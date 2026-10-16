"""S3 spike: transparent, always-on-top, click-through, never-focused overlay over WoW.

Shows a small translucent panel with a clock and a counter that updates once per second.
It never talks to the game: no input, no hooks, no game window access.
See docs/SPIKES.md#s3 for the checklist.

    uv run --with PySide6 spikes/s3_overlay.py [--x 40 --y 40 --w 320 --h 120] [--screen 0] [--opacity 0.85]
    uv run --with PySide6 spikes/s3_overlay.py --check      # print the window's extended styles and exit

Stop it with Ctrl+C in the console (the overlay itself cannot be clicked or focused, by design).
"""

from __future__ import annotations

import argparse
import signal
import sys
import time

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter
from PySide6.QtWidgets import QApplication, QWidget

IS_WIN = sys.platform == "win32"

GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
REQUIRED_EX = WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x1, 0x2, 0x10

if IS_WIN:
    import ctypes
    from ctypes import wintypes

    u32 = ctypes.WinDLL("user32", use_last_error=True)
    u32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    u32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    u32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    u32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    u32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                 ctypes.c_int, ctypes.c_uint]
    u32.GetForegroundWindow.restype = wintypes.HWND
    HWND_TOPMOST = wintypes.HWND(-1)


def describe_ex(ex: int) -> str:
    names = {WS_EX_TOPMOST: "TOPMOST", WS_EX_TRANSPARENT: "TRANSPARENT", WS_EX_TOOLWINDOW: "TOOLWINDOW",
             WS_EX_LAYERED: "LAYERED", WS_EX_NOACTIVATE: "NOACTIVATE"}
    return "|".join(n for bit, n in names.items() if ex & bit) or "none"


class Overlay(QWidget):
    def __init__(self, rect: QRect, opacity: float):
        # All flags are set before the first show(): changing them later re-creates the window (TECH_DECISIONS §2.2).
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setGeometry(rect)
        self.opacity = opacity
        self.counter = 0
        self.reasserts = 0
        self.started = time.monotonic()
        self.tick = QTimer(self, interval=1000, timeout=self.on_tick)
        self.tick.start()
        self.topmost = QTimer(self, interval=2000, timeout=self.reassert)   # keep topmost vs. other overlays
        self.topmost.start()

    def showEvent(self, e):
        super().showEvent(e)
        self.reassert()

    def hwnd(self) -> int:
        return int(self.winId())

    def ex_style(self) -> int:
        return u32.GetWindowLongPtrW(self.hwnd(), GWL_EXSTYLE) if IS_WIN else 0

    def reassert(self) -> None:
        if not IS_WIN:
            return
        h = self.hwnd()
        ex = self.ex_style()
        if ex & REQUIRED_EX != REQUIRED_EX:
            u32.SetWindowLongPtrW(h, GWL_EXSTYLE, ex | REQUIRED_EX)
        u32.SetWindowPos(h, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        self.reasserts += 1

    def on_tick(self) -> None:
        self.counter += 1
        if IS_WIN and self.counter % 10 == 0:
            fg = u32.GetForegroundWindow()
            print(f"[{self.counter:4d}s] ex={describe_ex(self.ex_style())} foreground_is_overlay={fg == self.hwnd()} "
                  f"reasserts={self.reasserts}", flush=True)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(12, 14, 20, int(255 * self.opacity * 0.75)))
        p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 10, 10)
        p.setPen(QColor(235, 238, 245, int(255 * self.opacity)))
        p.setFont(QFont("Segoe UI", 14, QFont.DemiBold))
        p.drawText(self.rect().adjusted(14, 10, -14, -10), Qt.AlignLeft | Qt.AlignTop, "RotationCoach S3")
        p.setFont(QFont("Consolas", 12))
        body = (f"{time.strftime('%H:%M:%S')}   tick {self.counter}\n"
                f"click-through · no focus")
        p.drawText(self.rect().adjusted(14, 40, -14, -10), Qt.AlignLeft | Qt.AlignTop, body)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--x", type=int, default=40)
    ap.add_argument("--y", type=int, default=40)
    ap.add_argument("--w", type=int, default=340)
    ap.add_argument("--h", type=int, default=110)
    ap.add_argument("--screen", type=int, default=0, help="monitor index (QGuiApplication.screens())")
    ap.add_argument("--opacity", type=float, default=0.85)
    ap.add_argument("--check", action="store_true", help="show, print window styles, exit")
    a = ap.parse_args(argv)

    app = QApplication(sys.argv[:1])
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    QTimer(app, interval=200, timeout=lambda: None).start()   # let Python handle Ctrl+C

    screens = QGuiApplication.screens()
    scr = screens[min(a.screen, len(screens) - 1)]
    g = scr.geometry()
    rect = QRect(g.x() + a.x, g.y() + a.y, a.w, a.h)
    w = Overlay(rect, a.opacity)
    w.show()
    for i, s in enumerate(screens):
        print(f"screen {i}: {s.name()} geometry={s.geometry().getRect()} dpr={s.devicePixelRatio()}")
    print(f"overlay on screen {a.screen} at {rect.getRect()} (logical px)")
    if IS_WIN:
        ex = w.ex_style()
        print(f"extended style: 0x{ex:08X} = {describe_ex(ex)}; required present: {ex & REQUIRED_EX == REQUIRED_EX}")
    if a.check:
        QTimer.singleShot(300, app.quit)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
