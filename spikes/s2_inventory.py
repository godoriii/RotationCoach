"""S2 spike: what Survival Hunter state can be reconstructed from a combat log alone?

Reads a recorded WoWCombatLog*.txt and writes an observability report (Markdown).
Standard library only. See docs/SPIKES.md#s2.

    python spikes/s2_inventory.py <WoWCombatLog-...txt> [--player "Name-Realm"] [--out spikes/results/S2_<name>.md]

What it measures
- header (log version, advanced flag, build)
- the player's event-type counts
- advanced-block length per event type  (settles the 17 vs 19 field question)
- where the player's own Focus is observable, and the advanced-block layout that fits
- presence of every watched spell/aura ID (casts, aura events, doses, damage, summons)
- aura durations (applied -> removed) for watched auras
- SPELL_CAST_FAILED reasons (localized strings)
- COMBATANT_INFO presence, spec ID position, talent tuple count
- Kill Command / Wildfire Bomb charge-model fit (max feasible recharge) and haste cross-check
"""

from __future__ import annotations

import argparse
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

SURVIVAL_SPEC_ID = 255
FOCUS = 2

# Spell / aura IDs from simc midnight SpellDataDump (docs/SCORING_SPEC.md §1.1, §6.1).
CASTS = {
    259489: "Kill Command", 186270: "Raptor Strike", 265189: "Raptor Strike (ranged)",
    1262293: "Raptor Swipe", 259495: "Wildfire Bomb", 1250646: "Takedown", 1261193: "Boomstick",
    1264949: "Moonlight Chakram", 190925: "Harpoon", 186289: "Aspect of the Eagle", 187707: "Muzzle",
}
AURAS = {
    260286: "Tip of the Spear", 1273155: "Raptor Swipe!", 1250646: "Takedown (buff)", 259388: "Mongoose Fury",
    1264946: "Moonlight Chakram window", 471878: "Howl ready: Wyvern", 472324: "Howl ready: Boar",
    472325: "Howl ready: Bear", 471877: "Howl cycle (cooldown aura)", 471881: "Wyvern's Cry",
    472640: "Hogstrider", 1253601: "Sentinel's Mark (debuff)", 470488: "Grenade Juggler",
    1252947: "Wildfire Imbuement", 1252741: "Wallop", 471536: "Tip lock (Boomstick, hidden?)",
    1280140: "Tip lock (Chakram, hidden?)", 1253750: "Stargazer", 260249: "Bloodseeker",
    186289: "Aspect of the Eagle",
}
DAMAGE = {
    1261215: "Boomstick tick", 265157: "Wildfire Bomb explosion", 269747: "Wildfire Bomb DoT",
    259277: "Kill Command (pet)", 1253733: "Lunar Storm", 1253859: "Takedown (player)",
    1253862: "Takedown (pet)", 1266081: "Moonlight Chakram dmg",
}
ENERGIZE = {1258571: "Takedown Focus"}
GCD_CASTS = {259489, 186270, 265189, 1262293, 259495, 1250646, 1261193, 1264949, 190925}

TS_RE = re.compile(r"^(\d{1,2})/(\d{1,2})(?:/(\d{4}))? (\d{1,2}):(\d{2}):(\d{2})\.(\d{3})([-+]?\d{1,2})?\s+")
GUID_RE = re.compile(r"^(Player|Creature|Pet|Vehicle|GameObject|Vignette|Item|0000000000000000)")


def split_fields(body: str) -> list[str]:
    """Comma split that respects "quoted strings" and nested [...] / (...)."""
    out, cur, depth, quoted = [], [], 0, False
    for ch in body:
        if quoted:
            if ch == '"':
                quoted = False
            else:
                cur.append(ch)
            continue
        if ch == '"':
            quoted = True
        elif ch in "[(":
            depth += 1
            cur.append(ch)
        elif ch in "])":
            depth -= 1
            cur.append(ch)
        elif ch == "," and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return out


def ts_seconds(m: re.Match) -> float:
    h, mi, s, ms = int(m.group(4)), int(m.group(5)), int(m.group(6)), int(m.group(7))
    day = int(m.group(2)) + 31 * int(m.group(1))          # monotonic enough within a session
    return day * 86400 + h * 3600 + mi * 60 + s + ms / 1000


def as_int(x: str) -> int | None:
    try:
        return int(x, 0) if x.startswith("0x") else int(x)
    except ValueError:
        return None


class Log:
    def __init__(self, path: Path):
        self.header = None
        self.rows: list[tuple[float, list[str]]] = []
        with open(path, encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                m = TS_RE.match(raw)
                if not m:
                    continue
                f = split_fields(raw[m.end():].rstrip("\r\n"))
                if f[0] == "COMBAT_LOG_VERSION" and self.header is None:
                    self.header = f
                self.rows.append((ts_seconds(m), f))
        self.rows.sort(key=lambda r: r[0])          # batches can be out of order (TECH_DECISIONS A.3)


def guess_player(log: Log) -> str | None:
    c = Counter()
    for _, f in log.rows:
        if f[0] == "SPELL_CAST_SUCCESS" and len(f) > 9 and as_int(f[9]) in CASTS and f[1].startswith("Player-"):
            c[f[1]] += 1
    return c.most_common(1)[0][0] if c else None


def adv_offset(event: str) -> int | None:
    """Index where the advanced block starts (TECH_DECISIONS A.2)."""
    if event.startswith("SWING_"):
        return 9
    if event.startswith(("SPELL_", "RANGE_")):
        return 12
    return None


SUFFIX_LEN = {"SPELL_CAST_SUCCESS": 0, "SPELL_ENERGIZE": 4, "SPELL_PERIODIC_ENERGIZE": 4}


def analyze(path: Path, player: str | None) -> str:
    log = Log(path)
    md = [f"# S2 report — `{path.name}`", ""]
    if log.header:
        md.append("- header: `" + ",".join(log.header) + "`")
    player = player_guid(log, player) or guess_player(log)
    if not player:
        md.append("- **no Survival casts found** (wrong file or wrong --player)")
        return "\n".join(md)
    md.append(f"- player GUID: `{player}` · lines: {len(log.rows):,}")
    pets = {f[5] for _, f in log.rows if f[0] == "SPELL_SUMMON" and f[1] == player}
    owner_pets = set()
    for _, f in log.rows:
        o = adv_offset(f[0])
        if o is not None and len(f) > o + 1 and f[o + 1] == player:
            owner_pets.add(f[o])
    pets |= owner_pets
    md.append(f"- pets/guardians owned by player: {len(pets)} (from SPELL_SUMMON + ownerGUID)")

    # --- event counts
    ev_src, ev_dst = Counter(), Counter()
    for _, f in log.rows:
        if len(f) > 5:
            if f[1] == player:
                ev_src[f[0]] += 1
            if f[5] == player:
                ev_dst[f[0]] += 1
    md += ["", "## Player events", "", "| event | as source | as dest |", "|---|---|---|"]
    for e in sorted(set(ev_src) | set(ev_dst)):
        md.append(f"| {e} | {ev_src[e]} | {ev_dst[e]} |")

    # --- advanced block length
    lens = defaultdict(Counter)
    for _, f in log.rows:
        if f[0] in SUFFIX_LEN and f[1] == player:
            o = adv_offset(f[0])
            lens[f[0]][len(f) - o - SUFFIX_LEN[f[0]]] += 1
    md += ["", "## Advanced block length (fields)", ""]
    adv_len = None
    for e, c in lens.items():
        md.append(f"- {e}: " + ", ".join(f"{k} fields ×{v}" for k, v in c.most_common()))
        if e == "SPELL_CAST_SUCCESS":
            adv_len = c.most_common(1)[0][0]
    if adv_len not in (17, 19):
        md.append(f"- ⚠ unexpected length {adv_len}; layout below assumes the closest known layout")
    idx = layout(adv_len or 17)
    md.append(f"- layout used: {adv_len or 17} fields → powerType@{idx['ptype']}, curPower@{idx['cur']}, "
              f"maxPower@{idx['max']}, cost@{idx['cost']}, x@{idx['x']}, y@{idx['y']}, map@{idx['map']}")

    # --- focus observability
    focus_obs = Counter()
    samples = []
    for t, f in log.rows:
        o = adv_offset(f[0])
        if o is None or len(f) < o + (adv_len or 17):
            continue
        if f[o] != player:
            continue
        ptypes = f[o + idx["ptype"]].split("|")
        if str(FOCUS) in ptypes:
            focus_obs[f[0]] += 1
            if len(samples) < 8 and f[0] == "SPELL_CAST_SUCCESS":
                k = ptypes.index(str(FOCUS))
                cur = f[o + idx["cur"]].split("|")[k]
                cost = f[o + idx["cost"]].split("|")[k]
                samples.append(f"{CASTS.get(as_int(f[9]), f[10])}: focus={cur} cost={cost}")
    md += ["", "## Player Focus observability (advanced block describes the player)", ""]
    md += [f"- {e}: {n}" for e, n in focus_obs.most_common()] or ["- **none found**"]
    if samples:
        md += ["- samples (SPELL_CAST_SUCCESS): " + "; ".join(samples),
               "- check: is `focus` before or after the cost? is `cost` in tenths?"]

    # --- positions
    pos = [(f[o + idx["x"]], f[o + idx["y"]]) for _, f in log.rows
           if (o := adv_offset(f[0])) is not None and f[0] == "SPELL_CAST_SUCCESS" and f[1] == player and len(f) > o + idx["y"]]
    md += ["", f"- player positions from SPELL_CAST_SUCCESS: {len(pos)} (first: {pos[:2]})"]

    # --- watched IDs
    seen = defaultdict(Counter)
    aura_times = defaultdict(list)
    open_aura = {}
    for t, f in log.rows:
        if len(f) < 10:
            continue
        sid = as_int(f[9])
        e = f[0]
        mine_src = f[1] == player or f[1] in pets
        on_me = f[5] == player
        if e.startswith("SPELL_AURA") and sid in AURAS and (on_me or (mine_src and sid == 1253601)):
            seen[sid][e] += 1
            key = (sid, f[5])
            if e == "SPELL_AURA_APPLIED":
                open_aura[key] = t
            elif e == "SPELL_AURA_REMOVED" and key in open_aura:
                aura_times[sid].append(t - open_aura.pop(key))
        elif mine_src and sid in CASTS and e in ("SPELL_CAST_SUCCESS", "SPELL_CAST_START", "SPELL_CAST_FAILED"):
            seen[sid][e] += 1
        elif mine_src and sid in DAMAGE and e.endswith("DAMAGE"):
            seen[sid][e] += 1
        elif mine_src and sid in ENERGIZE and "ENERGIZE" in e:
            seen[sid][e] += 1
        elif mine_src and e == "SPELL_SUMMON":
            seen[sid][e] += 1
    md += ["", "## Watched spell / aura IDs", "", "| id | name | kind | seen | events | durations s (median, n) |",
           "|---|---|---|---|---|---|"]
    for table, kind in ((CASTS, "cast"), (AURAS, "aura"), (DAMAGE, "damage"), (ENERGIZE, "energize")):
        for sid, name in table.items():
            evs = seen.get(sid, {})
            evs_k = {k: v for k, v in evs.items() if (kind == "aura") == k.startswith("SPELL_AURA")}
            d = aura_times.get(sid, [])
            dur = f"{statistics.median(d):.2f} ({len(d)})" if d and kind == "aura" else ""
            md.append(f"| {sid} | {name} | {kind} | {'✅' if evs_k else '—'} | "
                      + ", ".join(f"{k.replace('SPELL_', '')}×{v}" for k, v in sorted(evs_k.items())) + f" | {dur} |")
    summons = Counter(f[10] for _, f in log.rows if f[0] == "SPELL_SUMMON" and f[1] == player)
    if summons:
        md.append("\n- player SPELL_SUMMON: " + ", ".join(f"{n}×{c}" for n, c in summons.most_common()))
    unknown_auras = Counter((as_int(f[9]), f[10]) for _, f in log.rows
                            if f[0] == "SPELL_AURA_APPLIED" and f[5] == player and as_int(f[9]) not in AURAS)
    if unknown_auras:
        md.append("- other auras applied to player (top 25, for ID discovery): " + ", ".join(
            f"{n} ({i})×{c}" for (i, n), c in unknown_auras.most_common(25)))

    # --- failures
    fails = Counter((CASTS.get(as_int(f[9]), f[10]), f[-1]) for _, f in log.rows
                    if f[0] == "SPELL_CAST_FAILED" and f[1] == player and len(f) > 12)
    md += ["", "## SPELL_CAST_FAILED (player)", ""]
    md += [f"- {s}: \"{r}\" ×{c}" for (s, r), c in fails.most_common(30)] or ["- none"]
    other_fail_src = Counter(f[1].split("-")[0] for _, f in log.rows if f[0] == "SPELL_CAST_FAILED" and f[1] != player)
    md.append(f"- failures from other sources: {dict(other_fail_src) or 'none'}")

    # --- combatant info
    ci = [f for _, f in log.rows if f[0] == "COMBATANT_INFO" and f[1] == player]
    md += ["", "## COMBATANT_INFO", ""]
    if not ci:
        md.append("- none for the player (expected outside ENCOUNTER_START / CHALLENGE_MODE_START)")
    else:
        f = ci[0]
        spec_pos = [i for i, x in enumerate(f) if x == str(SURVIVAL_SPEC_ID)]
        talents = next((x for x in f if x.startswith("[(")), "")
        md += [f"- count: {len(ci)}, fields: {len(f)}, index of value {SURVIVAL_SPEC_ID} (Survival spec id): {spec_pos}",
               f"- talent tuples: {talents.count('(')}, first: `{talents[:80]}`"]

    # --- cooldown models
    md += ["", "## Charge-model fit", ""]
    casts = defaultdict(list)
    gcd_times = []
    for t, f in log.rows:
        if f[0] == "SPELL_CAST_SUCCESS" and f[1] == player and len(f) > 9:
            sid = as_int(f[9])
            casts[sid].append(t)
            if sid in GCD_CASTS:
                gcd_times.append(t)
    gaps = [b - a for a, b in zip(gcd_times, gcd_times[1:]) if 0.5 < b - a < 3]
    gcd_est = pct(gaps, 5) if gaps else None
    if gcd_est:
        md.append(f"- GCD estimate (5th percentile of consecutive GCD casts): {gcd_est:.3f} s → haste ≈ {1.5 / gcd_est - 1:+.1%}")
    kc = casts.get(259489, [])
    if len(kc) >= 4:
        r = max_feasible_recharge(kc, charges=2)
        md.append(f"- Kill Command ({len(kc)} casts), 2 charges: max feasible recharge {r:.3f} s "
                  f"(nominal 5 s ⇒ implied haste {5 / r - 1:+.1%}).")
    wfb = casts.get(259495, [])
    if len(wfb) >= 3:
        for ch in (1, 2):
            r0 = max_feasible_recharge(wfb, charges=ch)
            r1 = max_feasible_recharge(wfb, charges=ch, reductions=[(t, 1.0) for t in kc])
            md.append(f"- Wildfire Bomb ({len(wfb)} casts), {ch} charge(s): max feasible recharge {r0:.2f} s without CDR; "
                      f"{r1:.2f} s with Wildfire Infusion (−1 s per Kill Command). Nominal 18 s / (1+haste).")
    md += ["", "Interpretation: the max feasible recharge is the longest recharge that never makes a cast happen at 0 charges. "
           "When casts were pressed as soon as possible (S2 steps 2–3) it approximates the true recharge; compare it to "
           "nominal/(1+haste). A big gap means a missing cooldown-reduction rule."]
    return "\n".join(md)


def layout(n: int) -> dict[str, int]:
    # 17 (wiki): guid, owner, hp, maxhp, ap, sp, armor, absorb, ptype, cur, max, cost, x, y, map, facing, level
    # 19 (12.x per WowCoach): two always-0 fields after absorb
    extra = 2 if n >= 19 else 0
    base = 8 + extra
    return {"ptype": base, "cur": base + 1, "max": base + 2, "cost": base + 3, "x": base + 4, "y": base + 5,
            "map": base + 6}


def player_guid(log: Log, name: str | None) -> str | None:
    if not name:
        return None
    for _, f in log.rows:
        if len(f) > 2 and f[1].startswith("Player-") and f[2].split("-")[0] == name.split("-")[0]:
            return f[1]
    return None


def pct(vals: list[float], p: float) -> float:
    s = sorted(vals)
    k = (len(s) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def feasible(casts: list[float], charges: int, recharge: float, reductions: list[tuple[float, float]]) -> bool:
    """Simulate a charge cooldown (recharge one charge at a time) and check every cast had a charge."""
    events = sorted([(t, 0, 0.0) for t in casts] + [(t, 1, a) for t, a in reductions])
    have, progress, last = charges, 0.0, events[0][0] if events else 0.0
    for t, kind, amount in events:
        if have < charges:
            progress += t - last
            while progress >= recharge and have < charges:
                progress -= recharge
                have += 1
            if have == charges:
                progress = 0.0
        last = t
        if kind == 1:
            if have < charges:
                progress += amount
                while progress >= recharge and have < charges:
                    progress -= recharge
                    have += 1
                if have == charges:
                    progress = 0.0
            continue
        if have < 1 - 1e-9:
            return False
        have -= 1
    return True


def max_feasible_recharge(casts: list[float], charges: int, reductions=()) -> float:
    lo, hi = 0.1, 120.0
    if not feasible(casts, charges, lo, list(reductions)):
        return float("nan")
    for _ in range(50):
        mid = (lo + hi) / 2
        if feasible(casts, charges, mid, list(reductions)):
            lo = mid
        else:
            hi = mid
    return lo


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log", type=Path)
    ap.add_argument("--player")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    md = analyze(a.log, a.player)
    if a.out:
        a.out.write_text(md + "\n", encoding="utf-8")
        print(f"wrote {a.out}")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
