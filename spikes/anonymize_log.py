"""Anonymize a WoW combat log before sharing or committing it (NFR-S3).

Replaces every Player/Pet GUID with a stable fake GUID and every player/pet name with an alias.
Spell IDs, timings, numbers and NPC names are kept (they are what the analysis needs).

    python spikes/anonymize_log.py <in.txt> <out.txt> [--me "Name-Realm"]

--me gives your own character the alias "Me-Realm0" so reports stay readable.
A mapping file (<out>.map.txt) is written next to the output; keep it local, do not commit it.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

GUID_RE = re.compile(r"\b(Player|Pet)-(\d+)-([0-9A-F]+)\b")
# GUID followed by its quoted name: Player-1-ABC,"Name-Realm"
GUID_NAME_RE = re.compile(r"\b((?:Player|Pet)-\d+-[0-9A-F]+),\"([^\"]*)\"")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", type=Path)
    ap.add_argument("dst", type=Path)
    ap.add_argument("--me", help="your character name (Name or Name-Realm)")
    a = ap.parse_args(argv)

    guids: dict[str, str] = {}
    names: dict[str, str] = {}
    counters = {"Player": 0, "Pet": 0}
    me = a.me.split("-")[0] if a.me else None

    def alias_guid(kind: str, guid: str) -> str:
        if guid not in guids:
            counters[kind] += 1
            guids[guid] = f"{kind}-0-{counters[kind]:08X}"
        return guids[guid]

    # pass 1: collect names attached to Player/Pet GUIDs
    with open(a.src, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            for guid, name in GUID_NAME_RE.findall(line):
                kind = guid.split("-")[0]
                g = alias_guid(kind, guid)
                if name and name != "nil" and name not in names:
                    if kind == "Player" and me and name.split("-")[0] == me:
                        names[name] = "Me-Realm0"
                    else:
                        names[name] = f"{kind}{int(g.split('-')[2], 16)}" + ("-Realm0" if kind == "Player" else "")

    name_re = re.compile("\"(" + "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)) + ")\"") if names else None

    # pass 2: rewrite
    with open(a.src, encoding="utf-8", errors="replace") as fin, open(a.dst, "w", encoding="utf-8", newline="") as fout:
        for line in fin:
            line = GUID_RE.sub(lambda m: alias_guid(m.group(1), m.group(0)), line)
            if name_re:
                line = name_re.sub(lambda m: f"\"{names[m.group(1)]}\"", line)
            fout.write(line)

    with open(str(a.dst) + ".map.txt", "w", encoding="utf-8") as fm:
        for k, v in sorted(names.items(), key=lambda kv: kv[1]):
            fm.write(f"{v}\t{k}\n")
    print(f"wrote {a.dst} ({counters['Player']} players, {counters['Pet']} pets anonymized); mapping: {a.dst}.map.txt (keep local)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
