"""Operations on the wavelength axis: crop, mask, resample."""

from __future__ import annotations

from typing import Literal, Self

import numpy as np
from pydantic import Field, model_validator
from scipy.interpolate import PchipInterpolator

from swirl.core.spectrum import FloatArray, ProcessingStep, SpectralSet
from swirl.preprocess.registry import Params, ProcessingError, operation


class CropParams(Params):
    start: float = Field(description="First wavelength kept (nm, inclusive).")
    stop: float = Field(description="Last wavelength kept (nm, inclusive).")

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.start >= self.stop:
            raise ValueError("start must be below stop")
        return self


@operation("crop", CropParams)
def crop(sset: SpectralSet, p: CropParams, step: ProcessingStep) -> SpectralSet:
    """Keep only the bands between start and stop."""
    keep = (sset.wavelength >= p.start) & (sset.wavelength <= p.stop)
    if keep.sum() < 2:
        raise ProcessingError(f"fewer than two bands between {p.start:g} and {p.stop:g} nm")
    return sset.derive(step, values=sset.values[:, keep], wavelength=sset.wavelength[keep])


class MaskParams(Params):
    ranges: list[tuple[float, float]] = Field(
        description="Wavelength ranges (nm, inclusive) set to NaN, e.g. [[1350, 1450]]."
    )

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        for lo, hi in self.ranges:
            if lo >= hi:
                raise ValueError(f"range [{lo}, {hi}] is empty")
        return self


@operation("mask", MaskParams)
def mask(sset: SpectralSet, p: MaskParams, step: ProcessingStep) -> SpectralSet:
    """Set the bands inside the given ranges to NaN (e.g. atmospheric water bands)."""
    values = sset.values.copy()
    for lo, hi in p.ranges:
        values[:, (sset.wavelength >= lo) & (sset.wavelength <= hi)] = np.nan
    return sset.derive(step, values=values)


class ResampleParams(Params):
    start: float = Field(description="First wavelength of the new grid (nm).")
    stop: float = Field(description="Last wavelength of the new grid (nm, included if on-step).")
    step: float = Field(gt=0, description="Grid spacing (nm).")
    method: Literal["linear", "pchip"] = Field(
        "linear", description="Interpolation: linear, or monotone cubic (PCHIP)."
    )

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.start >= self.stop:
            raise ValueError("start must be below stop")
        return self


def regular_grid(start: float, stop: float, step: float) -> FloatArray:
    n = int(np.floor((stop - start) / step + 1e-9)) + 1
    return np.asarray(start + step * np.arange(n), dtype=np.float64)


def _resample_one(wl: FloatArray, v: FloatArray, grid: FloatArray, method: str) -> FloatArray:
    finite = np.isfinite(v)
    if finite.sum() < 2:
        return np.full(grid.shape, np.nan)
    x, y = wl[finite], v[finite]
    if method == "linear":
        out = np.interp(grid, x, y, left=np.nan, right=np.nan)
    else:
        out = PchipInterpolator(x, y, extrapolate=False)(grid)
    # A target band that falls in (or touches) a gap of the source is not interpolated across.
    in_gap = np.interp(grid, wl, (~finite).astype(np.float64)) > 0
    out[in_gap] = np.nan
    return np.asarray(out, dtype=np.float64)


@operation("resample", ResampleParams)
def resample(sset: SpectralSet, p: ResampleParams, step: ProcessingStep) -> SpectralSet:
    """Interpolate onto a regular grid; bands outside the data or inside NaN gaps become NaN."""
    grid = regular_grid(p.start, p.stop, p.step)
    if grid.size < 2:
        raise ProcessingError("the target grid has fewer than two bands")
    values = np.vstack([_resample_one(sset.wavelength, v, grid, p.method) for v in sset.values])
    return sset.derive(step, values=values, wavelength=grid)
