"""S1 spike: measure when WoW writes the combat log and in what chunks (+ S7 tail verification).

Read-only. It never touches the game: it only watches the Logs folder.
Standard library only. See docs/SPIKES.md#s1 and #s7.

Record (run while playing, Ctrl+C to stop):
    python spikes/s1_log_latency.py record --logs "C:\\Program Files (x86)\\World of Warcraft\\_retail_\\Logs"
        --out spikes/results/s1_run1  [--mirror]   (--mirror = S7: keep a byte copy of everything read)
    While recording, type a label in this console and press Enter to drop a marker
    (e.g. "start dummy", "end dummy", "reload"). Plain Enter = "mark".

Analyze:
    python spikes/s1_log_latency.py analyze spikes/results/s1_run1      -> writes report.md there

Verify (S7, after recording with --mirror):
    python spikes/s1_log_latency.py verify spikes/results/s1_run1 --logs "<same Logs folder>"
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import statistics
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

POLL_S = 0.02
DIR_SCAN_S = 0.5
LOG_GLOB = "WoWCombatLog*.txt"

# "5/8/2026 21:47:12.841-5  EVENT,..."  (new)   or   "11/21 12:01:34.071  EVENT,..." (old)
TS_RE = re.compile(
    r"^(?P<mo>\d{1,2})/(?P<d>\d{1,2})(?:/(?P<y>\d{4}))? (?P<h>\d{1,2}):(?P<mi>\d{2}):(?P<s>\d{2})\.(?P<ms>\d{3})(?P<off>[-+]?\d{1,2})?\s"
)


def parse_ts_ms(line: str, default_year: int) -> int | None:
    """Log timestamp -> epoch milliseconds (None if the line has no timestamp)."""
    m = TS_RE.match(line)
    if not m:
        return None
    y = int(m.group("y") or default_year)
    dt = datetime(y, int(m.group("mo")), int(m.group("d")), int(m.group("h")), int(m.group("mi")),
                  int(m.group("s")), int(m.group("ms")) * 1000)
    if m.group("off") is not None:
        dt = dt.replace(tzinfo=timezone(timedelta(hours=int(m.group("off")))))
        return int(dt.timestamp() * 1000)
    return int(time.mktime(dt.timetuple()) * 1000 + int(m.group("ms")))


def event_name(line: str) -> str:
    m = TS_RE.match(line)
    rest = line[m.end():].lstrip() if m else line
    return rest.split(",", 1)[0]


# ---------------------------------------------------------------------------
# Shared-mode open (Windows) so the game can keep writing / rotating its files
# ---------------------------------------------------------------------------

def open_shared(path: Path):
    if os.name != "nt":
        return open(path, "rb")
    import ctypes
    import msvcrt
    from ctypes import wintypes

    GENERIC_READ = 0x80000000
    FILE_SHARE_ALL = 0x1 | 0x2 | 0x4          # READ | WRITE | DELETE
    OPEN_EXISTING = 3
    FILE_ATTRIBUTE_NORMAL = 0x80
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    h = k32.CreateFileW(str(path), GENERIC_READ, FILE_SHARE_ALL, None, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None)
    if h in (None, wintypes.HANDLE(-1).value):
        raise OSError(ctypes.get_last_error(), f"CreateFileW failed for {path}")
    fd = msvcrt.open_osfhandle(h, os.O_RDONLY | os.O_BINARY)
    return os.fdopen(fd, "rb")


def newest_log(logs: Path) -> Path | None:
    files = list(logs.glob(LOG_GLOB))
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


# ---------------------------------------------------------------------------
# Record
# ---------------------------------------------------------------------------

CHUNK_FIELDS = ["arrival_ms", "file", "offset", "bytes", "lines", "first_ts", "last_ts", "min_ts", "max_ts",
                "out_of_order", "max_backjump_ms", "lag_min_ms", "lag_max_ms", "headers", "encounter_starts",
                "encounter_ends"]


@dataclass
class Tail:
    path: Path
    fh: object
    offset: int
    partial: bytes = b""


def record(args) -> int:
    logs: Path = args.logs
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    mirror_dir = out / "mirror"
    if args.mirror:
        mirror_dir.mkdir(exist_ok=True)
    year = datetime.now().year

    chunks_f = open(out / "chunks.csv", "w", newline="", encoding="utf-8")
    chunks = csv.DictWriter(chunks_f, fieldnames=CHUNK_FIELDS)
    chunks.writeheader()
    markers_f = open(out / "markers.csv", "w", newline="", encoding="utf-8")
    markers = csv.writer(markers_f)
    markers.writerow(["arrival_ms", "label"])
    events_f = open(out / "events.csv", "w", newline="", encoding="utf-8")   # boundary events only
    events = csv.writer(events_f)
    events.writerow(["arrival_ms", "ts_ms", "event", "text"])
    meta = {"started_ms": time.time_ns() // 1_000_000, "logs": str(logs), "files": {}, "poll_s": POLL_S,
            "platform": sys.platform, "python": sys.version.split()[0]}

    def marker_thread():
        for raw in sys.stdin:
            label = raw.strip() or "mark"
            markers.writerow([time.time_ns() // 1_000_000, label])
            markers_f.flush()
            print(f"  [marker] {label}")

    threading.Thread(target=marker_thread, daemon=True).start()

    tail: Tail | None = None
    last_scan = 0.0
    print(f"watching {logs}  (Ctrl+C to stop; type a label + Enter to mark)")
    try:
        while True:
            now = time.monotonic()
            if now - last_scan >= DIR_SCAN_S:
                last_scan = now
                cand = newest_log(logs)
                if cand and (tail is None or cand != tail.path):
                    if tail is not None:
                        drain(tail, chunks, events, year, mirror_dir if args.mirror else None)
                        meta["files"][tail.path.name]["end_offset"] = tail.offset
                        tail.fh.close()
                    start = 0 if (tail is not None or args.from_start) else cand.stat().st_size
                    tail = Tail(cand, open_shared(cand), start)
                    tail.fh.seek(start)
                    meta["files"][cand.name] = {"start_offset": start, "opened_ms": time.time_ns() // 1_000_000}
                    print(f"  following {cand.name} from offset {start}")
            if tail is not None:
                drain(tail, chunks, events, year, mirror_dir if args.mirror else None)
            time.sleep(POLL_S)
    except KeyboardInterrupt:
        pass
    finally:
        if tail is not None:
            drain(tail, chunks, events, year, mirror_dir if args.mirror else None)
            meta["files"][tail.path.name]["end_offset"] = tail.offset
            tail.fh.close()
        meta["stopped_ms"] = time.time_ns() // 1_000_000
        (out / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        for f in (chunks_f, markers_f, events_f):
            f.close()
        print(f"saved to {out}")
    return 0


def drain(tail: Tail, chunks, events, year: int, mirror_dir: Path | None) -> None:
    try:
        size = os.fstat(tail.fh.fileno()).st_size
    except OSError:
        return
    if size < tail.offset:                       # truncated / replaced in place
        print(f"  {tail.path.name} shrank ({tail.offset} -> {size}); restarting at 0")
        tail.offset, tail.partial = 0, b""
        tail.fh.seek(0)
    if size == tail.offset:
        return
    data = tail.fh.read(size - tail.offset)
    arrival = time.time_ns() // 1_000_000
    if mirror_dir is not None:
        with open(mirror_dir / tail.path.name, "ab") as m:
            m.write(data)
    chunk_offset = tail.offset
    tail.offset += len(data)
    buf = tail.partial + data
    *lines, tail.partial = buf.split(b"\n")
    if not lines:
        return
    ts_list, headers, enc_s, enc_e = [], 0, 0, 0
    for raw in lines:
        line = raw.decode("utf-8", "replace").rstrip("\r")
        ts = parse_ts_ms(line, year)
        if ts is None:
            continue
        ts_list.append(ts)
        ev = event_name(line)
        if ev in ("COMBAT_LOG_VERSION", "ENCOUNTER_START", "ENCOUNTER_END", "CHALLENGE_MODE_START",
                  "CHALLENGE_MODE_END", "ZONE_CHANGE", "MAP_CHANGE", "COMBATANT_INFO"):
            headers += ev == "COMBAT_LOG_VERSION"
            enc_s += ev == "ENCOUNTER_START"
            enc_e += ev == "ENCOUNTER_END"
            events.writerow([arrival, ts, ev, line[:160] if ev != "COMBATANT_INFO" else line[:60]])
    if not ts_list:
        return
    ooo, back, run_max = 0, 0, ts_list[0]
    for ts in ts_list[1:]:
        if ts < run_max:
            ooo += 1
            back = max(back, run_max - ts)
        run_max = max(run_max, ts)
    chunks.writerow({
        "arrival_ms": arrival, "file": tail.path.name, "offset": chunk_offset, "bytes": len(data),
        "lines": len(lines), "first_ts": ts_list[0], "last_ts": ts_list[-1], "min_ts": min(ts_list),
        "max_ts": max(ts_list), "out_of_order": ooo, "max_backjump_ms": back,
        "lag_min_ms": arrival - max(ts_list), "lag_max_ms": arrival - min(ts_list),
        "headers": headers, "encounter_starts": enc_s, "encounter_ends": enc_e,
    })


# ---------------------------------------------------------------------------
# Analyze
# ---------------------------------------------------------------------------

def pct(vals: list[float], p: float) -> float:
    if not vals:
        return float("nan")
    s = sorted(vals)
    k = (len(s) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def analyze(args) -> int:
    run: Path = args.run
    rows = list(csv.DictReader(open(run / "chunks.csv", encoding="utf-8")))
    for r in rows:
        for k in CHUNK_FIELDS:
            if k != "file":
                r[k] = int(r[k])
    markers = [(int(a), l) for a, l in list(csv.reader(open(run / "markers.csv", encoding="utf-8")))[1:]]
    md = [f"# S1 report — {run.name}", ""]
    if not rows:
        md.append("No data chunks were recorded.")
        (run / "report.md").write_text("\n".join(md), encoding="utf-8")
        print("\n".join(md))
        return 0

    t0 = rows[0]["arrival_ms"]
    total_lines = sum(r["lines"] for r in rows)
    md += ["## Chunks", "",
           f"- chunks: {len(rows)}, lines: {total_lines}, bytes: {sum(r['bytes'] for r in rows):,}",
           f"- lines per chunk: p50 {pct([r['lines'] for r in rows], 50):.0f}, p95 {pct([r['lines'] for r in rows], 95):.0f}, max {max(r['lines'] for r in rows)}",
           f"- chunk lag (arrival − newest line in chunk), ms: p50 {pct([r['lag_min_ms'] for r in rows], 50):.0f}, "
           f"p95 {pct([r['lag_min_ms'] for r in rows], 95):.0f}, max {max(r['lag_min_ms'] for r in rows)}",
           f"- chunk lag (arrival − oldest line in chunk), ms: p50 {pct([r['lag_max_ms'] for r in rows], 50):.0f}, "
           f"p95 {pct([r['lag_max_ms'] for r in rows], 95):.0f}, max {max(r['lag_max_ms'] for r in rows)}",
           f"- out-of-order lines: {sum(r['out_of_order'] for r in rows)} "
           f"({100 * sum(r['out_of_order'] for r in rows) / max(total_lines, 1):.2f}%), "
           f"max back-jump {max(r['max_backjump_ms'] for r in rows)} ms", ""]
    med_lag = pct([r["lag_min_ms"] for r in rows], 50)
    if abs(med_lag) > 3_600_000:
        md += [f"> **Clock warning**: median lag is {med_lag / 3_600_000:.1f} h. The UTC offset written in the log "
               "does not match this PC's clock/time zone, so absolute lags are wrong (chunk sizes and ordering are still valid).", ""]

    # Segments by log-time gaps (works without markers): consecutive lines > 5 s apart start a new segment.
    segs = []
    for r in sorted(rows, key=lambda r: r["min_ts"]):
        if segs and r["min_ts"] - segs[-1]["max_ts"] <= 5000:
            s = segs[-1]
            s["max_ts"] = max(s["max_ts"], r["max_ts"])
            s["last_arrival"] = max(s["last_arrival"], r["arrival_ms"])
            s["first_arrival"] = min(s["first_arrival"], r["arrival_ms"])
            s["chunks"] += 1
            s["lines"] += r["lines"]
        else:
            segs.append({"min_ts": r["min_ts"], "max_ts": r["max_ts"], "first_arrival": r["arrival_ms"],
                         "last_arrival": r["arrival_ms"], "chunks": 1, "lines": r["lines"]})
    md += ["## Activity segments (log-time gap > 5 s)", "",
           "| # | log span s | lines | chunks | first line written after (s) | last line written after (s) | written during segment? |",
           "|---|---|---|---|---|---|---|"]
    for i, s in enumerate(segs, 1):
        during = "yes" if s["first_arrival"] < s["max_ts"] else "no (all after)"
        md.append(f"| {i} | {(s['max_ts'] - s['min_ts']) / 1000:.1f} | {s['lines']} | {s['chunks']} | "
                  f"{(s['first_arrival'] - s['min_ts']) / 1000:.1f} | {(s['last_arrival'] - s['max_ts']) / 1000:.1f} | {during} |")

    if markers:
        md += ["", "## Markers", "", "| label | at (s from first chunk) | lines arrived in next 10 s | lines with log-time ≤ marker arriving after it |",
               "|---|---|---|---|"]
        for at, label in markers:
            nxt = sum(r["lines"] for r in rows if at <= r["arrival_ms"] < at + 10_000)
            late = sum(r["lines"] for r in rows if r["arrival_ms"] > at and r["min_ts"] <= at)
            md.append(f"| {label} | {(at - t0) / 1000:.1f} | {nxt} | {late} (chunks starting before marker) |")
        # marker pairs "start X" / "end X"
        starts = {l[6:]: a for a, l in markers if l.startswith("start ")}
        ends = {l[4:]: a for a, l in markers if l.startswith("end ")}
        pairs = [(k, starts[k], ends[k]) for k in starts if k in ends]
        if pairs:
            md += ["", "## Combat windows (start/end markers)", "",
                   "| window | duration s | lines logged in window | of which arrived before 'end' | last in-window line arrived after 'end' (s) |",
                   "|---|---|---|---|---|"]
            for k, a, b in pairs:
                in_win = [r for r in rows if r["max_ts"] >= a and r["min_ts"] <= b]
                lines = sum(r["lines"] for r in in_win)
                before = sum(r["lines"] for r in in_win if r["arrival_ms"] < b)
                last = max((r["arrival_ms"] for r in in_win), default=b)
                md.append(f"| {k} | {(b - a) / 1000:.1f} | {lines} | {before} ({100 * before / max(lines, 1):.0f}%) | {(last - b) / 1000:.1f} |")

    md += ["", "## How to read", "",
           "- 'written during segment? = no' and ~0% 'arrived before end' ⇒ the client batches the whole fight and writes it after combat (10.2 behaviour).",
           "- 'last line written after' is the delay we must wait after combat before scoring (NFR-L3 budget).",
           "- Out-of-order lines confirm the need for the reorder step in the tailer (ARCHITECTURE §4.1)."]
    (run / "report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    return 0


# ---------------------------------------------------------------------------
# Verify (S7)
# ---------------------------------------------------------------------------

def verify(args) -> int:
    run: Path = args.run
    meta = json.loads((run / "meta.json").read_text(encoding="utf-8"))
    ok = True
    for name, info in meta["files"].items():
        mirror = run / "mirror" / name
        real = args.logs / name
        if not mirror.exists():
            if info.get("end_offset", info["start_offset"]) == info["start_offset"]:
                print(f"{name}: OK  nothing was written while it was followed")
            else:
                print(f"{name}: no mirror (record with --mirror)")
                ok = False
            continue
        got = mirror.read_bytes()
        with open_shared(real) as fh:
            fh.seek(info["start_offset"])
            want = fh.read(len(got))
            rest = fh.read()
        if got == want:
            print(f"{name}: OK  {len(got):,} bytes identical from offset {info['start_offset']}"
                  + (f"  (+{len(rest):,} bytes written after recording stopped)" if rest else ""))
        else:
            ok = False
            i = next((k for k, (x, y) in enumerate(zip(got, want)) if x != y), min(len(got), len(want)))
            print(f"{name}: MISMATCH at byte {info['start_offset'] + i} (mirror {len(got):,} vs file {len(want):,})")
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    r.add_argument("--logs", type=Path, required=True)
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--mirror", action="store_true", help="S7: keep a byte copy of everything read")
    r.add_argument("--from-start", action="store_true", help="read the current file from the beginning")
    a = sub.add_parser("analyze")
    a.add_argument("run", type=Path)
    v = sub.add_parser("verify")
    v.add_argument("run", type=Path)
    v.add_argument("--logs", type=Path, required=True)
    args = ap.parse_args(argv)
    return {"record": record, "analyze": analyze, "verify": verify}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
