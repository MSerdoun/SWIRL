"""ASD binary spectra (``.asd``: FieldSpec, TerraSpec, LabSpec, HandHeld — file versions 1-8).

Layout (little-endian): a 484-byte header, the spectrum (``channels`` values), then for file
version >= 2 a reference header (VARIANT_BOOL flag, two OLE dates, a length-prefixed
description) followed by the white-reference spectrum. Later sections (classifier,
calibration, audit log, signature) are not needed and not read.

The stored spectrum is normally raw digital numbers (DN); reflectance is the ratio of the
target DN to the white-reference DN. What the reader returns is chosen with ``output`` and
every derivation is recorded in the spectrum history.

Header offsets were cross-checked against the ASD File Format v8 layout as implemented by
two independent MIT-licensed readers (SpecDAL, pyASDReader). **Validation against real
instrument files and their ViewSpec / RS3 text exports is still pending.**
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import numpy as np

from swirl.core import meta as mk
from swirl.core.spectrum import FloatArray, ProcessingStep, Quantity, Spectrum

HEADER_SIZE = 484

_VERSIONS = {b"ASD": 1, **{f"as{i}".encode(): i for i in range(2, 9)}}
_DATA_TYPES = {
    0: "raw",
    1: "reflectance",
    2: "radiance",
    3: "no_units",
    4: "irradiance",
    5: "quality_index",
    6: "transmittance",
    7: "unknown",
    8: "absolute_reflectance",
}
_INSTRUMENTS = {
    0: "unknown",
    1: "PSII",
    2: "LSVNIR",
    3: "FSVNIR",
    4: "FSFR",
    5: "FSNIR",
    6: "CHEM",
    7: "LabSpec Pro",
    10: "HandHeld",
}
# data_format code -> (struct code, bytes per value)
_DATA_FORMATS = {0: ("f", 4), 1: ("i", 4), 2: ("d", 8)}
_VARIANT_TRUE, _VARIANT_FALSE = b"\xff\xff", b"\x00\x00"
_OLE_EPOCH = datetime(1899, 12, 30)
# A stored spectrum whose maximum is at most this is already reflectance, not DN.
_MAX_STORED_REFLECTANCE = 1.5
# Upper bound on the reference description length, to reject implausible layouts.
_MAX_DESCRIPTION = 4096

Output = Literal["reflectance", "raw", "reference"]


class ASDFormatError(ValueError):
    """The file is not a readable ASD spectrum."""


@dataclass(frozen=True)
class ASDHeader:
    version: int
    comments: str
    acquired_at: datetime | None
    data_type: str
    first_wavelength: float
    wavelength_step: float
    data_format: int
    channels: int
    integration_time_ms: int
    instrument_number: int
    dark_corrected: bool
    sample_count: int
    instrument: str
    swir1_gain: int
    swir2_gain: int
    splice1_wavelength: float
    splice2_wavelength: float


def _u(fmt: str, raw: bytes, offset: int) -> Any:
    return struct.unpack_from("<" + fmt, raw, offset)[0]


def _tm_to_datetime(raw: bytes) -> datetime | None:
    sec, minute, hour, mday, mon, year = struct.unpack_from("<6h", raw, 160)
    try:
        return datetime(year + 1900 if year < 1900 else year, mon + 1, mday, hour, minute, sec)
    except ValueError:
        return None


def _ole_to_iso(value: float) -> str | None:
    if not np.isfinite(value) or value <= 0:
        return None
    try:
        return (_OLE_EPOCH + timedelta(days=value)).isoformat(timespec="seconds")
    except OverflowError:
        return None


def parse_header(raw: bytes) -> ASDHeader:
    if len(raw) < HEADER_SIZE:
        raise ASDFormatError(
            f"file is {len(raw)} bytes, shorter than the {HEADER_SIZE}-byte header"
        )
    version = _VERSIONS.get(raw[:3])
    if version is None:
        raise ASDFormatError(f"unknown file signature {raw[:3]!r}; not an ASD file")
    return ASDHeader(
        version=version,
        comments=raw[3:160].split(b"\x00", 1)[0].decode("cp1252", errors="replace").strip(),
        acquired_at=_tm_to_datetime(raw),
        data_type=_DATA_TYPES.get(_u("B", raw, 186), "unknown"),
        first_wavelength=float(_u("f", raw, 191)),
        wavelength_step=float(_u("f", raw, 195)),
        data_format=int(_u("B", raw, 199)),
        channels=int(_u("H", raw, 204)),
        integration_time_ms=int(_u("I", raw, 390)),
        instrument_number=int(_u("H", raw, 400)),
        dark_corrected=bool(_u("B", raw, 181)),
        sample_count=int(_u("H", raw, 429)),
        instrument=_INSTRUMENTS.get(_u("B", raw, 431), "unknown"),
        swir1_gain=int(_u("H", raw, 436)),
        swir2_gain=int(_u("H", raw, 438)),
        splice1_wavelength=float(_u("f", raw, 444)),
        splice2_wavelength=float(_u("f", raw, 448)),
    )


def _element_layout(raw: bytes, header: ASDHeader) -> tuple[str, int]:
    """Decide how spectrum values are stored, from the file structure rather than the values.

    Both reference implementations read doubles whatever ``data_format`` says, so doubles are
    tried first; the declared format is the fallback. A layout is accepted only if what
    follows the spectrum is consistent with it (end of file for v1, a VARIANT_BOOL reference
    flag for v2+).
    """
    declared = _DATA_FORMATS.get(header.data_format)
    candidates = [("d", 8)] + ([declared] if declared and declared != ("d", 8) else [])
    for code, size in candidates:
        end = HEADER_SIZE + header.channels * size
        if header.version == 1:
            if len(raw) == end:
                return code, size
        elif _reference_block_fits(raw, end, header.channels * size):
            return code, size
    raise ASDFormatError(
        f"cannot locate the spectrum block for {header.channels} channels "
        f"(data_format={header.data_format}, file size {len(raw)} bytes)"
    )


def _reference_block_fits(raw: bytes, start: int, block_bytes: int) -> bool:
    """True if a reference header + block of ``block_bytes`` can start at ``start``."""
    if len(raw) < start + 20 or raw[start : start + 2] not in (_VARIANT_TRUE, _VARIANT_FALSE):
        return False
    desc_len = int(_u("h", raw, start + 18))
    return 0 <= desc_len <= _MAX_DESCRIPTION and start + 20 + desc_len + block_bytes <= len(raw)


def _read_block(raw: bytes, offset: int, n: int, code: str, size: int) -> FloatArray:
    if offset + n * size > len(raw):
        raise ASDFormatError("file is truncated inside a spectrum block")
    return np.asarray(struct.unpack_from(f"<{n}{code}", raw, offset), dtype=np.float64)


def read_asd(path: str | Path, *, output: Output = "reflectance") -> list[Spectrum]:
    """Read one ASD file.

    Parameters
    ----------
    output:
        ``"reflectance"`` (default): the stored spectrum if it is already reflectance,
        otherwise target DN / white-reference DN. ``"raw"``: the stored target values
        (quantity ``raw``). ``"reference"``: the white-reference DN (quantity ``raw``),
        e.g. to check the reference itself.
    """
    path = Path(path)
    raw = path.read_bytes()
    header = parse_header(raw)
    if header.channels < 2:
        raise ASDFormatError(f"header declares {header.channels} channels")
    code, size = _element_layout(raw, header)
    n = header.channels
    target = _read_block(raw, HEADER_SIZE, n, code, size)

    reference: FloatArray | None = None
    ref_meta: dict[str, Any] = {}
    if header.version >= 2:
        start = HEADER_SIZE + n * size
        flag = raw[start : start + 2] == _VARIANT_TRUE
        ref_time = float(_u("d", raw, start + 2))
        desc_len = int(_u("h", raw, start + 18))
        desc_start = start + 20
        description = raw[desc_start : desc_start + desc_len]
        ref_meta = {
            "asd_reference_flag": flag,
            "asd_reference_time": _ole_to_iso(ref_time),
            "asd_reference_description": description.decode("cp1252", errors="replace"),
        }
        reference = _read_block(raw, desc_start + desc_len, n, code, size)

    wavelength = np.asarray(
        header.first_wavelength + header.wavelength_step * np.arange(n), dtype=np.float64
    )
    read_step = ProcessingStep(
        "read_asd",
        {
            "file": path.name,
            "version": header.version,
            "data_type": header.data_type,
            "value_bytes": size,
            "output": output,
        },
    )
    steps: list[ProcessingStep] = []
    if output == "raw":
        values, quantity = target, Quantity.RAW
    elif output == "reference":
        if reference is None:
            raise ASDFormatError(f"{path.name}: version-{header.version} files hold no reference")
        values, quantity = reference, Quantity.RAW
    elif output == "reflectance":
        quantity = Quantity.REFLECTANCE
        finite = target[np.isfinite(target)]
        if finite.size and float(np.max(finite)) <= _MAX_STORED_REFLECTANCE:
            values = target
            steps.append(ProcessingStep("asd_stored_reflectance", {}))
        else:
            if reference is None:
                raise ASDFormatError(
                    f"{path.name}: stored values are not reflectance and the file holds no "
                    "white reference; read it with output='raw'"
                )
            with np.errstate(divide="ignore", invalid="ignore"):
                values = np.where(reference != 0, target / reference, np.nan)
            steps.append(
                ProcessingStep(
                    "asd_reflectance_ratio",
                    {"formula": "target_dn / reference_dn", "zero_reference": "nan"},
                )
            )
    else:
        raise ValueError(f"output must be 'reflectance', 'raw' or 'reference', got {output!r}")

    meta: dict[str, Any] = {
        mk.SOURCE_PATH: str(path),
        mk.INSTRUMENT: f"ASD {header.instrument} #{header.instrument_number}",
        "asd_version": header.version,
        "asd_data_type": header.data_type,
        "integration_time_ms": header.integration_time_ms,
        "swir1_gain": header.swir1_gain,
        "swir2_gain": header.swir2_gain,
        "splice_wavelengths": [header.splice1_wavelength, header.splice2_wavelength],
        "dark_corrected": header.dark_corrected,
        "sample_count": header.sample_count,
        **ref_meta,
    }
    if header.comments:
        meta["comment"] = header.comments
    if header.acquired_at is not None:
        meta[mk.ACQUIRED_AT] = header.acquired_at.isoformat(timespec="seconds")

    return [
        Spectrum(
            wavelength=wavelength,
            values=values,
            name=path.stem,
            quantity=quantity,
            meta=meta,
            history=(read_step, *steps),
        )
    ]
