"""Continuum removal by the upper convex hull (hull quotient)."""

from __future__ import annotations

from typing import Self

import numpy as np
from pydantic import Field, model_validator
from scipy.spatial import ConvexHull, QhullError

from swirl.core.spectrum import FloatArray, ProcessingStep, Quantity, SpectralSet
from swirl.preprocess.registry import Params, ProcessingError, operation


def _upper_chain_python(x: FloatArray, y: FloatArray) -> list[int]:
    """Monotone-chain upper hull (reference implementation, O(n) with a Python loop)."""
    hull: list[int] = []
    for i in range(x.size):
        while len(hull) >= 2:
            o, a = hull[-2], hull[-1]
            cross = (x[a] - x[o]) * (y[i] - y[o]) - (y[a] - y[o]) * (x[i] - x[o])
            if cross >= 0:  # a lies on or below the chord o-i: not a hull vertex
                hull.pop()
            else:
                break
        hull.append(i)
    return hull


def _upper_chain(x: FloatArray, y: FloatArray) -> np.ndarray:
    """Indices (increasing) of the upper-hull vertices of strictly increasing x."""
    n = x.size
    if n <= 2:
        return np.arange(n)
    span_y = float(y.max() - y.min())
    if span_y == 0:
        return np.array([0, n - 1])
    # Normalise both axes: qhull is sensitive to very different scales (nm vs reflectance).
    pts = np.column_stack([(x - x[0]) / (x[-1] - x[0]), (y - y.min()) / span_y])
    try:
        v = ConvexHull(pts).vertices  # counter-clockwise
    except QhullError:  # e.g. all points collinear
        return np.array(_upper_chain_python(x, y))
    # Counter-clockwise from the rightmost point runs over the top to the leftmost one.
    order = np.roll(v, -int(np.flatnonzero(v == n - 1)[0]))
    stop = int(np.flatnonzero(order == 0)[0])
    return np.sort(order[: stop + 1])


def upper_hull(x: FloatArray, y: FloatArray) -> FloatArray:
    """Upper convex hull of the points (x, y), evaluated at every x.

    ``x`` must be strictly increasing; NaN values of ``y`` are ignored and give NaN.
    """
    finite = np.flatnonzero(np.isfinite(y))
    out = np.full(x.shape, np.nan)
    if finite.size < 2:
        return out
    xf, yf = x[finite], y[finite]
    hull = _upper_chain(xf, yf)
    lo, hi = finite[0], finite[-1]
    out[lo : hi + 1] = np.interp(x[lo : hi + 1], xf[hull], yf[hull])
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
