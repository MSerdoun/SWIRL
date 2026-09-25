"""Sample tables (CSV / TSV exported from a spreadsheet): hole and depths per sample id,
joined to spectra by name.

The delimiter and a decimal comma are detected; column roles are guessed from common
header names (``SampleID``, ``HoleID``/``BHID``, ``From``/``Depth``, ``To``...) and can be
changed by the user.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SampleTableError(ValueError):
    """The table cannot be read or used."""


@dataclass
class SampleTable:
    columns: list[str]
    rows: list[list[str]]
    filename: str = ""


def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def _delimiter(lines: Sequence[str]) -> str:
    """The first delimiter present the same number of times on every line; comma last, as
    it may be a decimal mark (``3,5``) when another delimiter is used."""
    for d in ("\t", ";", "|", ","):
        counts = {ln.count(d) for ln in lines}
        if len(counts) == 1 and counts.pop() > 0:
            return d
    for d in ("\t", ";", "|", ","):
        if d in lines[0]:
            return d
    raise SampleTableError("no column delimiter found (tab, ';', '|' or ',')")


def read_sample_table(data: bytes | str, filename: str = "") -> SampleTable:
    text = _decode(data) if isinstance(data, bytes) else data
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        raise SampleTableError("the table needs a header row and at least one data row")
    delimiter = _delimiter(lines[:50])
    reader = csv.reader(io.StringIO("\n".join(lines)), delimiter=delimiter)
    rows = [[c.strip() for c in r] for r in reader]
    header, body = rows[0], rows[1:]
    if len(set(header)) != len(header) or not all(header):
        raise SampleTableError("column names must be unique and not empty")
    width = len(header)
    body = [(r + [""] * width)[:width] for r in body]
    return SampleTable(columns=header, rows=body, filename=filename)


_ROLE_NAMES = {
    "key": [
        "sampleid",
        "sample",
        "samplename",
        "sampleno",
        "id",
        "name",
        "spectrum",
        "file",
        "filename",
    ],
    "hole": ["holeid", "hole", "bhid", "dhid", "drillhole", "holename", "borehole", "hole_id"],
    "depth_from": ["from", "depthfrom", "fromm", "mfrom", "depth", "top", "depthm"],
    "depth_to": ["to", "depthto", "tom", "mto", "bottom"],
}


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def guess_mapping(columns: Sequence[str]) -> dict[str, str | None]:
    """Guess which column plays which role from its header (None when nothing fits)."""
    normed = {c: _norm(c) for c in columns}
    out: dict[str, str | None] = {}
    used: set[str] = set()
    for role, candidates in _ROLE_NAMES.items():
        found = None
        for cand in candidates:
            found = next((c for c, n in normed.items() if n == _norm(cand) and c not in used), None)
            if found:
                break
        out[role] = found
        if found:
            used.add(found)
    return out


class TableMapping(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(description="Column holding the sample name, matched to the spectra.")
    hole: str = Field(description="Column holding the hole identifier.")
    depth_from: str = Field(description="Column holding the depth (or interval top), in metres.")
    depth_to: str | None = Field(None, description="Column holding the interval bottom.")
    match_on: Literal["name", "file"] = Field(
        "name", description="Match the key to the spectrum name or to its file name."
    )
    ignore_case: bool = Field(True, description="Ignore upper/lower case when matching.")
    ignore_extension: bool = Field(True, description="Ignore a file extension in the key.")


@dataclass(frozen=True)
class Assignment:
    hole_id: str
    depth_from: float
    depth_to: float


@dataclass
class MatchReport:
    assignments: list[Assignment | None]
    unmatched_spectra: list[int] = field(default_factory=list)
    unused_rows: list[str] = field(default_factory=list)
    duplicate_keys: list[str] = field(default_factory=list)
    bad_rows: list[str] = field(default_factory=list)


def _number(text: str) -> float | None:
    t = text.strip().replace(",", ".")
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def match_key(text: str, mapping: TableMapping) -> str:
    k = text.strip()
    if mapping.ignore_extension:
        suffix = PurePath(k).suffix
        if suffix and re.fullmatch(r"\.[A-Za-z][A-Za-z0-9]{0,4}", suffix):
            k = k[: -len(suffix)]
    return k.lower() if mapping.ignore_case else k


def match_table(table: SampleTable, mapping: TableMapping, keys: Sequence[str]) -> MatchReport:
    """Assign a hole and depths to each spectrum key found in the table."""
    for col in (mapping.key, mapping.hole, mapping.depth_from, mapping.depth_to):
        if col is not None and col not in table.columns:
            raise SampleTableError(f"column {col!r} is not in the table")
    ci = {c: i for i, c in enumerate(table.columns)}
    by_key: dict[str, Assignment] = {}
    report = MatchReport(assignments=[])
    for row in table.rows:
        raw_key = row[ci[mapping.key]]
        if not raw_key:
            continue
        k = match_key(raw_key, mapping)
        hole = row[ci[mapping.hole]].strip()
        top = _number(row[ci[mapping.depth_from]])
        bottom = _number(row[ci[mapping.depth_to]]) if mapping.depth_to else None
        if not hole or top is None:
            report.bad_rows.append(raw_key)
            continue
        if k in by_key:
            report.duplicate_keys.append(raw_key)
            continue
        by_key[k] = Assignment(hole, top, bottom if bottom is not None and bottom >= top else top)
    used: set[str] = set()
    for i, key in enumerate(keys):
        k = match_key(key, mapping)
        a = by_key.get(k)
        report.assignments.append(a)
        if a is None:
            report.unmatched_spectra.append(i)
        else:
            used.add(k)
    report.unused_rows = [k for k in by_key if k not in used]
    return report
