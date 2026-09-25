# Synthetic end-members — status: TO REVIEW

The four end-members in `src/swirl/synthetic/minerals.toml` (white mica, illite, chlorite,
hematite) were written by the developer as generic placeholders to exercise the code. They
have **not** been reviewed by the domain expert and must not be used to calibrate an
interpretation algorithm until they have been.

## Model

R(λ) = C(λ) · Π_i [1 - d_i · exp(-4 ln2 (λ - c_i)² / w_i²)]

C is a monotone cubic (PCHIP) through the continuum anchors; c, w, d are the band centre,
FWHM and depth relative to the continuum. The depth is exact for an isolated band;
overlapping bands shift the apparent minimum and depth, so measured values will differ from
the generating parameters there.

## Noisy variants

`*_noisy.txt` add Gaussian noise whose sigma rises at both ends of the range, and
multiplicative steps on the ASD VNIR (≤ 1000 nm) and SWIR2 (> 1800 nm) detectors. The exact
offsets and seeds are in `examples/data/synthetic/truth.json`.

## Points for the expert to review

- Band centres, widths and depths of each end-member.
- Illite vs white mica: the 2200/1900 depth ratio (≈ 7 for white mica, ≈ 1.4 for illite).
- Chlorite: Fe2+ band at ~1050 nm, FeOH 2253 / MgOH 2340 positions for a Fe-Mg chlorite.
- Hematite: charge-transfer edge shape and the ~870 nm crystal-field band.
- Noise level (base sigma 0.0015) and splice offset amplitude (≤ 2 %).
