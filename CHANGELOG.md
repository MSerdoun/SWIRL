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
