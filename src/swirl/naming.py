"""Read the hole and the depth from sample names, by example — no regular expressions needed.

The user marks, in one example name, which part is the hole and which part is the depth::

    SYN_02_354   ->   hole = "SYN_02", depth = "354"

The example is cut into tokens (letters, digits, separators). Candidate rules are built by
generalising each part of the name at several levels — the exact text, its *shape*
("letters_digits"), a looser shape (any separator), or anything — and every candidate that
reproduces the example exactly is scored on all the names: the rule that reads the most
names wins, the most specific one on a tie. The rule therefore captures the structure, not
the values: it reads ``SYN_01_357`` as hole ``SYN_01``, depth 357.

When one rule cannot explain several examples (names with different structures), one rule
per example is kept, the most specific first. A rule is described in plain words for the
user; the regular expression stays internal.

Depths are integers or decimals (``354``, ``354.5``, ``354,5``).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import product
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

TOKEN_RE = re.compile(r"[A-Za-z]+|\d+|[^A-Za-z\d]+")
NUMBER = r"\d+(?:[.,]\d+)?"
_NUMBER_RE = re.compile(rf"^{NUMBER}$")


@dataclass(frozen=True)
class Token:
    text: str
    kind: str  # "alpha", "digit" or "sep"
    start: int
    end: int


def tokenize(name: str) -> list[Token]:
    out = []
    for m in TOKEN_RE.finditer(name):
        t = m.group()
        kind = "alpha" if t[0].isalpha() else "digit" if t[0].isdigit() else "sep"
        out.append(Token(t, kind, m.start(), m.end()))
    return out


def parse_depth(text: str) -> float:
    return float(text.replace(",", "."))


class NamingExample(BaseModel):
    """One name with the character spans [start, end) of the hole and of the depth."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    hole: tuple[int, int]
    depth: tuple[int, int]

    @model_validator(mode="after")
    def _valid(self) -> Self:
        n = len(self.name)
        for what, (a, b) in (("hole", self.hole), ("depth", self.depth)):
            if not 0 <= a < b <= n:
                raise ValueError(f"{what} span {a}-{b} is outside the name")
        (a1, b1), (a2, b2) = self.hole, self.depth
        if a1 < b2 and a2 < b1:
            raise ValueError("the hole and the depth overlap")
        if not _NUMBER_RE.match(self.depth_text):
            raise ValueError(f"the depth {self.depth_text!r} is not a number")
        return self

    @property
    def hole_text(self) -> str:
        return self.name[self.hole[0] : self.hole[1]]

    @property
    def depth_text(self) -> str:
        return self.name[self.depth[0] : self.depth[1]]


# --- generalisation of the parts of a name ------------------------------------------------


@dataclass(frozen=True)
class _Option:
    regex: str
    score: int  # specificity: higher = more specific
    words: str  # plain-language description


def _shape(text: str, loose: bool) -> tuple[str, str]:
    regex, words = [], []
    for t in tokenize(text):
        if t.kind == "alpha":
            regex.append("[A-Za-z]+")
            words.append("letters")
        elif t.kind == "digit":
            regex.append(r"\d+")
            words.append("digits")
        elif loose:
            regex.append(r"[^A-Za-z\d]+")
            words.append("·")
        else:
            regex.append(re.escape(t.text))
            words.append(t.text)
    return "".join(regex), "".join(words) if not loose else " ".join(words)


def _field_options(text: str) -> list[_Option]:
    """Ways to generalise the hole."""
    shape, shape_w = _shape(text, loose=False)
    loose, loose_w = _shape(text, loose=True)
    opts = [_Option(shape, 3, f"shaped like {shape_w}")]
    if loose != shape:
        opts.append(_Option(loose, 2, f"shaped like {loose_w} (any separator)"))
    opts += [_Option(".+", 0, "any text"), _Option(".+?", 0, "any text (shortest)")]
    return opts


def _gap_options(text: str) -> list[_Option]:
    """Ways to generalise the text between the hole and the depth."""
    if not text:
        return [_Option("", 5, "")]
    opts = [_Option(re.escape(text), 4, f"then {text!r}")]
    if all(t.kind == "sep" for t in tokenize(text)):
        opts.append(_Option(r"[^A-Za-z\d]+", 2, "then a separator"))
    else:
        shape, words = _shape(text, loose=False)
        opts.append(_Option(shape, 3, f"then {words}"))
    return opts


def _edge_options(text: str, at_end: bool) -> list[_Option]:
    """Ways to generalise what comes before the first part or after the last one."""
    where = "then" if at_end else "starting with"
    if not text:
        opts = [_Option("", 5, "")]
        # Allow extra text after a separator (e.g. replicate suffixes "_rep", "_2").
        extra = r"(?:[^A-Za-z\d].*)?" if at_end else r"(?:.*[^A-Za-z\d])?"
        opts.append(
            _Option(
                extra,
                0,
                "optionally anything after a separator"
                if at_end
                else "optionally anything before a separator",
            )
        )
        return opts
    shape, words = _shape(text, loose=False)
    loose, loose_w = _shape(text, loose=True)
    opts = [
        _Option(re.escape(text), 4, f"{where} {text!r}"),
        _Option(shape, 3, f"{where} {words}"),
        _Option(f"(?:{shape})?", 1, f"{where} optional {words}"),
    ]
    if loose != shape:
        opts.append(_Option(loose, 2, f"{where} {loose_w}"))
    opts.append(_Option(".*" if at_end else ".*?", 0, f"{where} anything"))
    return opts


@dataclass(frozen=True)
class NamingRule:
    pattern: str
    description: str
    specificity: int

    def parse(self, name: str) -> tuple[str, float] | None:
        m = re.fullmatch(self.pattern, name)
        if m is None:
            return None
        hole, depth = m.group("hole"), m.group("depth")
        if not hole:
            return None
        return hole, parse_depth(depth)

    def to_dict(self) -> dict[str, object]:
        return {"pattern": self.pattern, "description": self.description}


def _candidates(ex: NamingExample) -> list[NamingRule]:
    s = ex.name
    hole_first = ex.hole[0] < ex.depth[0]
    first, second = (ex.hole, ex.depth) if hole_first else (ex.depth, ex.hole)
    pre, gap, post = s[: first[0]], s[first[1] : second[0]], s[second[1] :]
    depth = _Option(NUMBER, 3, "a number")
    out = []
    for p, h, g, q in product(
        _edge_options(pre, at_end=False),
        _field_options(ex.hole_text),
        _gap_options(gap),
        _edge_options(post, at_end=True),
    ):
        hole_re = f"(?P<hole>{h.regex})"
        depth_re = f"(?P<depth>{depth.regex})"
        parts = (
            [p.regex, hole_re, g.regex, depth_re, q.regex]
            if hole_first
            else [p.regex, depth_re, g.regex, hole_re, q.regex]
        )
        words = [p.words, f"hole = {h.words}", g.words, "depth = a number", q.words]
        if not hole_first:
            words = [p.words, "depth = a number", g.words, f"hole = {h.words}", q.words]
        out.append(
            NamingRule(
                pattern="".join(parts),
                description=", ".join(w for w in words if w),
                specificity=p.score + h.score + g.score + q.score,
            )
        )
    return out


def _reads(rule: NamingRule, ex: NamingExample) -> bool:
    got = rule.parse(ex.name)
    return got is not None and got[0] == ex.hole_text and got[1] == parse_depth(ex.depth_text)


@dataclass(frozen=True)
class Inference:
    rules: tuple[NamingRule, ...]
    single: bool
    """True when one rule explains every example."""


def infer_rules(examples: Sequence[NamingExample], names: Sequence[str]) -> Inference:
    """Rules that read every example exactly and as many ``names`` as possible."""
    if not examples:
        raise ValueError("at least one example is needed")
    pool: dict[str, NamingRule] = {}
    for ex in examples:
        for r in _candidates(ex):
            pool.setdefault(r.pattern, r)
    compiled = {p: re.compile(p) for p in pool}

    def coverage(rule: NamingRule) -> int:
        rx = compiled[rule.pattern]
        return sum(1 for n in names if rx.fullmatch(n) and rule.parse(n) is not None)

    def best(rules: list[NamingRule]) -> NamingRule:
        return max(rules, key=lambda r: (coverage(r), r.specificity))

    joint = [r for r in pool.values() if all(_reads(r, ex) for ex in examples)]
    if joint:
        return Inference((best(joint),), single=True)
    chosen: list[NamingRule] = []
    for ex in examples:
        rule = best([r for r in pool.values() if _reads(r, ex)])
        if rule not in chosen:
            chosen.append(rule)
    chosen.sort(key=lambda r: -r.specificity)
    return Inference(tuple(chosen), single=False)


def apply_rules(
    rules: Sequence[NamingRule], names: Sequence[str]
) -> list[tuple[str, float] | None]:
    """(hole, depth) read from each name by the first rule that matches, else None."""
    out: list[tuple[str, float] | None] = []
    for n in names:
        got = None
        for r in rules:
            got = r.parse(n)
            if got is not None:
                break
        out.append(got)
    return out
