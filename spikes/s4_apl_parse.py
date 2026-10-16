"""S4 spike: SimC APL parsing, 3-valued evaluation, and expression term inventory.

Throwaway prototype (see docs/SPIKES.md#s4). Standard library only.

The lexer, operator precedence and shunting-yard conversion mirror
simc engine/sim/expressions.cpp (midnight @ 76f8118c) so that we parse
conditions exactly the way SimC does.

Usage:
    python spikes/s4_apl_parse.py spikes/data/hunter_survival@76f8118c.simc [--compare OTHER.simc] [--out report.md]
    python spikes/s4_apl_parse.py --selftest
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Lexer (mirrors simc lexer_t::next)
# ---------------------------------------------------------------------------

NUM, STR, LPAR, RPAR = "NUM", "STR", "(", ")"
UNARY = {"!", "u+", "u-", "@", "floor", "ceil"}

# Precedence table copied from simc expression::precedence().
PRECEDENCE = {
    "floor": 9, "ceil": 9,
    "!": 8, "u+": 8, "u-": 8, "@": 8,
    "*": 7, "%": 7, "%%": 7,
    "+": 6, "-": 6,
    "<?": 5, ">?": 5,          # <? = max, >? = min
    "=": 4, "!=": 4, "<": 4, "<=": 4, ">": 4, ">=": 4,
    "~": 4, "!~": 4,           # in / not in (string ops, unused by our APLs)
    "&": 3,
    "^": 2,
    "|": 1,
}


@dataclass(frozen=True)
class Tok:
    kind: str
    text: str


class LexError(ValueError):
    pass


def lex(expr: str) -> list[Tok]:
    toks: list[Tok] = []
    i, n = 0, len(expr)
    while i < n:
        ch = expr[i]
        if ch.isdigit():
            j = i + 1
            while j < n and expr[j].isdigit():
                j += 1
            if j < n and expr[j] == ".":
                j += 1
                while j < n and expr[j].isdigit():
                    j += 1
            toks.append(Tok(NUM, expr[i:j]))
            i = j
            continue
        if ch.isascii() and ch.isalpha():
            j = i + 1
            while j < n and (expr[j].isascii() and (expr[j].isalnum() or expr[j] in "_.")):
                j += 1
            toks.append(Tok(STR, expr[i:j]))
            i = j
            continue
        two = expr[i:i + 2]
        if two in ("%%", "<=", ">=", "!=", "<?", ">?", "!~", "&&", "||", "^^", "=="):
            op = {"&&": "&", "||": "|", "^^": "^", "==": "="}.get(two, two)
            toks.append(Tok(op, op))
            i += 2
            continue
        if ch in "()+-*%@&|^=!<>~":
            toks.append(Tok(ch, ch))
            i += 1
            continue
        if ch.isspace():
            raise LexError(f"whitespace is not valid in SimC expressions: {expr!r}")
        raise LexError(f"unexpected character {ch!r} in {expr!r}")

    # Post-processing from simc parse_tokens(): unary/binary +/-, floor/ceil, negative literals.
    out: list[Tok] = []
    prev = None
    for t in toks:
        left_side = prev in (STR, NUM, RPAR)
        kind = t.kind
        if kind == "-" and not left_side:
            kind = "u-"
        elif kind == "+" and not left_side:
            kind = "u+"
        if kind == LPAR and prev == STR and out[-1].text.lower() in ("floor", "ceil"):
            out[-1] = Tok(out[-1].text.lower(), out[-1].text.lower())
        if kind == NUM and prev == "u-":
            out[-1] = Tok(NUM, "-" + t.text)
            prev = NUM
            continue
        out.append(Tok(kind, t.text))
        prev = kind
    return out


def to_rpn(tokens: list[Tok]) -> list[Tok]:
    """Shunting-yard exactly as simc convert_to_rpn (all operators left-associative)."""
    rpn: list[Tok] = []
    stack: list[Tok] = []
    for t in tokens:
        if t.kind in (NUM, STR):
            rpn.append(t)
        elif t.kind == LPAR:
            stack.append(t)
        elif t.kind == RPAR:
            while True:
                if not stack:
                    raise ValueError("unbalanced ')'")
                s = stack.pop()
                if s.kind == LPAR:
                    break
                rpn.append(s)
        else:
            while stack and stack[-1].kind != LPAR and not (PRECEDENCE[t.kind] > PRECEDENCE[stack[-1].kind]):
                rpn.append(stack.pop())
            stack.append(t)
    while stack:
        s = stack.pop()
        if s.kind == LPAR:
            raise ValueError("unbalanced '('")
        rpn.append(s)
    return rpn


# ---------------------------------------------------------------------------
# AST
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Node:
    op: str                      # "num", "term", or an operator
    args: tuple = ()
    value: str = ""

    def __str__(self) -> str:
        if self.op == "num":
            return self.value
        if self.op == "term":
            return self.value
        if len(self.args) == 1:
            return f"{self.op}({self.args[0]})"
        return f"({self.args[0]} {self.op} {self.args[1]})"


def parse_expr(expr: str) -> Node:
    stack: list[Node] = []
    for t in to_rpn(lex(expr)):
        if t.kind == NUM:
            stack.append(Node("num", value=t.text))
        elif t.kind == STR:
            stack.append(Node("term", value=t.text))
        elif t.kind in UNARY:
            if not stack:
                raise ValueError(f"missing operand for {t.kind} in {expr!r}")
            stack.append(Node(t.kind, (stack.pop(),)))
        else:
            if len(stack) < 2:
                raise ValueError(f"missing operand for {t.kind} in {expr!r}")
            r, l = stack.pop(), stack.pop()
            stack.append(Node(t.kind, (l, r)))
    if len(stack) != 1:
        raise ValueError(f"malformed expression {expr!r}")
    return stack[0]


def terms_of(node: Node) -> set[str]:
    if node.op == "term":
        return {node.value}
    out: set[str] = set()
    for a in node.args:
        out |= terms_of(a)
    return out


# ---------------------------------------------------------------------------
# Interval values and 3-valued evaluation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Iv:
    """Closed interval [lo, hi]. A point value has lo == hi.

    `fair` marks intervals that exist only because of a deliberate fairness
    tolerance (reaction window, boundary epsilon); model uncertainty has fair=False.
    """
    lo: float
    hi: float
    fair: bool = False

    @staticmethod
    def pt(v: float) -> "Iv":
        return Iv(v, v, True)

    @property
    def certain(self) -> bool:
        return self.lo == self.hi

    def truth(self) -> str:
        if self.lo == 0 and self.hi == 0:
            return "false"
        if self.lo > 0 or self.hi < 0:
            return "true"
        return "unknown"


UNKNOWN = Iv(-math.inf, math.inf, False)
T, F, TF_FAIR, TF_MODEL = Iv(1, 1, True), Iv(0, 0, True), Iv(0, 1, True), Iv(0, 1, False)


def _bool(truth: str, fair: bool) -> Iv:
    return T if truth == "true" else F if truth == "false" else (TF_FAIR if fair else TF_MODEL)


def _arith(op: str, a: Iv, b: Iv) -> Iv:
    fair = a.fair and b.fair
    if op in ("+", "-", "*", "%"):
        if op == "+":
            vals = [a.lo + b.lo, a.hi + b.hi]
        elif op == "-":
            vals = [a.lo - b.hi, a.hi - b.lo]
        elif op == "*":
            vals = [x * y for x in (a.lo, a.hi) for y in (b.lo, b.hi) if not (math.isinf(x) and y == 0 or math.isinf(y) and x == 0)] or [0.0]
        else:  # SimC '%' is division
            if b.lo <= 0 <= b.hi:
                return UNKNOWN if not (a.certain and b.certain) else Iv.pt(math.inf if a.lo else math.nan)
            vals = [x / y for x in (a.lo, a.hi) for y in (b.lo, b.hi)]
        return Iv(min(vals), max(vals), fair)
    if op == "<?":
        return Iv(max(a.lo, b.lo), max(a.hi, b.hi), fair)
    if op == ">?":
        return Iv(min(a.lo, b.lo), min(a.hi, b.hi), fair)
    if op == "%%":
        if a.certain and b.certain and b.lo != 0:
            return Iv.pt(math.fmod(a.lo, b.lo))
        return UNKNOWN
    raise ValueError(op)


def _compare(op: str, a: Iv, b: Iv) -> Iv:
    fair = a.fair and b.fair
    if op == "<":
        t = "true" if a.hi < b.lo else "false" if a.lo >= b.hi else "unknown"
    elif op == "<=":
        t = "true" if a.hi <= b.lo else "false" if a.lo > b.hi else "unknown"
    elif op == ">":
        t = "true" if a.lo > b.hi else "false" if a.hi <= b.lo else "unknown"
    elif op == ">=":
        t = "true" if a.lo >= b.hi else "false" if a.hi < b.lo else "unknown"
    elif op in ("=", "!="):
        if a.certain and b.certain:
            t = "true" if a.lo == b.lo else "false"
        elif a.hi < b.lo or b.hi < a.lo:
            t = "false"
        else:
            t = "unknown"
        if op == "!=" and t != "unknown":
            t = "false" if t == "true" else "true"
    else:
        raise ValueError(op)
    return _bool(t, fair)


def evaluate(node: Node, lookup) -> Iv:
    """lookup(term:str) -> Iv. Unknown terms should return UNKNOWN."""
    op = node.op
    if op == "num":
        return Iv.pt(float(node.value))
    if op == "term":
        return lookup(node.value)
    if op == "!":
        return _bool({"true": "false", "false": "true", "unknown": "unknown"}[evaluate(node.args[0], lookup).truth()],
                     evaluate(node.args[0], lookup).fair)
    if op in ("u-", "u+", "@", "floor", "ceil"):
        v = evaluate(node.args[0], lookup)
        if op == "u-":
            return Iv(-v.hi, -v.lo, v.fair)
        if op == "u+":
            return v
        if op == "@":
            lo, hi = sorted((abs(v.lo), abs(v.hi)))
            return Iv(0 if v.lo <= 0 <= v.hi else lo, hi, v.fair)
        f = math.floor if op == "floor" else math.ceil
        return Iv(f(v.lo), f(v.hi), v.fair)
    if op in ("&", "|", "^"):
        a = evaluate(node.args[0], lookup)
        ta = a.truth()
        # short-circuit like SimC (&& / ||)
        if op == "&" and ta == "false":
            return F
        if op == "|" and ta == "true":
            return T
        b = evaluate(node.args[1], lookup)
        tb = b.truth()
        fair = (a.fair or ta != "unknown") and (b.fair or tb != "unknown")
        if op == "&":
            t = "false" if tb == "false" else "true" if ta == tb == "true" else "unknown"
        elif op == "|":
            t = "true" if tb == "true" else "false" if ta == tb == "false" else "unknown"
        else:
            t = "unknown" if "unknown" in (ta, tb) else ("true" if (ta == "true") != (tb == "true") else "false")
        return _bool(t, fair)
    if op in ("=", "!=", "<", "<=", ">", ">="):
        return _compare(op, evaluate(node.args[0], lookup), evaluate(node.args[1], lookup))
    if op in ("~", "!~"):
        return UNKNOWN
    return _arith(op, evaluate(node.args[0], lookup), evaluate(node.args[1], lookup))


# ---------------------------------------------------------------------------
# APL file model
# ---------------------------------------------------------------------------

EXPR_OPTIONS = {"if", "target_if", "value", "value_else", "condition", "interrupt_if", "early_chain_if",
                "chain", "cycle_targets", "max_cycle_targets", "line_cd", "wait_on_ready", "sec", "delay"}


@dataclass
class AplLine:
    list_name: str
    index: int            # 1-based position within the list
    file_line: int
    action: str
    options: dict[str, str]
    raw: str
    cond: Node | None = None
    target_if: tuple[str, Node] | None = None
    other_exprs: dict[str, Node] = field(default_factory=dict)


@dataclass
class AplProgram:
    lists: dict[str, list[AplLine]]
    comments: dict[str, str]


LINE_RE = re.compile(r"^actions(?:\.(?P<list>[A-Za-z0-9_]+))?(?P<op>\+?=)/?(?P<body>.*)$")


def parse_apl(text: str) -> AplProgram:
    lists: dict[str, list[AplLine]] = defaultdict(list)
    comments: dict[str, str] = {}
    pending_comment = None
    for no, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            pending_comment = line.lstrip("# ").strip()
            continue
        m = LINE_RE.match(line)
        if not m:
            raise ValueError(f"line {no}: not an action line: {raw!r}")
        name = m.group("list") or "default"
        if m.group("op") == "=" and lists.get(name):
            raise ValueError(f"line {no}: '=' resets list {name} which already has entries")
        if pending_comment and name not in comments:
            comments[name] = pending_comment
        pending_comment = None
        parts = m.group("body").split(",")
        action, opts = parts[0], {}
        for p in parts[1:]:
            k, _, v = p.partition("=")
            opts[k] = v
        ln = AplLine(name, len(lists[name]) + 1, no, action, opts, raw)
        if "if" in opts:
            ln.cond = parse_expr(opts["if"])
        if "target_if" in opts:
            mode, sep, expr = opts["target_if"].partition(":")
            if not sep:
                mode, expr = "first", opts["target_if"]
            ln.target_if = (mode, parse_expr(expr))
        for k in ("value", "value_else", "condition", "interrupt_if", "early_chain_if"):
            if k in opts:
                ln.other_exprs[k] = parse_expr(opts[k])
        lists[name].append(ln)
    return AplProgram(dict(lists), comments)


# ---------------------------------------------------------------------------
# 3-valued priority walk (docs/SCORING_SPEC.md §6.3)
# ---------------------------------------------------------------------------

@dataclass
class WalkResult:
    top: str | None                     # action chosen on a fully certain path (None if undecided)
    candidates: list[tuple[str, str, int, bool]]   # (action, list, index, fair_only) = the set C
    trace: list[str]


def walk(prog: AplProgram, list_name: str, lookup, usable, ignore: set[str], *, scoped_lookup=None,
         depth: int = 0, ctx_certain: bool = True, ctx_fair: bool = True,
         res: WalkResult | None = None) -> WalkResult:
    """Walk a list top-down with 3-valued conditions.

    - false line: skipped
    - unknown line: its action (or its sub-list's candidates) joins C, walk continues
    - true + usable line: joins C and ends this list; it is `top` only if every
      enclosing call_action_list condition was also certainly true
    usable(action) -> True / False / None (unknown).
    """
    res = res if res is not None else WalkResult(None, [], [])
    for ln in prog.lists.get(list_name, []):
        if ln.action in ignore:
            continue
        lk = scoped_lookup(ln.action) if scoped_lookup else lookup
        cond = evaluate(ln.cond, lk) if ln.cond else T
        truth = cond.truth()
        res.trace.append(f"{'  ' * depth}{list_name}#{ln.index} {ln.action}: if={truth}")
        if truth == "false":
            continue
        line_certain = ctx_certain and truth == "true"
        line_fair = ctx_fair and (truth == "true" or cond.fair)
        if ln.action in ("call_action_list", "run_action_list"):
            walk(prog, ln.options["name"], lookup, usable, ignore, scoped_lookup=scoped_lookup,
                 depth=depth + 1, ctx_certain=line_certain, ctx_fair=line_fair, res=res)
            if res.top is not None:
                return res
            continue
        u = usable(ln.action)
        if u is False:
            continue
        if truth == "true" and u is True:
            res.candidates.append((ln.action, list_name, ln.index, line_fair))
            if ctx_certain:
                res.top = ln.action
            return res
        res.candidates.append((ln.action, list_name, ln.index, line_fair and u is True))
    return res


# ---------------------------------------------------------------------------
# Term inventory and observability classification
# ---------------------------------------------------------------------------

# Initial classification, from docs/SCORING_SPEC.md §6.1 (to be confirmed by S2).
# O = observed in log, I = inferable from other events, U = uncertain interval, X = not available,
# N = not scored (MVP ignores the line), C = constant from config/talents.
SPELL_NOTES = {
    "tip_of_the_spear": "O: aura 260286 + dose events",
    "raptor_swipe": "O (expected): aura 1273155",
    "takedown": "O: aura 1250646 / cast",
    "howl_of_the_pack_leader_wyvern": "O? aura 471878 (S2)",
    "howl_of_the_pack_leader_boar": "O? aura 472324 (S2)",
    "howl_of_the_pack_leader_bear": "O? aura 472325 (S2)",
    "sentinels_mark": "O (expected): debuff 1253601 on target",
    "power_infusion": "O: external buff aura",
}


def classify(term: str) -> tuple[str, str]:
    parts = term.split(".")
    head = parts[0]
    if head in ("buff", "debuff"):
        name = parts[1] if len(parts) > 1 else "?"
        return ("O", SPELL_NOTES.get(name, "aura (verify ID in S2)"))
    if head == "cooldown":
        name, prop = (parts + ["", ""])[1:3]
        if name == "takedown":
            return ("I", "90 s - Savagery talent; deterministic from casts")
        return ("I", f"cooldown model for {name}.{prop}")
    if head in ("full_recharge_time", "charges", "charges_fractional", "recharge_time"):
        return ("I/U", "charge model of the line's own action (Wildfire Bomb CDR chain => U)")
    if head == "gcd":
        return ("I", "haste estimate")
    if head == "talent":
        return ("C", "COMBATANT_INFO or talent profile")
    if head == "howl_summon":
        return ("O/I", "any Howl ready buff up; fallback 30 s timer model")
    if head == "active_enemies":
        return ("I", "distinct enemies damaged in last 3 s")
    if head == "target":
        prop = parts[1] if len(parts) > 1 else ""
        if prop == "distance":
            return ("U", "positions known, hitbox unknown")
        if prop in ("time_to_die", "health"):
            return ("I", "HP trend from advanced block (no hindsight)")
        return ("U", "target property")
    if head == "fight_remains":
        return ("I", "HP-trend estimate (no hindsight)")
    if head in ("this_trinket", "other_trinket", "equipped", "fight_style"):
        return ("N", "trinket/sim-only; line not scored in MVP")
    return ("?", "unclassified")


SCORED_LISTS = ("plst", "sentst")           # MVP single-target lists
NOT_SCORED_ACTIONS = {"retarget", "auto_attack", "snapshot_stats", "summon_pet", "use_item", "use_items",
                      "potion", "invoke_external_buff", "blood_fury", "berserking", "fireblood",
                      "ancestral_call", "muzzle", "aspect_of_the_eagle"}


def inventory(prog: AplProgram) -> dict[str, dict]:
    inv: dict[str, dict] = {}
    for lname, lines in prog.lists.items():
        for ln in lines:
            exprs = [n for n in [ln.cond, ln.target_if[1] if ln.target_if else None, *ln.other_exprs.values()] if n]
            for e in exprs:
                for t in terms_of(e):
                    rec = inv.setdefault(t, {"lists": set(), "count": 0})
                    rec["lists"].add(lname)
                    rec["count"] += 1
    return inv


def option_keys(prog: AplProgram) -> dict[str, int]:
    keys: dict[str, int] = defaultdict(int)
    for lines in prog.lists.values():
        for ln in lines:
            for k in ln.options:
                keys[k] += 1
    return dict(keys)


# ---------------------------------------------------------------------------
# Demo states for the 3-valued walk
# ---------------------------------------------------------------------------

def demo_lookup(values: dict[str, Iv], action_scope: str | None = None):
    def lk(term: str) -> Iv:
        if term in values:
            return values[term]
        if action_scope and term in ("full_recharge_time",):
            return values.get(f"{action_scope}.{term}", UNKNOWN)
        return UNKNOWN
    return lk


def run_demos(prog: AplProgram) -> list[str]:
    out = []
    base_pl = {
        "talent.howl_of_the_pack_leader": Iv.pt(1), "talent.twin_fangs": Iv.pt(0),
        "talent.lethal_calibration": Iv.pt(1), "talent.takedown": Iv.pt(1),
        "active_enemies": Iv.pt(1), "fight_style.dungeonroute": Iv.pt(0), "gcd": Iv.pt(1.2),
        "buff.takedown.up": Iv.pt(0), "cooldown.takedown.ready": Iv.pt(0),
        "cooldown.takedown.remains": Iv.pt(30), "howl_summon.ready": Iv.pt(0),
        "buff.raptor_swipe.up": Iv.pt(0), "wildfire_bomb.full_recharge_time": Iv.pt(10),
    }
    all_usable = {"kill_command", "raptor_strike", "wildfire_bomb", "boomstick"}
    scenarios = [
        ("PL: Tip 0, Howl ready", {
            "buff.tip_of_the_spear.stack": Iv.pt(0), "buff.tip_of_the_spear.up": Iv.pt(0),
            "howl_summon.ready": Iv.pt(1)}, all_usable),
        ("PL: Tip 1, WFB full_recharge_time model-uncertain [3.2, 6.0] s", {
            "buff.tip_of_the_spear.stack": Iv.pt(1), "buff.tip_of_the_spear.up": Iv.pt(1),
            "wildfire_bomb.full_recharge_time": Iv(3.2, 6.0, False)}, all_usable),
        ("PL: Tip 0, KC/Boomstick unavailable, Raptor Swipe! proc inside reaction window", {
            "buff.tip_of_the_spear.stack": Iv.pt(0), "buff.tip_of_the_spear.up": Iv.pt(0),
            "buff.raptor_swipe.up": Iv(0, 1, True)}, {"raptor_strike", "wildfire_bomb"}),
    ]
    for title, vals, usable_set in scenarios:
        values = {**base_pl, **vals}
        usable = lambda a, u=usable_set: a in u
        res = walk(prog, "default", demo_lookup(values), usable, NOT_SCORED_ACTIONS,
                   scoped_lookup=lambda act, v=values: demo_lookup(v, act))
        determinate = res.top is not None and len(res.candidates) == 1
        cands = ", ".join(f"`{a}` ({l}#{i}, {'fair' if fair else 'model-uncertain'})" for a, l, i, fair in res.candidates)
        out.append(f"- **{title}** → first certain line = `{res.top}`, determinate = {determinate}; C = {{{cands}}}")
    return out


# ---------------------------------------------------------------------------
# Self test
# ---------------------------------------------------------------------------

def selftest() -> None:
    cases = {
        "a>0&!b|c=0&b": "(((a > 0) & !(b)) | ((c = 0) & b))",
        "a|b&c": "(a | (b & c))",
        "a-b-c": "((a - b) - c)",
        "a%b%%c": "((a % b) %% c)",
        "4+gcd": "(4 + gcd)",
        "x*0.45": "(x * 0.45)",
        "-1+a": "(-1 + a)",
        "a<?b>?c": "((a <? b) >? c)",
        "!a=b": "(!(a) = b)",
        "floor(a%2)": "floor((a % 2))",
        "buff.tip_of_the_spear.stack<2&(buff.x.remains|buff.y.remains)":
            "((buff.tip_of_the_spear.stack < 2) & (buff.x.remains | buff.y.remains))",
    }
    for src, want in cases.items():
        got = str(parse_expr(src))
        assert got == want, f"{src}: got {got}, want {want}"
    lk = lambda t: {"a": Iv(0, 5, False), "b": Iv.pt(3), "r": Iv(0, 1, True)}.get(t, UNKNOWN)
    assert evaluate(parse_expr("b>2"), lk).truth() == "true"
    assert evaluate(parse_expr("a>2"), lk).truth() == "unknown"
    assert evaluate(parse_expr("a>2"), lk).fair is False
    assert evaluate(parse_expr("r&b>2"), lk).fair is True
    assert evaluate(parse_expr("a>9|b>2"), lk).truth() == "true"
    assert evaluate(parse_expr("a>9&b>4"), lk).truth() == "false"
    print(f"selftest ok ({len(cases)} parse cases, 6 eval cases)")


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def report(path: Path, compare: Path | None) -> str:
    text = path.read_text(encoding="utf-8")
    prog = parse_apl(text)
    n_lines = sum(len(v) for v in prog.lists.values())
    n_exprs = sum(1 for v in prog.lists.values() for ln in v if ln.cond or ln.target_if or ln.other_exprs)
    inv = inventory(prog)
    md = [f"## `{path.name}`", "",
          f"- action lists: {len(prog.lists)} ({', '.join(prog.lists)})",
          f"- action lines: {n_lines}, lines with expressions: {n_exprs}, parse errors: 0",
          f"- option keys: " + ", ".join(f"`{k}`×{v}" for k, v in sorted(option_keys(prog).items())), "",
          "| term | lists | uses | class | note |", "|---|---|---|---|---|"]
    for t in sorted(inv):
        cls, note = classify(t)
        md.append(f"| `{t}` | {', '.join(sorted(inv[t]['lists']))} | {inv[t]['count']} | {cls} | {note} |")
    st_terms = sorted(t for t, r in inv.items() if r["lists"] & set(SCORED_LISTS))
    if st_terms:
        oi = [t for t in st_terms if classify(t)[0] in ("O", "I", "C", "O/I")]
        md += ["", f"MVP single-target lists ({', '.join(SCORED_LISTS)}): {len(st_terms)} terms, "
               f"{len(oi)} classified O/I/C directly ({100 * len(oi) // len(st_terms)}%), "
               f"others: " + ", ".join(f"`{t}`" for t in st_terms if t not in oi)]
    if "plst" in prog.lists:
        md += ["", "### 3-valued walk demo (fake states)", "", *run_demos(prog)]
    if compare:
        other = parse_apl(compare.read_text(encoding="utf-8"))
        oinv = inventory(other)
        new_heads = sorted({t.split(".")[0] for t in oinv} - {t.split(".")[0] for t in inv})
        new_opts = sorted(set(option_keys(other)) - set(option_keys(prog)))
        new_actions = sorted({ln.action for v in other.lists.values() for ln in v}
                             - {ln.action for v in prog.lists.values() for ln in v})
        md += ["", f"### Compared with `{compare.name}` (syntax needed for future specs/patches)", "",
               f"- action lists: {len(other.lists)}, action lines: {sum(len(v) for v in other.lists.values())}, parse errors: 0",
               f"- term families only there: " + ", ".join(f"`{h}`" for h in new_heads),
               f"- option keys only there: " + ", ".join(f"`{k}`" for k in new_opts),
               f"- actions only there: " + ", ".join(f"`{a}`" for a in new_actions)]
    return "\n".join(md)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("apl", nargs="?", type=Path)
    ap.add_argument("--compare", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest or not args.apl:
        selftest()
        if not args.apl:
            return 0
    md = report(args.apl, args.compare)
    if args.out:
        args.out.write_text(md + "\n", encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
