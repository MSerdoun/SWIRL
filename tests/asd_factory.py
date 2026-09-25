"""Build ASD binary files for tests.

The header is packed field by field with the full ASD v8 header layout (one struct format
for all 484 bytes), independently of the fixed offsets used by the reader, so the two
cross-check each other.
"""

import struct
from pathlib import Path

import numpy as np

HEADER_FORMAT = (
    "<3s 157s 18s B B b b l b l f f b b b b b H 128s 56s L h h H H f f f f h b 4b H H H b L "
    "H H H H f f 27s 5b"
)
assert struct.calcsize(HEADER_FORMAT) == 484


def ole_date(year, month, day, hour=0, minute=0):
    from datetime import datetime

    delta = datetime(year, month, day, hour, minute) - datetime(1899, 12, 30)
    return delta.total_seconds() / 86400.0


def make_asd(
    path: Path,
    target,
    reference=None,
    *,
    version: bytes = b"as7",
    data_type: int = 1,
    data_format: int = 2,
    value_code: str = "d",
    first_wavelength: float = 350.0,
    step: float = 1.0,
    comments: bytes = b"core DH01 12.5m",
    when=(30, 15, 10, 25, 8, 126),  # 10:15:30, 25 Sep 2026 (month 0-based, years since 1900)
    integration_time: int = 17,
    instrument_number: int = 18123,
    instrument: int = 4,
    swir_gains=(128, 256),
    splice=(1000.0, 1800.0),
    reference_description: bytes = b"Spectralon",
    reference_time: float | None = None,
    trailer: bytes = b"",
) -> Path:
    target = np.asarray(target, dtype=float)
    when_bytes = struct.pack("<9h", *when, 0, 0, 0)
    header = struct.pack(
        HEADER_FORMAT,
        version,
        comments,
        when_bytes,
        1,  # program version
        1,  # file version
        0,  # itime
        1,  # dark corrected
        0,  # dark time
        data_type,
        0,  # reference time (time_t)
        first_wavelength,
        step,
        data_format,
        0,
        0,
        0,
        0,  # old counts, application
        target.size,
        b"",  # app data
        b"",  # gps
        integration_time,
        0,
        0,
        0,  # fore optic, dcc, calibration
        instrument_number,
        0.0,
        1.0,
        350.0,
        2500.0,  # ymin ymax xmin xmax
        16,
        0,  # ip bits, xmode
        0,
        0,
        0,
        0,  # flags
        25,
        10,
        10,  # dc / ref / sample counts
        instrument,
        0,  # bulb
        swir_gains[0],
        swir_gains[1],
        2048,
        2048,
        splice[0],
        splice[1],
        b"",
        0,
        0,
        0,
        0,
        0,
    )
    body = struct.pack(f"<{target.size}{value_code}", *target)
    if version != b"ASD":
        flag = b"\xff\xff" if reference is not None else b"\x00\x00"
        ref = np.zeros_like(target) if reference is None else np.asarray(reference, dtype=float)
        rt = ole_date(2026, 9, 25, 10, 10) if reference_time is None else reference_time
        body += flag + struct.pack("<2d", rt, rt) + struct.pack("<h", len(reference_description))
        body += reference_description + struct.pack(f"<{ref.size}{value_code}", *ref)
    path.write_bytes(header + body + trailer)
    return path
