"""Splice (detector-step) correction.

A spectrometer with several detectors (ASD: VNIR ≤ 1000 nm < SWIR1 ≤ 1800 nm < SWIR2)
can show a step at each detector boundary. The spectrum is cut into segments at the
boundaries; one segment is the reference and the others are brought into line with it,
working outwards from the reference, one boundary at a time.

At each boundary the level of both sides is predicted at the midpoint between the last band
of the left segment and the first band of the right segment, by fitting a polynomial of
``fit_degree`` to the ``fit_bands`` finite bands nearest the boundary on each side. The
non-reference side is then scaled (multiplicative) or shifted (additive) to match.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from itertools import pairwise
from typing import Any, Literal, Self

import numpy as np
from pydantic import Field, model_validator

from swirl.core.spectrum import FloatArray, ProcessingStep, SpectralSet
from swirl.preprocess.registry import Params, ProcessingError, operation

METADATA_KEY = "splice_wavelengths"


class SpliceParams(Params):
    boundaries: list[float] | Literal["metadata"] = Field(
        default_factory=lambda: [1000.0, 1800.0],
        description=(
            "Detector boundaries (nm): the last wavelength of each detector but the last. "
            "'metadata' uses each spectrum's own 'splice_wavelengths' (ASD header)."
        ),
    )
    reference_segment: int = Field(
        1,
        ge=0,
        description="Index of the segment left unchanged (ASD: 0 = VNIR, 1 = SWIR1, 2 = SWIR2).",
    )
    method: Literal["multiplicative", "additive"] = Field(
        "multiplicative", description="Scale the other segments, or shift them."
    )
    fit_bands: int = Field(
        20, ge=1, description="Bands on each side of a boundary used to predict its level."
    )
    fit_degree: int = Field(
        1, ge=0, description="Degree of the polynomial fitted to those bands (0 = mean)."
    )

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.fit_degree >= self.fit_bands:
            raise ValueError("fit_degree must be lower than fit_bands")
        if isinstance(self.boundaries, list):
            if not self.boundaries:
                raise ValueError("at least one boundary is needed")
            if any(b >= c for b, c in pairwise(self.boundaries)):
                raise ValueError("boundaries must be strictly increasing")
            if self.reference_segment > len(self.boundaries):
                raise ValueError(
                    f"reference_segment {self.reference_segment} does not exist with "
                    f"{len(self.boundaries)} boundaries"
                )
        return self


def resolve_boundaries(
    boundaries: Sequence[float] | Literal["metadata"], meta: Mapping[str, Any], name: str
) -> list[float]:
    if boundaries != "metadata":
        return [float(b) for b in boundaries]
    found = meta.get(METADATA_KEY)
    if not found:
        raise ProcessingError(f"{name}: no {METADATA_KEY!r} in metadata")
    return [float(b) for b in found]


def _segments(wl: FloatArray, boundaries: Sequence[float]) -> list[np.ndarray]:
    edges = [-np.inf, *boundaries, np.inf]
    return [(wl > lo) & (wl <= hi) for lo, hi in pairwise(edges)]


def _level(
    wl: FloatArray, v: FloatArray, seg: np.ndarray, at_end: bool, n: int, deg: int, x0: float
) -> float:
    idx = np.flatnonzero(seg & np.isfinite(v))
    idx = idx[-n:] if at_end else idx[:n]
    if idx.size <= deg:
        raise ProcessingError(f"only {idx.size} finite bands next to the boundary at {x0:g} nm")
    coef = np.polyfit(wl[idx], v[idx], deg)
    return float(np.polyval(coef, x0))


def correct_splices(
    wl: FloatArray,
    v: FloatArray,
    boundaries: Sequence[float],
    *,
    reference_segment: int = 1,
    method: str = "multiplicative",
    fit_bands: int = 20,
    fit_degree: int = 1,
) -> tuple[FloatArray, list[float]]:
    """Correct one spectrum; return the corrected values and the correction of each segment.

    Corrections are factors (multiplicative) or offsets (additive); the reference segment
    and empty segments get the identity (1 or 0).
    """
    segs = _segments(wl, boundaries)
    if reference_segment >= len(segs):
        raise ProcessingError(f"reference_segment {reference_segment} does not exist")
    if not segs[reference_segment].any():
        raise ProcessingError("the reference segment holds no bands")
    identity = 1.0 if method == "multiplicative" else 0.0
    corrections = [identity] * len(segs)
    out = v.copy()

    def match(fixed: int, moving: int) -> None:
        left, right = sorted((fixed, moving))
        if not segs[moving].any():
            return
        x0 = 0.5 * (wl[segs[left]].max() + wl[segs[right]].min())
        lv = _level(wl, out, segs[left], True, fit_bands, fit_degree, x0)
        rv = _level(wl, out, segs[right], False, fit_bands, fit_degree, x0)
        target, current = (lv, rv) if fixed == left else (rv, lv)
        if method == "multiplicative":
            if current == 0:
                raise ProcessingError(f"zero level at the boundary near {x0:g} nm")
            corrections[moving] = target / current
            out[segs[moving]] *= corrections[moving]
        else:
            corrections[moving] = target - current
            out[segs[moving]] += corrections[moving]

    for j in range(reference_segment + 1, len(segs)):
        if segs[j - 1].any():
            match(j - 1, j)
    for j in range(reference_segment - 1, -1, -1):
        if segs[j + 1].any():
            match(j + 1, j)
    return out, corrections


@operation("splice_correction", SpliceParams)
def splice_correction(sset: SpectralSet, p: SpliceParams, step: ProcessingStep) -> SpectralSet:
    """Remove detector steps by matching each segment to its neighbour, from the reference out."""
    values = np.empty_like(sset.values)
    metas = []
    for i, (v, meta, name) in enumerate(zip(sset.values, sset.metas, sset.names, strict=True)):
        bounds = resolve_boundaries(p.boundaries, meta, name)
        try:
            values[i], corr = correct_splices(
                sset.wavelength,
                v,
                bounds,
                reference_segment=p.reference_segment,
                method=p.method,
                fit_bands=p.fit_bands,
                fit_degree=p.fit_degree,
            )
        except ProcessingError as exc:
            raise ProcessingError(f"{name}: {exc}") from None
        metas.append({**meta, "splice_corrections": corr})
    return sset.derive(step, values=values, metas=metas)
