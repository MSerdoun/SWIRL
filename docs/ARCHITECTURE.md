# Architecture

## Layers

```
swirl.core        data model: Spectrum, SpectralSet, ProcessingStep, metadata keys
swirl.io          file formats behind one registry: read(path) / write(spectra, path)
swirl.synthetic   end-members with known ground truth, for tests and calibration
swirl.preprocess  operations (crop, mask, resample, splice, smooth, continuum), recipes, QC
swirl.features    band parameters (position, depth, width, asymmetry, ratios); later matching, rules
swirl.drillhole   samples grouped by hole and depth; strip-log arrays (build_log)
swirl.naming      hole & depth read from names by example (rule inference, no regex for users)
swirl.sampletable sample sheets (CSV/TSV) joined to spectra
swirl.project     .swirl projects: spectra (exact) + session settings; GUI ↔ notebook bridge
swirl.cli         command line (`swirl ...`)
swirl.app         FastAPI backend (in-memory workspace + JSON API) serving the Vue frontend
frontend/         Vue 3 + Vuetify + Plotly; built into src/swirl/app/static
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

**D6 — Parameters as data, all user-settable.** Every operation declares a pydantic
parameter model (defaults, bounds, descriptions; unknown fields rejected). The same model
validates Python calls and recipe files, is recorded verbatim in the history, and will give
the GUI its forms through `model_json_schema()` — no GUI ↔ backend drift.

**D9 — Recipes.** A processing chain is data: an ordered list of `{op, params}` in TOML or
JSON, validated entirely before any spectrum is touched. The same recipe runs from Python,
the CLI (`swirl process`) and the GUI.

**D7 — Validation before trust.** Each algorithm lands with a science spec and a reference
case (see `docs/science/`), and a test that scores it against that case. Synthetic spectra
carry their generating parameters (`truth.json`) for this purpose.

**D8 — Local web GUI.** FastAPI + Vue, with the built frontend shipped inside the Python
package; `swirl app` opens the browser. Point-spectra volumes fit in memory, so no tiling.
The API only translates JSON to library calls; processing and QC always run server-side,
so the GUI, the CLI and Python give identical results. Spectra on different grids are
processed in separate groups rather than resampled behind the user's back.

**D10 — Projects are a bridge, not a database.** A `.swirl` file is a zip of readable JSON
(settings, metadata, history) and float64 arrays; loading never executes anything (no
pickle). The GUI settings it carries are plain data that Python can turn back into a recipe,
band and QC parameters, so a session started in the GUI continues in a notebook and back.

**D11 — Measure, then keep the GUI light.** Large arrays travel as float32 (base64) with
each wavelength axis sent once, and stay outside Vue's reactivity; the server caches
recipe outputs, band parameters and QC by (spectra identity, parameters); a panel's data
is computed only while it is shown; long lists are virtualised. Performance claims are
measured before and after (see the changelog), never assumed.

## Naming

The PyPI name `swirl` is taken, so the distribution is `swirl-spectra`; the import name is
`swirl`.
