"""File formats. Each format registers a reader and/or a writer; :func:`read` and :func:`write`
dispatch on the file extension unless a format name is given.

Adding a format (``.asd``, ``.sco``, ``.sed`` ...) means writing one module and one
:func:`register_format` call; nothing else in SWIRL needs to change.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from swirl.core.spectrum import SpectralSet, Spectrum
from swirl.io.asd import ASDFormatError, read_asd
from swirl.io.text import TextFormatError, read_text, write_text

Reader = Callable[..., list[Spectrum]]
Writer = Callable[..., None]


@dataclass(frozen=True)
class Format:
    name: str
    extensions: tuple[str, ...]
    reader: Reader | None = None
    writer: Writer | None = None
    description: str = ""


_FORMATS: dict[str, Format] = {}


def register_format(fmt: Format) -> None:
    for ext in fmt.extensions:
        if not ext.startswith("."):
            raise ValueError(f"extension {ext!r} must start with a dot")
    _FORMATS[fmt.name] = fmt


def formats() -> list[Format]:
    return list(_FORMATS.values())


def _resolve(path: Path, format: str | None) -> Format:
    if format is not None:
        try:
            return _FORMATS[format]
        except KeyError:
            raise ValueError(f"unknown format {format!r}; known: {sorted(_FORMATS)}") from None
    ext = path.suffix.lower()
    for fmt in _FORMATS.values():
        if ext in fmt.extensions:
            return fmt
    raise ValueError(
        f"no format registered for extension {ext!r}; pass format= explicitly "
        f"(known: {sorted(_FORMATS)})"
    )


def read(path: str | Path, *, format: str | None = None, **kwargs: Any) -> list[Spectrum]:
    """Read all spectra in ``path``."""
    path = Path(path)
    fmt = _resolve(path, format)
    if fmt.reader is None:
        raise ValueError(f"format {fmt.name!r} cannot be read")
    return fmt.reader(path, **kwargs)


def write(
    spectra: Sequence[Spectrum] | SpectralSet,
    path: str | Path,
    *,
    format: str | None = None,
    **kwargs: Any,
) -> None:
    """Write ``spectra`` to ``path``."""
    path = Path(path)
    fmt = _resolve(path, format)
    if fmt.writer is None:
        raise ValueError(f"format {fmt.name!r} cannot be written")
    fmt.writer(spectra, path, **kwargs)


register_format(
    Format(
        name="text",
        extensions=(".txt", ".csv", ".tsv", ".dat", ".sco"),
        reader=read_text,
        writer=write_text,
        description="Delimited text: one wavelength column, one column per spectrum",
    )
)
register_format(
    Format(
        name="asd",
        extensions=(".asd",),
        reader=read_asd,
        description="ASD binary (FieldSpec, TerraSpec, LabSpec, HandHeld), file versions 1-8",
    )
)


def _read_project(path: Path, **kwargs: Any) -> list[Spectrum]:
    from swirl.project import read_project_spectra

    return read_project_spectra(path)


register_format(
    Format(
        name="project",
        extensions=(".swirl",),
        reader=_read_project,
        description="SWIRL project (spectra and session settings); read returns the spectra",
    )
)

__all__ = [
    "ASDFormatError",
    "Format",
    "TextFormatError",
    "formats",
    "read",
    "read_asd",
    "read_text",
    "register_format",
    "write",
    "write_text",
]
