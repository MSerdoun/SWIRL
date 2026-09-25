# Pre-processing — methods, defaults, measured behaviour

Every parameter below is user-settable (Python keyword, recipe file, or later the GUI).
Defaults are **provisional** starting points, not recommendations validated on real data.
`swirl ops` prints the live list of operations, parameters, defaults and descriptions.

## splice_correction

Segments are cut at `boundaries` (ASD default 1000 / 1800 nm, or each file's header values
with `boundaries = "metadata"`). The `reference_segment` is left unchanged; working outwards,
each neighbour is scaled (`multiplicative`) or shifted (`additive`) so both sides agree at
the boundary. The level of each side at the boundary midpoint is predicted by a polynomial
of degree `fit_degree` fitted to the `fit_bands` nearest finite bands. The applied
corrections are stored per spectrum in `meta["splice_corrections"]`.

Measured on the synthetic set (offsets from `truth.json`), maximum error on the correction
factor:

| fit | noise-free (curvature bias) | with synthetic noise |
|---|---|---|
| 10 bands, linear | ≤ 1.4e-5 | ≤ 0.71 % |
| **20 bands, linear (default)** | ≤ 6.7e-5 | ≤ 0.51 % |
| 40 bands, linear | ≤ 3.8e-4 | ≤ 0.39 % |
| 20 bands, quadratic | ≤ 8.4e-6 | ≤ 0.97 % |

With noise the error is dominated by the noise, not by the method; more bands reduce it
until curvature near the boundary (e.g. the chlorite Fe²⁺ band at ~1000 nm) takes over.

## smooth

Savitzky-Golay (`window`, `polyorder`) or centred moving average (`window`), applied to
each run of finite values separately — never across NaN gaps; runs shorter than the window
are left as they are. Requires a regular grid.

## continuum_removal

Upper convex hull of the reflectance over [`start`, `stop`], then reflectance / hull
(hull quotient). The output is cropped to the range and has quantity `continuum_removed`.

**Measured behaviour on noisy spectra:** the hull rests on the highest noise excursions, so
the quotient is biased low where there is no absorption — about 0.5–1 % after an 11-band
Savitzky-Golay, more without smoothing and on dark spectra (hematite). This will bias
shallow band depths measured later. Possible mitigations for the expert to choose from:
stronger smoothing before the hull, or fitting the hull on a smoothed copy while dividing
the unsmoothed spectrum.

## crop, mask, resample

`crop` keeps [`start`, `stop`]. `mask` sets `ranges` to NaN (e.g. atmospheric water bands in
field spectra). `resample` interpolates onto `start:stop:step` (linear or PCHIP); target
bands outside the data or inside NaN gaps are NaN, never extrapolated.

## Quality control (`swirl qc`)

Measures per spectrum, flagged against thresholds (each can be switched off):
maximum reflectance (`above_max`), mean reflectance (`low_albedo`), NaN fraction
(`missing_bands`), RMS residual from a Savitzky-Golay copy over `noise_range` (`noisy`), and
the largest relative splice correction (`splice_step`, same estimator as above, so its
own error is ~0.5 % at the synthetic noise level).
