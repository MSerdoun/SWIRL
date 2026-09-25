"""SWIRL projects: the loaded spectra plus the settings of a session, in one ``.swirl`` file.

A project is a zip archive:

* ``project.json`` — format and version, name, dates, SWIRL version, and the session
  ``settings`` (recipe with enabled/disabled steps, quick continuum option, band and QC
  parameters, interface state). Settings are plain JSON so they stay readable.
* ``spectra.json`` — one entry per spectrum, in workspace order: name, quantity, metadata,
  processing history, and where its values are stored.
* ``spectra.npz`` — wavelength grids and values as float64 arrays (``allow_pickle`` is
  never used), so a saved project restores exactly.

Spectra are stored as they were loaded; the files they came from are never touched.
The same file opens in the GUI, in Python (:func:`load_project`) and through
:func:`swirl.read` (it returns the spectra).
"""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any

import numpy as np

from swirl._version import __version__
from swirl.core.spectrum import ProcessingStep, Quantity, Spectrum

if TYPE_CHECKING:
    from swirl.features import BandParams
    from swirl.preprocess import QCParams, Recipe

FORMAT = "swirl-project"
VERSION = 1
EXTENSION = ".swirl"


class ProjectError(ValueError):
    """The file is not a readable SWIRL project."""


def _json_default(obj: Any) -> Any:
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, Mapping):
        return dict(obj)
    if isinstance(obj, tuple):
        return list(obj)
    raise TypeError(f"{type(obj).__name__} is not JSON serialisable")


@dataclass
class Project:
    spectra: list[Spectrum]
    settings: dict[str, Any] = field(default_factory=dict)
    name: str = ""
    created: str = ""
    saved: str = ""
    swirl_version: str = ""

    def recipe(self) -> Recipe | None:
        """The processing the project's view shows: enabled recipe steps, then the quick
        continuum removal if it is on and the recipe does not already remove it."""
        from swirl.preprocess import Recipe

        raw = self.settings.get("recipe") or {}
        steps = [
            {"op": s["op"], **(s.get("params") or {})}
            for s in raw.get("steps", [])
            if s.get("enabled", True)
        ]
        cont = self.settings.get("continuum") or {}
        if cont.get("on") and not any(s["op"] == "continuum_removal" for s in steps):
            steps.append(
                {
                    "op": "continuum_removal",
                    "start": _bound(cont.get("start")),
                    "stop": _bound(cont.get("stop")),
                }
            )
        if not steps:
            return None
        return Recipe.from_dict({"name": raw.get("name", ""), "steps": steps})

    def band_params(self) -> BandParams:
        from swirl.features import BandParams

        return BandParams.model_validate(self.settings.get("band_params") or {})

    def qc_params(self) -> QCParams:
        from swirl.preprocess import QCParams

        return QCParams.model_validate(self.settings.get("qc_params") or {})


def _bound(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    return float(str(value).replace(",", "."))


def save_project(
    target: str | Path | IO[bytes],
    spectra: Sequence[Spectrum],
    settings: Mapping[str, Any] | None = None,
    *,
    name: str = "",
    created: str | None = None,
) -> None:
    """Write a project (spectra + settings) to a path or a binary file object."""
    now = datetime.now(UTC).isoformat(timespec="seconds")
    grids: list[np.ndarray] = []
    rows: list[list[np.ndarray]] = []
    entries = []
    for s in spectra:
        g = next((k for k, wl in enumerate(grids) if np.array_equal(wl, s.wavelength)), None)
        if g is None:
            grids.append(s.wavelength)
            rows.append([])
            g = len(grids) - 1
        entries.append(
            {
                "name": s.name,
                "quantity": s.quantity.value,
                "meta": dict(s.meta),
                "history": [h.to_dict() for h in s.history],
                "grid": g,
                "row": len(rows[g]),
            }
        )
        rows[g].append(s.values)

    arrays: dict[str, np.ndarray] = {}
    for g, wl in enumerate(grids):
        arrays[f"grid{g}_wavelength"] = np.asarray(wl, dtype=np.float64)
        arrays[f"grid{g}_values"] = np.vstack(rows[g]).astype(np.float64)
    npz = io.BytesIO()
    np.savez_compressed(npz, **arrays)  # type: ignore[arg-type]

    header = {
        "format": FORMAT,
        "version": VERSION,
        "name": name,
        "created": created or now,
        "saved": now,
        "swirl_version": __version__,
        "n_spectra": len(entries),
        "settings": dict(settings or {}),
    }
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("project.json", json.dumps(header, indent=2, default=_json_default))
        zf.writestr("spectra.json", json.dumps(entries, default=_json_default))
        zf.writestr("spectra.npz", npz.getvalue())


def load_project(source: str | Path | IO[bytes]) -> Project:
    """Read a project written by :func:`save_project`."""
    try:
        zf = zipfile.ZipFile(source)
    except (zipfile.BadZipFile, OSError) as exc:
        raise ProjectError(f"not a SWIRL project (not a zip archive): {exc}") from None
    with zf:
        names = set(zf.namelist())
        missing = {"project.json", "spectra.json", "spectra.npz"} - names
        if missing:
            raise ProjectError(f"not a SWIRL project: missing {sorted(missing)}")
        try:
            header = json.loads(zf.read("project.json"))
            entries = json.loads(zf.read("spectra.json"))
        except json.JSONDecodeError as exc:
            raise ProjectError(f"corrupted project metadata: {exc}") from None
        if header.get("format") != FORMAT:
            raise ProjectError(f"not a SWIRL project (format {header.get('format')!r})")
        if int(header.get("version", 0)) > VERSION:
            raise ProjectError(
                f"project format version {header.get('version')} is newer than this SWIRL "
                f"({VERSION}); update SWIRL to open it"
            )
        with np.load(io.BytesIO(zf.read("spectra.npz")), allow_pickle=False) as npz:
            arrays = {k: npz[k] for k in npz.files}

    spectra = []
    for i, e in enumerate(entries):
        try:
            g, r = int(e["grid"]), int(e["row"])
            spectra.append(
                Spectrum(
                    wavelength=arrays[f"grid{g}_wavelength"],
                    values=arrays[f"grid{g}_values"][r],
                    name=str(e["name"]),
                    quantity=Quantity(e["quantity"]),
                    meta=e.get("meta") or {},
                    history=tuple(ProcessingStep.from_dict(h) for h in e.get("history", [])),
                )
            )
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise ProjectError(f"spectrum {i} cannot be restored: {exc}") from None
    return Project(
        spectra=spectra,
        settings=dict(header.get("settings") or {}),
        name=str(header.get("name", "")),
        created=str(header.get("created", "")),
        saved=str(header.get("saved", "")),
        swirl_version=str(header.get("swirl_version", "")),
    )


def read_project_spectra(path: str | Path) -> list[Spectrum]:
    """Reader for :func:`swirl.read`: the spectra of a project."""
    return load_project(path).spectra
