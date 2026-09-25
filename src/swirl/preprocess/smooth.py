"""Smoothing."""

from __future__ import annotations

from typing import Literal, Self

import numpy as np
from pydantic import Field, model_validator
from scipy.ndimage import uniform_filter1d
from scipy.signal import savgol_filter

from swirl.core.spectrum import FloatArray, ProcessingStep, SpectralSet
from swirl.preprocess.registry import Params, ProcessingError, operation


class SmoothParams(Params):
    method: Literal["savgol", "moving_average"] = Field(
        "savgol", description="Savitzky-Golay, or a centred moving average."
    )
    window: int = Field(11, ge=3, description="Window length in bands (odd).")
    polyorder: int = Field(2, ge=0, description="Savitzky-Golay polynomial order.")

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.window % 2 == 0:
            raise ValueError("window must be odd")
        if self.method == "savgol" and self.polyorder >= self.window:
            raise ValueError("polyorder must be lower than window")
        return self


def _finite_runs(v: FloatArray) -> list[tuple[int, int]]:
    finite = np.concatenate([[False], np.isfinite(v), [False]])
    edges = np.flatnonzero(np.diff(finite.astype(np.int8)))
    return list(zip(edges[::2], edges[1::2], strict=True))


def smooth_values(v: FloatArray, p: SmoothParams) -> FloatArray:
    """Smooth each run of finite values independently; runs shorter than the window are kept."""
    out = v.copy()
    for a, b in _finite_runs(v):
        if b - a < p.window:
            continue
        if p.method == "savgol":
            out[a:b] = savgol_filter(v[a:b], p.window, p.polyorder, mode="interp")
        else:
            out[a:b] = uniform_filter1d(v[a:b], p.window, mode="nearest")
    return out


@operation("smooth", SmoothParams)
def smooth(sset: SpectralSet, p: SmoothParams, step: ProcessingStep) -> SpectralSet:
    """Smooth each spectrum along wavelength (NaN gaps are not smoothed across)."""
    spacing = np.diff(sset.wavelength)
    if not np.allclose(spacing, spacing[0], rtol=1e-6):
        raise ProcessingError("smoothing needs a regular wavelength grid; resample first")
    values = np.vstack([smooth_values(v, p) for v in sset.values])
    return sset.derive(step, values=values)
