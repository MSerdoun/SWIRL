"""Absorption-band parameters: position, depth, width, asymmetry, curvature, depth ratios.

For each band definition (name, nominal centre, search window [lo, hi]) the band is looked
for on a continuum-removed signal:

* ``continuum = "input"``: the input is already continuum-removed (e.g. a recipe ending in
  ``continuum_removal``); ``"local"``: the reflectance is divided by its upper hull over the
  search window only; ``"auto"``: ``input`` if the spectra are continuum-removed, else
  ``local``.
* The deepest sample in the window is taken. If it lies on the window edge there is no
  local minimum: with ``shoulder_detection`` the band is located at the maximum of the
  second derivative (a shoulder), otherwise it is reported absent.
* The position is refined by a parabola through ``fit_points`` samples (3 = vertex of the
  three points around the minimum; a vertex outside the fitted samples is rejected), by a
  Gaussian fit over the window, or left at the minimum sample.
* Depth is ``1 - CR`` at the minimum sample (``depth_at = "sample"``) or of the fitted
  model (``"fitted"``). Width is the full width at half depth, found by walking outwards
  from the minimum (over the whole input for ``input``, within the window for ``local``).
  Asymmetry is ``(right half-width - left half-width) / width`` (0 = symmetric, > 0 = the
  long-wavelength wing is wider).

The default band table and ratios are the project's working definitions (a starting
point, all editable).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Self

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator
from scipy.optimize import curve_fit
from scipy.signal import savgol_filter

from swirl.core.spectrum import FloatArray, ProcessingStep, Quantity, SpectralSet, Spectrum
from swirl.preprocess.continuum import upper_hull
from swirl.preprocess.registry import Params, ProcessingError

Status = Literal["minimum", "shoulder", "absent", "no_data"]


class BandDefinition(BaseModel):
    """One absorption band to measure."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, description="Short name, used in column names and ratios.")
    center: float = Field(description="Nominal centre (nm); the shift is reported from it.")
    lo: float = Field(description="Start of the search window (nm).")
    hi: float = Field(description="End of the search window (nm).")

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if not self.lo < self.hi:
            raise ValueError(f"band {self.name}: lo must be below hi")
        if not self.lo <= self.center <= self.hi:
            raise ValueError(f"band {self.name}: center must lie in [lo, hi]")
        return self


# Working definitions from the project's calibration notebook (name, centre, lo, hi).
DEFAULT_BANDS = [
    BandDefinition(name="OH1400", center=1410, lo=1360, hi=1460),
    BandDefinition(name="APS1480", center=1480, lo=1460, hi=1500),
    BandDefinition(name="F1770", center=1770, lo=1752, hi=1798),
    BandDefinition(name="kaol", center=2160, lo=2145, hi=2180),
    BandDefinition(name="APS2170", center=2172, lo=2162, hi=2188),
    BandDefinition(name="AlOH", center=2200, lo=2185, hi=2225),
    BandDefinition(name="FeOH", center=2250, lo=2232, hi=2278),
    BandDefinition(name="CO3", center=2320, lo=2305, hi=2338),
    BandDefinition(name="MgOH", center=2350, lo=2338, hi=2378),
]
DEFAULT_RATIOS = [
    ("kaol", "AlOH"),
    ("MgOH", "AlOH"),
    ("FeOH", "MgOH"),
    ("APS1480", "AlOH"),
    ("CO3", "MgOH"),
    ("F1770", "AlOH"),
]


class BandParams(Params):
    bands: list[BandDefinition] = Field(
        default=DEFAULT_BANDS, description="Bands to measure: name, centre, search window."
    )
    ratios: list[tuple[str, str]] = Field(
        default=DEFAULT_RATIOS, description="Depth ratios to report, as (numerator, denominator)."
    )
    continuum: Literal["auto", "input", "local"] = Field(
        "auto",
        description=(
            "input: spectra are already continuum-removed; local: hull over each search "
            "window; auto: input if continuum-removed, else local."
        ),
    )
    position_method: Literal["parabola", "gaussian", "minimum"] = Field(
        "parabola",
        description="Refine the position with a parabola, a Gaussian fit, or keep the minimum.",
    )
    fit_points: int = Field(
        3, ge=3, description="Samples in the parabola fit, centred on the minimum (odd)."
    )
    depth_at: Literal["sample", "fitted"] = Field(
        "sample", description="Depth at the minimum sample, or of the fitted model."
    )
    shoulder_detection: bool = Field(
        True,
        description="Without a local minimum, locate the band at the 2nd-derivative maximum.",
    )
    derivative_window: int = Field(
        11, ge=5, description="Savitzky-Golay window (bands, odd) of the 2nd derivative."
    )
    derivative_polyorder: int = Field(
        3, ge=2, description="Savitzky-Golay polynomial order of the 2nd derivative."
    )
    min_depth: float = Field(
        0.0, ge=0, lt=1, description="Report the band absent when shallower than this."
    )
    min_window_bands: int = Field(
        7, ge=3, description="Minimum number of finite samples in a search window."
    )
    ratio_scale: Literal["log", "linear"] = Field(
        "log", description="Report ratios as log(a/b) or a/b."
    )
    ratio_epsilon: float = Field(
        1e-4, ge=0, description="Added to both depths before the ratio (avoids 0/0)."
    )

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        names = [b.name for b in self.bands]
        if len(set(names)) != len(names):
            raise ValueError("band names must be unique")
        for a, b in self.ratios:
            if a not in names or b not in names:
                raise ValueError(f"ratio {a}/{b} refers to an unknown band")
        if self.fit_points % 2 == 0:
            raise ValueError("fit_points must be odd")
        if self.derivative_window % 2 == 0:
            raise ValueError("derivative_window must be odd")
        if self.derivative_polyorder >= self.derivative_window:
            raise ValueError("derivative_polyorder must be lower than derivative_window")
        return self


@dataclass(frozen=True)
class BandMeasure:
    position: float
    depth: float
    width: float
    asymmetry: float
    curvature: float
    status: Status
    continuum: str

    @property
    def found(self) -> bool:
        return self.status in ("minimum", "shoulder")


NO_DATA = BandMeasure(*(math.nan,) * 5, status="no_data", continuum="")


@dataclass(frozen=True)
class SpectrumBands:
    name: str
    bands: dict[str, BandMeasure]
    ratios: dict[str, float]
    meta: Mapping[str, Any] = field(default_factory=dict)
    history: tuple[ProcessingStep, ...] = ()


def _gauss(x: FloatArray, c: float, d: float, f: float) -> FloatArray:
    return np.asarray(1.0 - d * np.exp(-4.0 * math.log(2.0) * (x - c) ** 2 / f**2))


def _half_width_crossing(x: FloatArray, y: FloatArray, j: int, level: float, step: int) -> float:
    """From index j, go left (step -1) or right (+1) to where y first rises to ``level`` and
    interpolate the crossing. A gap (NaN) met first, or no crossing, gives NaN."""
    seg = y[j + 1 :] if step > 0 else y[:j][::-1]
    hits = np.flatnonzero(~(seg < level))  # reaches the level, or is NaN
    if hits.size == 0:
        return math.nan
    b = j + step * (int(hits[0]) + 1)
    a = b - step
    if not (np.isfinite(y[a]) and np.isfinite(y[b])):
        return math.nan
    t = (level - y[a]) / (y[b] - y[a]) if y[b] != y[a] else 0.0
    return float(x[a] + t * (x[b] - x[a]))


def _measure(
    x: FloatArray,
    cr: FloatArray,
    window: np.ndarray,
    band: BandDefinition,
    p: BandParams,
    continuum: str,
    d2: FloatArray | None = None,
) -> BandMeasure:
    """Measure one band on the continuum-removed signal ``cr`` defined on ``x``.

    ``d2`` may carry the precomputed 2nd derivative of ``cr[window]`` (batch path).
    """
    idx = np.flatnonzero(window & np.isfinite(cr))
    if idx.size < p.min_window_bands:
        return NO_DATA
    w, sub = x[idx], cr[idx]
    if d2 is None or d2.shape != sub.shape:
        d2 = _second_derivative(sub, p)
    j = int(np.argmin(sub))
    status: Status = "minimum"
    if not 0 < j < idx.size - 1:
        if not p.shoulder_detection or not np.any(np.isfinite(d2)):
            return BandMeasure(*(math.nan,) * 5, status="absent", continuum=continuum)
        status = "shoulder"
        j = min(max(int(np.nanargmax(d2)), 1), idx.size - 2)
    curvature = float(d2[j]) if np.isfinite(d2[j]) else math.nan

    position, fitted_depth = float(w[j]), 1.0 - float(sub[j])
    if p.position_method == "parabola":
        h = p.fit_points // 2
        lo, hi = max(j - h, 0), min(j + h + 1, idx.size)
        a2, a1, a0 = np.polyfit(w[lo:hi], sub[lo:hi], 2)
        if a2 > 0:
            vertex = -a1 / (2 * a2)
            # A vertex outside the fitted samples is an extrapolation: keep the sample.
            if w[lo] <= vertex <= w[hi - 1]:
                position = float(vertex)
                fitted_depth = 1.0 - float(a2 * vertex**2 + a1 * vertex + a0)
    elif p.position_method == "gaussian":
        span = float(w[-1] - w[0])
        try:
            (c, d, _fwhm), _ = curve_fit(
                _gauss,
                w,
                sub,
                p0=(float(w[j]), max(1.0 - float(sub[j]), 1e-3), span / 2),
                bounds=((w[0], 0.0, 1e-3), (w[-1], 1.0, 4 * span)),
                maxfev=2000,
            )
            position, fitted_depth = float(c), float(d)
        except (RuntimeError, ValueError):
            pass

    depth = fitted_depth if p.depth_at == "fitted" else 1.0 - float(sub[j])
    if depth < p.min_depth:
        return BandMeasure(*(math.nan,) * 5, status="absent", continuum=continuum)

    # Width: walk outwards from the minimum sample on the full signal (input) or window.
    full_j = int(idx[j])
    xs, ys = (x, cr) if continuum == "input" else (w, sub)
    jj = full_j if continuum == "input" else j
    level = 1.0 - depth / 2.0
    left = _half_width_crossing(xs, ys, jj, level, -1)
    right = _half_width_crossing(xs, ys, jj, level, +1)
    width = right - left if np.isfinite(left) and np.isfinite(right) else math.nan
    asym = ((right - position) - (position - left)) / width if width and width > 0 else math.nan
    return BandMeasure(position, depth, float(width), float(asym), curvature, status, continuum)


def _ratio(a: float, b: float, p: BandParams) -> float:
    if not (np.isfinite(a) and np.isfinite(b)):
        return math.nan
    num, den = a + p.ratio_epsilon, b + p.ratio_epsilon
    if den <= 0 or num <= 0:
        return math.nan
    return math.log(num / den) if p.ratio_scale == "log" else num / den


def _second_derivative(sub: FloatArray, p: BandParams) -> FloatArray:
    """Savitzky-Golay 2nd derivative along the last axis (rows of a matrix at once)."""
    n = sub.shape[-1]
    k = min(p.derivative_window, n - (1 - n % 2))
    if k <= p.derivative_polyorder:
        return np.full(sub.shape, math.nan)
    return np.asarray(savgol_filter(sub, k, p.derivative_polyorder, deriv=2, axis=-1))


def _mode(quantity: Quantity, p: BandParams) -> str:
    if p.continuum == "input" and quantity is not Quantity.CONTINUUM_REMOVED:
        raise ProcessingError(
            "continuum='input' needs continuum-removed spectra: add a continuum_removal step "
            "or use continuum='local'"
        )
    if p.continuum == "local" or (
        p.continuum == "auto" and quantity is not Quantity.CONTINUUM_REMOVED
    ):
        if quantity is Quantity.RAW:
            raise ProcessingError("band parameters need reflectance or continuum-removed input")
        return "local"
    return "input"


def _measure_set(
    wl: FloatArray, values: FloatArray, quantity: Quantity, p: BandParams
) -> list[tuple[dict[str, BandMeasure], dict[str, float]]]:
    """Measure all bands on a matrix of spectra sharing ``wl`` (one row per spectrum).

    The 2nd derivative of every row that is complete over a window is computed in one call;
    rows with gaps are handled one by one. Results are identical either way.
    """
    mode = _mode(quantity, p)
    n = values.shape[0]
    per: list[dict[str, BandMeasure]] = [{} for _ in range(n)]
    for band in p.bands:
        window = (wl >= band.lo) & (wl <= band.hi)
        if mode == "input":
            x, cr, mask = wl, values, window
        else:
            cols = np.flatnonzero(window)
            x = wl[cols]
            cr = np.full((n, cols.size), np.nan)
            for i in range(n):
                v = values[i, cols]
                if np.isfinite(v).sum() < p.min_window_bands:
                    continue
                hull = upper_hull(x, v)
                with np.errstate(divide="ignore", invalid="ignore"):
                    cr[i] = np.where(hull > 0, v / hull, np.nan)
            mask = np.ones(x.size, bool)
        block = cr[:, mask]
        complete = np.all(np.isfinite(block), axis=1)
        d2_rows: dict[int, FloatArray] = {}
        if complete.any() and block.shape[1] >= p.min_window_bands:
            d2 = _second_derivative(block[complete], p)
            d2_rows = dict(zip(np.flatnonzero(complete).tolist(), d2, strict=True))
        for i in range(n):
            per[i][band.name] = _measure(x, cr[i], mask, band, p, mode, d2_rows.get(i))

    key = "log" if p.ratio_scale == "log" else "ratio"
    return [
        (bands, {f"{key}({a}/{b})": _ratio(bands[a].depth, bands[b].depth, p) for a, b in p.ratios})
        for bands in per
    ]


def measure_spectrum(
    wavelength: FloatArray, values: FloatArray, quantity: Quantity, p: BandParams
) -> tuple[dict[str, BandMeasure], dict[str, float]]:
    """Measure all bands of one spectrum."""
    return _measure_set(wavelength, values[None, :], quantity, p)[0]


def extract_bands(
    data: Spectrum | SpectralSet | Sequence[Spectrum], params: BandParams | None = None
) -> list[SpectrumBands]:
    """Measure every band of ``params`` on every spectrum (input order kept)."""
    p = params or BandParams()
    spectra: list[Spectrum] = [data] if isinstance(data, Spectrum) else list(data)
    step = ProcessingStep("band_parameters", p.model_dump(mode="json"))
    out: list[SpectrumBands | None] = [None] * len(spectra)
    # Group spectra sharing a grid and quantity so each group is measured as one matrix.
    groups: dict[tuple[bytes, str], list[int]] = {}
    for i, s in enumerate(spectra):
        groups.setdefault((s.wavelength.tobytes(), s.quantity.value), []).append(i)
    for members in groups.values():
        first = spectra[members[0]]
        matrix = np.vstack([spectra[i].values for i in members])
        for i, (bands, ratios) in zip(
            members, _measure_set(first.wavelength, matrix, first.quantity, p), strict=True
        ):
            s = spectra[i]
            out[i] = SpectrumBands(s.name, bands, ratios, dict(s.meta), (*s.history, step))
    return [r for r in out if r is not None]


MEASURES = ("position", "shift", "depth", "width", "asymmetry", "curvature", "status")


def band_table(
    results: Sequence[SpectrumBands], params: BandParams
) -> tuple[list[str], list[list[Any]]]:
    """Flatten results to (columns, rows): one row per spectrum."""
    centers = {b.name: b.center for b in params.bands}
    columns = ["spectrum"]
    for b in params.bands:
        columns += [f"{b.name}_{m}" for m in MEASURES]
    ratio_names = list(results[0].ratios) if results else []
    columns += ratio_names
    rows = []
    for r in results:
        row: list[Any] = [r.name]
        for b in params.bands:
            m = r.bands[b.name]
            row += [
                m.position,
                m.position - centers[b.name],
                m.depth,
                m.width,
                m.asymmetry,
                m.curvature,
                m.status,
            ]
        row += [r.ratios[k] for k in ratio_names]
        rows.append(row)
    return columns, rows


def write_band_table(
    results: Sequence[SpectrumBands], params: BandParams, path: Any, *, digits: int = 6
) -> None:
    """Write the band table as CSV, with the parameters used in a header comment."""
    import json
    from pathlib import Path

    columns, rows = band_table(results, params)

    def fmt(v: Any) -> str:
        if isinstance(v, float):
            return "" if not math.isfinite(v) else f"{v:.{digits}g}"
        return str(v).replace(",", "_")

    lines = [
        "# swirl band parameters",
        f"# params: {json.dumps(params.model_dump(mode='json'))}",
        ",".join(columns),
        *(",".join(fmt(v) for v in row) for row in rows),
    ]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
