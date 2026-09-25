"""Down-hole organisation of spectra: group samples by hole, order them by depth, and build
the arrays of a strip log (spectral image, band parameters, QC, synthetic truth).

A spectrum belongs to a hole through its metadata: ``hole_id`` and ``depth_from`` (and
optionally ``depth_to``; a bare ``depth`` is accepted as ``depth_from``).
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from swirl.core import meta as mk
from swirl.core.spectrum import FloatArray, Quantity, SpectralSet, Spectrum
from swirl.features import BandParams, extract_bands
from swirl.preprocess import QCParams, QCResult, Recipe, run_qc


@dataclass(frozen=True)
class Sample:
    spectrum: Spectrum
    hole_id: str
    depth_from: float
    depth_to: float

    @property
    def depth(self) -> float:
        """Mid-depth of the sample (m)."""
        return 0.5 * (self.depth_from + self.depth_to)


def _depths(spectrum: Spectrum) -> tuple[float, float] | None:
    m = spectrum.meta
    top = m.get(mk.DEPTH_FROM, m.get("depth"))
    if top is None:
        return None
    try:
        top = float(top)
    except (TypeError, ValueError):
        return None
    bottom = m.get(mk.DEPTH_TO)
    try:
        bottom = float(bottom) if bottom is not None else top
    except (TypeError, ValueError):
        bottom = top
    return top, max(bottom, top)


def as_sample(spectrum: Spectrum) -> Sample | None:
    hole = spectrum.meta.get(mk.HOLE_ID)
    depths = _depths(spectrum)
    if hole in (None, "") or depths is None:
        return None
    return Sample(spectrum, str(hole), *depths)


def holes(spectra: Iterable[Spectrum]) -> dict[str, list[Sample]]:
    """Samples per hole, each list sorted by depth (spectra without hole or depth ignored)."""
    out: dict[str, list[Sample]] = {}
    for s in spectra:
        sample = as_sample(s)
        if sample is not None:
            out.setdefault(sample.hole_id, []).append(sample)
    for samples in out.values():
        samples.sort(key=lambda x: (x.depth_from, x.depth_to))
    return out


@dataclass
class HoleLog:
    """Everything a strip log needs, as arrays aligned on the samples (top to bottom)."""

    hole_id: str
    names: list[str]
    depth_from: FloatArray
    depth_to: FloatArray
    quantity: Quantity
    image_wavelength: FloatArray
    image: FloatArray
    mean_reflectance: FloatArray
    bands: dict[str, dict[str, list[Any]]]
    ratios: dict[str, FloatArray]
    qc: list[QCResult] | None
    truth_composition: dict[str, FloatArray] | None = None
    truth_aloh_center: FloatArray | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def depth(self) -> FloatArray:
        return np.asarray(0.5 * (self.depth_from + self.depth_to))


def _bin_columns(
    wl: FloatArray, values: FloatArray, max_bands: int
) -> tuple[FloatArray, FloatArray]:
    """Average adjacent bands so the image has at most ``max_bands`` columns."""
    k = max(1, math.ceil(wl.size / max_bands))
    if k == 1:
        return wl, values
    m = (wl.size // k) * k
    wl_b = wl[:m].reshape(-1, k).mean(1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        v_b = np.nanmean(values[:, :m].reshape(values.shape[0], -1, k), axis=2)
    return np.asarray(wl_b), np.asarray(v_b)


def build_log(
    samples: Sequence[Sample],
    *,
    recipe: Recipe | None = None,
    band_params: BandParams | None = None,
    qc_params: QCParams | None = None,
    image_max_bands: int = 400,
) -> HoleLog:
    """Run the recipe on the hole's spectra and assemble the log arrays."""
    if not samples:
        raise ValueError("no samples")
    hole_id = samples[0].hole_id
    spectra = [s.spectrum for s in samples]
    inputs = SpectralSet.from_spectra(spectra)
    processed = recipe.run(inputs) if recipe is not None and recipe.steps else inputs
    bp = band_params or BandParams()
    results = extract_bands(processed, bp)

    bands: dict[str, dict[str, list[Any]]] = {}
    for b in bp.bands:
        ms = [r.bands[b.name] for r in results]
        bands[b.name] = {
            "position": [m.position for m in ms],
            "depth": [m.depth for m in ms],
            "width": [m.width for m in ms],
            "asymmetry": [m.asymmetry for m in ms],
            "status": [m.status for m in ms],
        }
    ratio_names = list(results[0].ratios) if results else []
    ratios = {k: np.array([r.ratios[k] for r in results]) for k in ratio_names}

    notes = []
    qc: list[QCResult] | None = None
    if inputs.quantity is Quantity.REFLECTANCE:
        qc = run_qc(inputs, qc_params)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            mean_r = np.nanmean(inputs.values, axis=1)
    else:
        notes.append(f"QC and mean reflectance need reflectance input ({inputs.quantity.value})")
        mean_r = np.full(len(samples), np.nan)

    img_wl, img = _bin_columns(processed.wavelength, processed.values, image_max_bands)

    truth_comp: dict[str, FloatArray] | None = None
    truth_aloh: FloatArray | None = None
    comps = [s.spectrum.meta.get("synthetic_composition") for s in samples]
    if all(isinstance(c, dict) for c in comps):
        keys = sorted({k for c in comps for k in c})  # type: ignore[union-attr]
        truth_comp = {k: np.array([c.get(k, 0.0) for c in comps]) for k in keys}  # type: ignore[union-attr]
        aloh = [s.spectrum.meta.get("synthetic_aloh_center") for s in samples]
        if all(a is not None for a in aloh):
            truth_aloh = np.array(aloh, dtype=float)

    return HoleLog(
        hole_id=hole_id,
        names=[s.spectrum.name for s in samples],
        depth_from=np.array([s.depth_from for s in samples]),
        depth_to=np.array([s.depth_to for s in samples]),
        quantity=processed.quantity,
        image_wavelength=img_wl,
        image=img,
        mean_reflectance=np.asarray(mean_r, dtype=float),
        bands=bands,
        ratios=ratios,
        qc=qc,
        truth_composition=truth_comp,
        truth_aloh_center=truth_aloh,
        notes=notes,
    )
