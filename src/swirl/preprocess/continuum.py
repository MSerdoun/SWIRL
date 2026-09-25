"""Continuum removal by the upper convex hull (hull quotient)."""

from __future__ import annotations

from typing import Self

import numpy as np
from pydantic import Field, model_validator

from swirl.core.spectrum import FloatArray, ProcessingStep, Quantity, SpectralSet
from swirl.preprocess.registry import Params, ProcessingError, operation


def upper_hull(x: FloatArray, y: FloatArray) -> FloatArray:
    """Upper convex hull of the points (x, y), evaluated at every x.

    ``x`` must be strictly increasing; NaN values of ``y`` are ignored and give NaN.
    """
    finite = np.flatnonzero(np.isfinite(y))
    out = np.full(x.shape, np.nan)
    if finite.size < 2:
        return out
    hull: list[int] = []
    for i in finite:
        while len(hull) >= 2:
            o, a = hull[-2], hull[-1]
            cross = (x[a] - x[o]) * (y[i] - y[o]) - (y[a] - y[o]) * (x[i] - x[o])
            if cross >= 0:  # a lies on or below the chord o-i: not a hull vertex
                hull.pop()
            else:
                break
        hull.append(int(i))
    lo, hi = finite[0], finite[-1]
    out[lo : hi + 1] = np.interp(x[lo : hi + 1], x[hull], y[hull])
    out[~np.isfinite(y)] = np.nan
    return out


class ContinuumParams(Params):
    start: float | None = Field(
        None, description="First wavelength of the range (nm); default: start of the data."
    )
    stop: float | None = Field(
        None, description="Last wavelength of the range (nm); default: end of the data."
    )

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.start is not None and self.stop is not None and self.start >= self.stop:
            raise ValueError("start must be below stop")
        return self


@operation("continuum_removal", ContinuumParams)
def continuum_removal(sset: SpectralSet, p: ContinuumParams, step: ProcessingStep) -> SpectralSet:
    """Divide reflectance by its upper convex hull over [start, stop]; output is cropped to it."""
    if sset.quantity is not Quantity.REFLECTANCE:
        raise ProcessingError(f"continuum removal needs reflectance, got {sset.quantity.value}")
    wl = sset.wavelength
    lo = wl[0] if p.start is None else p.start
    hi = wl[-1] if p.stop is None else p.stop
    keep = (wl >= lo) & (wl <= hi)
    if keep.sum() < 3:
        raise ProcessingError(f"fewer than three bands between {lo:g} and {hi:g} nm")
    x = wl[keep]
    values = np.empty((len(sset), x.size))
    for i, v in enumerate(sset.values[:, keep]):
        hull = upper_hull(x, v)
        with np.errstate(divide="ignore", invalid="ignore"):
            values[i] = np.where(hull > 0, v / hull, np.nan)
    return sset.derive(step, values=values, wavelength=x, quantity=Quantity.CONTINUUM_REMOVED)
