# Changelog

## Unreleased

- Core data model: `Spectrum`, `SpectralSet`, `ProcessingStep` provenance, metadata keys.
- Delimited text reader (tab / `;` / `,` / whitespace, decimal comma, µm, percent — all
  recorded in history) and SWIRL text writer with metadata and history round-trip.
- Format registry: `swirl.read` / `swirl.write` dispatch on extension.
- Synthetic end-members (white mica, illite, chlorite, hematite) with noise, ASD splice
  steps and a ground-truth file; sample set in `examples/data/synthetic/`.
- CLI: `swirl info`, `swirl synth`.
- ASD binary reader (file versions 1–8): reflectance from target / white reference or the
  stored reflectance, raw DN and white-reference outputs, header metadata (instrument,
  acquisition time, integration time, gains, splice wavelengths, reference description).
- New quantity `raw` (instrument digital numbers).
- Pre-processing operations with validated, user-settable parameter models: `crop`,
  `mask`, `resample`, `splice_correction`, `smooth`, `continuum_removal`.
- Recipes (TOML / JSON) chaining operations; `swirl process`, `swirl ops`.
- Quality control with settable thresholds; `swirl qc`.
- Graphical interface (`swirl app`): file import (drag and drop), interactive spectrum plot
  (input / processed / both, stacked when quantities differ), live recipe editor with forms
  generated from the parameter models, recipe load/save, QC table with editable thresholds,
  metadata and history view, CSV export.
- Absorption-band parameters (`swirl.features`): position (parabola / Gaussian / minimum),
  depth, width at half depth, asymmetry, curvature, minimum/shoulder/absent status and depth
  ratios, for an editable band table (defaults = the project's working definitions);
  continuum from the recipe or local per window. `swirl bands` CLI and CSV export; GUI tab
  with band-table and ratio editors, results matrix (including the error vs synthetic
  truth), and band markers and search windows on the plot. Accuracy measured on the
  synthetic set in docs/science/band_parameters.md.
