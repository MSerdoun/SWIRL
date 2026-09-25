"""Delimited text spectra: generic exports (ASD ViewSpec, spreadsheets) and the SWIRL text format.

Reading accepts:

* tab, semicolon, comma or whitespace delimiters, detected from the first data row;
* decimal points or decimal commas (``0,4521`` with ``;``, tab or whitespace delimiters);
* an optional header row (the last non-comment line before the data) naming the columns;
* one wavelength column followed by one or more spectrum columns;
* ``#`` comment lines, which carry file and per-spectrum metadata in the SWIRL format.

Every unit conversion the reader makes (micrometres to nanometres, percent to fraction,
reversed order) is recorded in the spectrum history rather than applied silently.

The SWIRL text format written by :func:`write_text` is a comma-separated file::

    # swirl-format: 1
    # quantity: reflectance
    # [illite] meta: {"hole_id": "DH01", "depth_from": 12.5}
    # [illite] history: [{"name": "synthesize", "params": {...}, "swirl_version": "0.1.0"}]
    wavelength_nm,illite
    350.0000,0.412345
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

import numpy as np

from swirl._version import __version__
from swirl.core import meta as mk
from swirl.core.spectrum import FloatArray, ProcessingStep, Quantity, SpectralSet, Spectrum

FORMAT_VERSION = 1

_DATA_START = re.compile(r"^\s*[+]?(\d|\.\d)")
_SPECTRUM_HEADER = re.compile(r"^#\s*\[(?P<name>[^\]]+)\]\s*(?P<key>[\w-]+)\s*:\s*(?P<value>.*)$")
_FILE_HEADER = re.compile(r"^#\s*(?P<key>[\w-]+)\s*:\s*(?P<value>.*)$")
_NAN_TOKENS = frozenset({"", "nan", "na", "n/a", "null", "-"})
_FORBIDDEN_NAME_CHARS = frozenset(",\n\r]")

# Largest value accepted as reflectance in fraction units; above it the file is taken to be
# in percent. Real reflectance can exceed 1 slightly (poor white reference, specular glint).
_MAX_FRACTION = 1.5
# Largest value accepted as reflectance in percent.
_MAX_PERCENT = 150.0
# Wavelength axes whose maximum is below this are taken to be in micrometres.
_MAX_MICROMETRES = 20.0

Scale = float | Literal["auto"]
WavelengthUnit = Literal["auto", "nm", "um"]


class TextFormatError(ValueError):
    """The file could not be interpreted as delimited spectra."""


def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def _json_or_str(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value.strip()


def _detect_delimiter(line: str) -> str | None:
    if "\t" in line:
        return "\t"
    if ";" in line:
        return ";"
    stripped = line.strip()
    if "," in stripped:
        # "350 0,4521" is whitespace-delimited with a decimal comma; "350,0.4521" is CSV.
        if re.search(r"\s", stripped) and "." not in stripped:
            return None
        return ","
    return None


def _split(line: str, delimiter: str | None) -> list[str]:
    tokens = line.split() if delimiter is None else line.rstrip("\r\n").split(delimiter)
    return [t.strip() for t in tokens]


def _to_float(token: str, decimal: str, lineno: int) -> float:
    if token.lower() in _NAN_TOKENS:
        return float("nan")
    try:
        return float(token.replace(decimal, ".") if decimal != "." else token)
    except ValueError:
        raise TextFormatError(f"line {lineno}: cannot read {token!r} as a number") from None


def read_text(
    path: str | Path,
    *,
    delimiter: str | None = None,
    decimal: str | None = None,
    reflectance_scale: Scale = "auto",
    wavelength_unit: WavelengthUnit = "auto",
) -> list[Spectrum]:
    """Read every spectrum column of a delimited text file.

    Parameters
    ----------
    delimiter:
        Column separator. ``None`` detects it from the first data row.
    decimal:
        Decimal mark, ``"."`` or ``","``. ``None`` detects it.
    reflectance_scale:
        Factor applied to the values to obtain reflectance as a fraction. ``"auto"`` keeps
        values whose maximum is at most 1.5 and divides values up to 150 by 100 (percent);
        anything larger is rejected as not being reflectance.
    wavelength_unit:
        ``"nm"``, ``"um"`` or ``"auto"`` (micrometres when the largest wavelength is below 20).
    """
    path = Path(path)
    lines = _decode(path.read_bytes()).splitlines()

    file_meta: dict[str, Any] = {}
    spectrum_meta: dict[str, dict[str, Any]] = {}
    spectrum_history: dict[str, list[ProcessingStep]] = {}
    quantity = Quantity.REFLECTANCE
    header: str | None = None
    data: list[tuple[int, str]] = []

    for lineno, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            if m := _SPECTRUM_HEADER.match(line.strip()):
                name, key, value = m["name"].strip(), m["key"], m["value"]
                if key == "meta":
                    spectrum_meta[name] = dict(json.loads(value))
                elif key == "history":
                    spectrum_history[name] = [
                        ProcessingStep.from_dict(d) for d in json.loads(value)
                    ]
            elif m := _FILE_HEADER.match(line.strip()):
                key, value = m["key"], m["value"]
                if key == "quantity":
                    quantity = Quantity(value.strip())
                elif key not in ("swirl-format", "swirl-version"):
                    file_meta[key] = _json_or_str(value)
            continue
        if _DATA_START.match(line):
            data.append((lineno, line))
        elif data:
            raise TextFormatError(f"line {lineno}: unexpected text inside the data block")
        else:
            header = line

    if not data:
        raise TextFormatError(f"{path.name}: no numeric data rows found")

    sep = _detect_delimiter(data[0][1]) if delimiter is None else delimiter
    if decimal is None:
        sample = "".join(line for _, line in data[:20])
        decimal = "," if sep != "," and "," in sample and "." not in sample else "."

    rows = [_split(line, sep) for _, line in data]
    if all(len(r) > 1 and r[-1] == "" for r in rows):
        # A delimiter closing every row (common in spreadsheet exports) is not a column.
        rows = [r[:-1] for r in rows]
    n_cols = len(rows[0])
    if n_cols < 2:
        raise TextFormatError(
            f"{path.name}: expected a wavelength column and at least one spectrum"
        )
    table = np.empty((len(rows), n_cols), dtype=np.float64)
    for r, ((lineno, _), tokens) in enumerate(zip(data, rows, strict=True)):
        if len(tokens) != n_cols:
            raise TextFormatError(f"line {lineno}: expected {n_cols} columns, found {len(tokens)}")
        table[r] = [_to_float(t, decimal, lineno) for t in tokens]

    names = _column_names(header, sep, n_cols, path.stem)
    wavelength = table[:, 0]
    values = table[:, 1:]
    steps: list[ProcessingStep] = []

    if np.any(np.isnan(wavelength)):
        raise TextFormatError(f"{path.name}: the wavelength column contains missing values")
    if wavelength.size > 1 and np.all(np.diff(wavelength) < 0):
        wavelength, values = wavelength[::-1], values[::-1]
        steps.append(ProcessingStep("reverse_order", {"reason": "wavelength was decreasing"}))

    unit = wavelength_unit
    if unit == "auto":
        unit = "um" if np.max(wavelength) < _MAX_MICROMETRES else "nm"
    if unit == "um":
        wavelength = wavelength * 1000.0
        steps.append(ProcessingStep("convert_wavelength", {"from": "um", "to": "nm"}))

    scale = _resolve_scale(values, reflectance_scale, quantity, path.name)
    if scale != 1.0:
        values = values * scale
        steps.append(ProcessingStep("scale_values", {"factor": scale, "reason": "percent"}))

    read_step = ProcessingStep(
        "read_text",
        {
            "file": path.name,
            "delimiter": "whitespace" if sep is None else sep,
            "decimal": decimal,
        },
    )
    spectra = []
    for j, name in enumerate(names):
        meta = {
            **file_meta,
            mk.SOURCE_PATH: str(path),
            mk.SOURCE_COLUMN: name,
            **spectrum_meta.get(name, {}),
        }
        spectra.append(
            Spectrum(
                wavelength=wavelength,
                values=values[:, j],
                name=name,
                quantity=quantity,
                meta=meta,
                history=(*spectrum_history.get(name, []), read_step, *steps),
            )
        )
    return spectra


def _column_names(header: str | None, sep: str | None, n_cols: int, stem: str) -> list[str]:
    if header is not None:
        tokens = _split(header, sep)
        while len(tokens) > n_cols and tokens[-1] == "":
            tokens.pop()
        if len(tokens) == n_cols and all(tokens[1:]):
            names = tokens[1:]
            if len(set(names)) == len(names):
                return names
    if n_cols == 2:
        return [stem]
    return [f"{stem}_{i}" for i in range(1, n_cols)]


def _resolve_scale(
    values: FloatArray, requested: Scale, quantity: Quantity, filename: str
) -> float:
    if requested != "auto":
        return float(requested)
    if quantity is not Quantity.REFLECTANCE or not np.any(np.isfinite(values)):
        return 1.0
    peak = float(np.nanmax(values))
    if peak <= _MAX_FRACTION:
        return 1.0
    if peak <= _MAX_PERCENT:
        return 0.01
    raise TextFormatError(
        f"{filename}: values reach {peak:g}, which is neither reflectance as a fraction nor "
        "a percentage; pass reflectance_scale explicitly if this is intended"
    )


def _json_default(obj: Any) -> Any:
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, Mapping):
        return dict(obj)
    raise TypeError(f"{type(obj).__name__} is not JSON serialisable")


def write_text(
    spectra: Sequence[Spectrum] | SpectralSet,
    path: str | Path,
    *,
    value_format: str = "%.6f",
    wavelength_format: str = "%.4f",
) -> None:
    """Write spectra sharing one wavelength grid to a SWIRL text file (comma-separated)."""
    sset = spectra if isinstance(spectra, SpectralSet) else SpectralSet.from_spectra(spectra)
    for name in sset.names:
        if not name or _FORBIDDEN_NAME_CHARS & set(name):
            raise ValueError(
                f"spectrum name {name!r} cannot be written (empty or contains , ] or newline)"
            )
    if len(set(sset.names)) != len(sset.names):
        raise ValueError("spectrum names must be unique to be written to one file")

    out = [
        f"# swirl-format: {FORMAT_VERSION}",
        f"# swirl-version: {__version__}",
        f"# quantity: {sset.quantity.value}",
    ]
    for s in sset:
        meta = {k: v for k, v in s.meta.items() if k not in (mk.SOURCE_PATH, mk.SOURCE_COLUMN)}
        if meta:
            out.append(f"# [{s.name}] meta: {json.dumps(meta, default=_json_default)}")
        if s.history:
            hist = [step.to_dict() for step in s.history]
            out.append(f"# [{s.name}] history: {json.dumps(hist, default=_json_default)}")
    out.append(",".join(["wavelength_nm", *sset.names]))
    for i, wl in enumerate(sset.wavelength):
        row = [wavelength_format % wl]
        row.extend("nan" if np.isnan(v) else value_format % v for v in sset.values[:, i])
        out.append(",".join(row))
    Path(path).write_text("\n".join(out) + "\n", encoding="utf-8")
