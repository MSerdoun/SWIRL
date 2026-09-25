"""Quality control: measures on each spectrum, flagged against user thresholds.

QC never changes a spectrum. Every check can be switched off by setting its threshold to
``None``. The default thresholds are provisional and meant to be tuned per instrument.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Self

import numpy as np
from pydantic import Field, model_validator
from scipy.signal import savgol_filter

from swirl.core.spectrum import FloatArray, Quantity, SpectralSet
from swirl.preprocess.registry import Params, ProcessingError
from swirl.preprocess.splice import correct_splices, resolve_boundaries


class QCParams(Params):
    max_reflectance: float | None = Field(
        1.05, description="Flag 'above_max' if any reflectance exceeds this."
    )
    min_mean_reflectance: float | None = Field(
        0.05, description="Flag 'low_albedo' if the mean reflectance is below this."
    )
    max_nan_fraction: float | None = Field(
        0.05, ge=0, le=1, description="Flag 'missing_bands' if more bands than this are NaN."
    )
    noise_range: tuple[float, float] = Field(
        (2300.0, 2450.0), description="Wavelength range (nm) where noise is measured."
    )
    noise_window: int = Field(
        11, ge=5, description="Savitzky-Golay window (bands, odd) of the noise-free reference."
    )
    max_noise: float | None = Field(
        0.005,
        description="Flag 'noisy' if the RMS residual from a smoothed copy exceeds this.",
    )
    splice_boundaries: list[float] | Literal["metadata"] = Field(
        default_factory=lambda: [1000.0, 1800.0],
        description="Detector boundaries (nm) at which steps are measured.",
    )
    max_splice_step: float | None = Field(
        0.01,
        description="Flag 'splice_step' if a detector needs a relative correction above this.",
    )

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.noise_window % 2 == 0:
            raise ValueError("noise_window must be odd")
        if self.noise_range[0] >= self.noise_range[1]:
            raise ValueError("noise_range must be increasing")
        return self


@dataclass(frozen=True)
class QCResult:
    name: str
    metrics: dict[str, float]
    flags: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.flags


def _noise(wl: FloatArray, v: FloatArray, p: QCParams) -> float:
    sel = (wl >= p.noise_range[0]) & (wl <= p.noise_range[1]) & np.isfinite(v)
    if sel.sum() < p.noise_window:
        return float("nan")
    seg = v[sel]
    resid = seg - savgol_filter(seg, p.noise_window, 2)
    return float(np.sqrt(np.mean(resid**2)))


def run_qc(sset: SpectralSet, params: QCParams | None = None) -> list[QCResult]:
    p = params or QCParams()
    if sset.quantity is not Quantity.REFLECTANCE:
        raise ProcessingError(f"QC expects reflectance, got {sset.quantity.value}")
    wl = sset.wavelength
    results = []
    for v, meta, name in zip(sset.values, sset.metas, sset.names, strict=True):
        finite = v[np.isfinite(v)]
        m: dict[str, float] = {
            "max_reflectance": float(finite.max()) if finite.size else float("nan"),
            "mean_reflectance": float(finite.mean()) if finite.size else float("nan"),
            "nan_fraction": 1.0 - finite.size / v.size,
            "noise_rms": _noise(wl, v, p),
        }
        try:
            bounds = resolve_boundaries(p.splice_boundaries, meta, name)
            _, factors = correct_splices(wl, v, bounds, reference_segment=1)
            m["max_splice_step"] = float(max(abs(f - 1.0) for f in factors))
        except ProcessingError:
            m["max_splice_step"] = float("nan")

        flags = []
        if p.max_reflectance is not None and m["max_reflectance"] > p.max_reflectance:
            flags.append("above_max")
        if p.min_mean_reflectance is not None and m["mean_reflectance"] < p.min_mean_reflectance:
            flags.append("low_albedo")
        if p.max_nan_fraction is not None and m["nan_fraction"] > p.max_nan_fraction:
            flags.append("missing_bands")
        if p.max_noise is not None and m["noise_rms"] > p.max_noise:
            flags.append("noisy")
        if p.max_splice_step is not None and m["max_splice_step"] > p.max_splice_step:
            flags.append("splice_step")
        results.append(QCResult(name=name, metrics=m, flags=tuple(flags)))
    return results
