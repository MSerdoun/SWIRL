# Architecture

## Layers

```
swirl.core        data model: Spectrum, SpectralSet, ProcessingStep, metadata keys
swirl.io          file formats behind one registry: read(path) / write(spectra, path)
swirl.synthetic   end-members with known ground truth, for tests and calibration
swirl.preprocess  (planned) splice correction, smoothing, resampling, continuum removal, QC
swirl.features    (planned) absorption-feature extraction, scalars, library matching, rules
swirl.cli         command line (`swirl ...`)
swirl.app         (planned) FastAPI backend serving the Vue frontend — a client of the above
```

Dependencies only point downwards: `core` imports nothing from SWIRL, `io` imports `core`,
processing imports `core`, and the CLI and the app import everything. Nothing below `app`
knows a GUI exists.

## Decisions

**D1 — The library is the product, the GUI is a client.** Anything the GUI does is a library
call that can be scripted. The GUI holds no science.

**D2 — Canonical units.** Wavelength in nm (finite, strictly increasing), reflectance as a
fraction. Readers convert on the way in; conversions are recorded, never silent.

**D3 — Immutable objects with provenance.** Arrays are read-only; every operation returns a
new object and appends a `ProcessingStep(name, params, swirl_version)` to its history. The
history is written into exported files, so any product can be traced and replayed.

**D4 — No silent resampling.** A `SpectralSet` requires one shared grid. Spectra on
different grids are rejected; resampling is an explicit, recorded processing step.

**D5 — Formats are plugins.** A format is a module plus one `register_format` call. Reading
returns `list[Spectrum]`, because one file can hold several spectra.

**D6 — Parameters as data.** Algorithm parameters will be plain dataclasses / schemas, so the
GUI generates its forms from them instead of duplicating them (no GUI ↔ backend drift).

**D7 — Validation before trust.** Each algorithm lands with a science spec and a reference
case (see `docs/science/`), and a test that scores it against that case. Synthetic spectra
carry their generating parameters (`truth.json`) for this purpose.

**D8 — Local web GUI.** FastAPI + Vue, with the built frontend shipped inside the Python
package; `swirl app` opens the browser. Point-spectra volumes fit in memory, so no tiling.

## Naming

The PyPI name `swirl` is taken, so the distribution is `swirl-spectra`; the import name is
`swirl`.
