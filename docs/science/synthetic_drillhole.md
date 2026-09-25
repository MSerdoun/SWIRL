# Synthetic drill hole — known zonation, and what the log recovers

`swirl.synthetic.drillhole.synthetic_drillhole()` (GUI: flask menu → *Synthetic drill hole*;
CLI: `swirl synth-hole out.csv`) generates **SYN-DH01**: 200 one-metre samples, 0–200 m, each
a linear mixture of the synthetic end-members. Every parameter is in `DrillholeConfig`.

| Zone (m) | Composition | Story |
|---|---|---|
| 0–60 | white mica 0.85, illite 0.15 | sericitic |
| 60–110 | illite 0.8, white mica 0.1, chlorite 0.1 | illitic |
| 110–160 | chlorite 0.75, illite 0.25 | chloritic |
| 160–200 | chlorite 0.65, hematite 0.35 | chloritic, hematitic |

* Boundaries are blended linearly over 8 m; each fraction gets a 4 % random jitter.
* The white-mica AlOH centre drifts linearly from 2196 nm (top) to 2214 nm (bottom): a
  composition vector to recover.
* 3 samples are darkened ×0.06 (wet/dark core) to exercise QC.
* Noise and random ASD splice steps (≤ 2 % VNIR, ≤ 1.5 % SWIR2) as for the noisy
  end-members.
* The truth travels with each spectrum: `synthetic_composition`,
  `synthetic_aloh_center`, `synthetic_dark`, plus `hole_id`, `depth_from`, `depth_to`.

These zones are an illustration built from the four placeholder end-members, not a
deposit model.

## What the log recovers (recipe `examples/recipes/swir_basic.toml`, default band table)

Measured on the default hole (tests in `tests/test_drillhole.py`):

| Check | Result |
|---|---|
| FeOH depth vs chlorite fraction (linear r, QC-passed samples) | 0.98 |
| AlOH depth vs white mica + illite fraction | 0.99 |
| MgOH depth vs chlorite fraction | 0.89 — the MgOH window also holds the micas' 2350 nm band |
| AlOH position vs generating centre, white-mica-dominant samples | r = 0.97, median bias +0.7 nm |
| Mean reflectance, hematitic zone vs sericitic zone | < 0.65× |
| Darkened samples flagged `low_albedo` | exactly the 3 |

Notes:

* Rank correlations are misleading here: 60 samples have exactly zero chlorite, and their
  noise-level FeOH depths rank at random. Linear correlation is the right measure for
  linear mixtures.
* The +0.7 nm AlOH bias is physical, not a defect: the 15 % illite (AlOH at 2205 nm) in the
  sericitic zone pulls the mixture's minimum towards 2205 nm. The position of a mixture is
  not the position of its white mica.
* Where the AlOH band is weak (chloritic zones), its "position" is a noise-level minimum;
  `min_depth` in the band parameters reports it absent instead.
* QC flags ~65 % of samples for `splice_step`: the random synthetic steps (up to 2 %) are
  often above the 1 % default threshold. QC is measured on the input spectra, before any
  splice correction in the recipe.

## Performance

Building the full log (recipe, 9 bands, QC, 200 × 2151 spectra) takes ≈ 0.8 s: the
convex hull uses qhull, and Savitzky-Golay filters run on all spectra at once (results
identical to the per-spectrum path, checked by the test suite).
