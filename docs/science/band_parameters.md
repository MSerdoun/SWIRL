# Band parameters — method and measured accuracy (synthetic set)

`swirl.features.extract_bands` measures, for each band definition (name, nominal centre,
search window), the **position**, **depth**, **width at half depth**, **asymmetry**, 2nd-
derivative **curvature** and a **status** (`minimum`, `shoulder`, `absent`, `no_data`), plus
depth **ratios**. The default band table and ratios are the project's working definitions
(from the calibration notebook); every parameter is editable (Python, `swirl bands
--config`, GUI "Band parameters" tab).

Method details are in the module docstring. In short: deepest sample in the window; if it
sits on the window edge there is no local minimum and, with shoulder detection, the band is
placed at the 2nd-derivative maximum; the position is refined by a parabola (`fit_points`,
3 by default, vertex rejected if outside the fitted samples), a Gaussian fit, or left at the
sample; depth = 1 − CR.

## Validation

Analytic cases (tests): a Gaussian band on a flat continuum is recovered exactly (position,
depth, width = FWHM, asymmetry 0); an off-grid centre (2203.4 nm) is found to 0.01 nm by the
3-point parabola and to 1e-4 nm by the Gaussian fit; shoulders, absent bands, windows
without data, ratios and parameter validation are covered.

Synthetic end-members, **clean**, after `continuum_removal` over 1300–2500 nm: every
generated band (OH ~1400, AlOH, FeOH, MgOH) is found within **0.03 nm** of its generating
centre.

Synthetic end-members, **noisy** (50 noise draws, synthetic noise model + random ASD splice
steps). Position error vs the generating centre, RMSE / max |error| in nm:

Recipe = splice correction + Savitzky-Golay 11 + continuum removal 1300–2500:

| band | minimum | parabola 3 (default) | parabola 7 | parabola 11 | Gaussian |
|---|---|---|---|---|---|
| white mica OH1400 | 0.20 / 1.00 | 0.23 / 0.59 | 0.13 / 0.26 | 0.09 / 0.19 | 0.04 / 0.10 |
| white mica AlOH | 0.51 / 1.00 | 0.38 / 0.77 | 0.23 / 0.64 | 0.15 / 0.46 | 0.04 / 0.10 |
| white mica MgOH (2350) | 0.49 / 1.00 | 0.38 / 0.86 | 0.27 / 0.75 | 0.18 / 0.55 | 0.09 / 0.20 |
| illite OH1400 | 0.71 / 2.00 | 0.60 / 1.88 | 0.36 / 1.10 | 0.25 / 0.72 | 0.06 / 0.14 |
| illite AlOH | 0.65 / 1.00 | 0.53 / 1.21 | 0.33 / 0.72 | 0.22 / 0.53 | 0.05 / 0.16 |
| chlorite OH1400 | 0.97 / 2.00 | 0.87 / 1.82 | 0.68 / 1.66 | 0.41 / 0.99 | 0.19 / 0.47 |
| chlorite FeOH | 0.65 / 1.00 | 0.54 / 1.23 | 0.41 / 0.90 | 0.28 / 0.73 | 0.08 / 0.21 |
| chlorite MgOH (2340) | 1.17 / 5.00 | 0.93 / 2.97 | 0.75 / 1.98 | 0.72 / 1.37 | 0.40 / 1.01 |

Without smoothing the errors roughly double (parabola 3: up to 3.3 nm; Gaussian: ≤ 0.3 nm
except chlorite MgOH 1.6 nm). The parabola-7 run without smoothing showed one 11.8 nm
outlier, caused by a vertex extrapolated outside its fitted samples; such vertices are now
rejected.

**Caveat — the Gaussian fit is favoured by construction:** the synthetic bands *are*
Gaussians. Real absorptions are asymmetric, doublets or overlapping, where a Gaussian fit
may be biased; the wider parabolas (7–11 points) make no shape assumption and already cut
the 3-point error by 2–3×. Choosing the default is the expert's call.

## Behaviours worth knowing (seen on the synthetic set)

1. **Narrow local continuum biases the position.** With `continuum = local` (hull over the
   search window only) the window edges sit inside the band wings of broad bands: on the
   *clean* white mica the AlOH position is off by +1.8 nm, the chlorite MgOH by +8.3 nm.
   A continuum removed over a broad range first (as in the notebook) brings both to
   ≤ 0.03 nm.
2. **A band next to a window edge.** The chlorite MgOH band (2340 nm) is 2 nm inside the
   MgOH window (2338–2378); with noise its minimum can fall on the edge sample and it is
   then treated as a shoulder (84 % of draws are "minimum" without smoothing, 98 % with),
   with errors up to 5–7 nm. The same band also appears as a deep "shoulder" in the
   neighbouring CO3 window (2305–2338).
3. **Wings of strong neighbours read as shoulders.** On white mica the APS2170 window
   (2162–2188) reports a 0.25-deep "shoulder" that is the wing of the AlOH band.
4. **Absent bands still get a position.** With `min_depth = 0` (notebook behaviour) a
   window without an absorption reports the deepest noise sample (depth ~0.00–0.01).
   Setting `min_depth` (e.g. above the noise level) reports them as absent.
