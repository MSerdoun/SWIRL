"""HTTP API of the local app. It only translates between JSON and library calls."""

from __future__ import annotations

import base64
import io
import json
import math
import tempfile
import threading
import tomllib
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from functools import partial
from pathlib import Path, PurePath
from typing import Any, Literal

import numpy as np
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field, ValidationError

from swirl._version import __version__
from swirl.app.workspace import Entry, Workspace, as_set, group_by_grid
from swirl.core import meta as mk
from swirl.core.spectrum import SpectralSet, Spectrum
from swirl.drillhole import (
    as_sample,
    assign_hole_depth,
    build_log,
    clear_hole_depth,
    holes,
    summarize_assignments,
)
from swirl.features import BandParams, SpectrumBands, extract_bands, write_band_table
from swirl.io import formats, read
from swirl.io.text import write_text
from swirl.naming import Inference, NamingExample, apply_rules, infer_rules
from swirl.preprocess import (
    ProcessingError,
    QCParams,
    QCResult,
    Recipe,
    RecipeStep,
    get_operation,
    operations,
    run_qc,
)
from swirl.project import EXTENSION, ProjectError, load_project, save_project
from swirl.sampletable import (
    MatchReport,
    SampleTable,
    SampleTableError,
    TableMapping,
    guess_mapping,
    match_table,
    read_sample_table,
)
from swirl.synthetic import generative_bands, truth_in_window

# --- JSON helpers ---------------------------------------------------------------------------


def jsonable(obj: Any) -> Any:
    """Make metadata, history and metrics JSON-safe (NaN/inf -> None, numpy -> Python)."""
    if isinstance(obj, float | np.floating):
        return float(obj) if math.isfinite(obj) else None
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.ndarray):
        return [jsonable(x) for x in obj.tolist()]
    if isinstance(obj, Mapping):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [jsonable(x) for x in obj]
    return obj


def array(values: np.ndarray) -> list[float | None]:
    """Small arrays as JSON lists (NaN -> null)."""
    return [float(v) if math.isfinite(v) else None for v in values.tolist()]


def packed(values: np.ndarray) -> dict[str, Any]:
    """Large arrays as little-endian float32, base64 (4 bytes a value instead of ~20 as
    JSON text; NaN stays NaN). The browser decodes them into Float32Arrays."""
    a = np.ascontiguousarray(values, dtype="<f4")
    return {"f32": base64.b64encode(a.tobytes()).decode("ascii"), "shape": list(a.shape)}


class LRU:
    """A small thread-safe least-recently-used cache for computed results."""

    def __init__(self, size: int) -> None:
        self.size = size
        self._data: OrderedDict[Any, tuple[Any, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: Any, compute: Callable[[], tuple[Any, Any]]) -> Any:
        """The cached value for ``key``, else ``compute()`` → (objects kept alive, value)."""
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                return self._data[key][1]
        keep, value = compute()
        with self._lock:
            self._data[key] = (keep, value)
            self._data.move_to_end(key)
            while len(self._data) > self.size:
                self._data.popitem(last=False)
        return value


def spectra_key(entries: Sequence[Entry]) -> tuple[int, ...]:
    # Spectra are immutable and replaced (never modified) when their metadata change, so the
    # identity of the objects is a safe cache key while the cache keeps them alive.
    return tuple(id(e.spectrum) for e in entries)


def summary(entry: Entry) -> dict[str, Any]:
    s = entry.spectrum
    sample = as_sample(s)
    return {
        "id": entry.id,
        "name": s.name,
        "source": entry.source,
        "quantity": s.quantity.value,
        "n_bands": s.n_bands,
        "wl_min": float(s.wavelength[0]),
        "wl_max": float(s.wavelength[-1]),
        "file": PurePath(str(s.meta[mk.SOURCE_PATH])).stem if s.meta.get(mk.SOURCE_PATH) else None,
        "hole_id": sample.hole_id if sample else None,
        "depth_from": sample.depth_from if sample else None,
        "depth_to": sample.depth_to if sample else None,
    }


class Grids:
    """Wavelength axes sent once per response: spectra refer to them by key."""

    def __init__(self) -> None:
        self._keys: dict[bytes, str] = {}
        self.packed: dict[str, dict[str, Any]] = {}

    def key(self, wavelength: np.ndarray) -> str:
        raw = np.ascontiguousarray(wavelength, dtype=np.float64).tobytes()
        if raw not in self._keys:
            k = f"g{len(self._keys)}"
            self._keys[raw] = k
            self.packed[k] = packed(wavelength)
        return self._keys[raw]


def detail(entry: Entry, grids: Grids | None = None) -> dict[str, Any]:
    """A spectrum with its arrays. With ``grids``, the wavelength is a key into them."""
    s = entry.spectrum
    return {
        **summary(entry),
        **({"grid": grids.key(s.wavelength)} if grids else {"wavelength": packed(s.wavelength)}),
        "values": packed(s.values),
        "meta": jsonable(dict(s.meta)),
        "history": [jsonable(h.to_dict()) for h in s.history],
    }


# --- request models -------------------------------------------------------------------------


class StepIn(BaseModel):
    op: str
    params: dict[str, Any] = Field(default_factory=dict)


class ProcessIn(BaseModel):
    ids: list[str]
    steps: list[StepIn] = Field(default_factory=list)
    with_inputs: list[str] = Field(default_factory=list)


class IdsIn(BaseModel):
    ids: list[str]


class RecipeTextIn(BaseModel):
    text: str
    filename: str = "recipe.toml"


class BandsIn(BaseModel):
    ids: list[str]
    steps: list[StepIn] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)


class LogIn(BaseModel):
    hole_id: str
    steps: list[StepIn] = Field(default_factory=list)
    band_params: dict[str, Any] = Field(default_factory=dict)
    qc_params: dict[str, Any] = Field(default_factory=dict)
    image_max_bands: int = Field(400, ge=10, le=3000)


class ProjectSaveIn(BaseModel):
    name: str = ""
    created: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)
    visible_ids: list[str] = Field(default_factory=list)
    focused_id: str | None = None


class NamingIn(BaseModel):
    examples: list[NamingExample]
    source: Literal["name", "file"] = "name"
    only_unassigned: bool = False


class TableIn(BaseModel):
    table_id: str
    mapping: TableMapping


class ClearIn(BaseModel):
    ids: list[str] | None = None


class QCIn(BaseModel):
    ids: list[str]
    params: dict[str, Any] = Field(default_factory=dict)


def _recipe(steps: Sequence[StepIn]) -> Recipe:
    """Validate every step; report all invalid steps at once, with the step index."""
    built, problems = [], []
    for i, step in enumerate(steps):
        try:
            op = get_operation(step.op)
            built.append(RecipeStep(op.name, op.make_params(step.params)))
        except ProcessingError as exc:
            problems.append({"step": i, "op": step.op, "errors": [{"loc": [], "msg": str(exc)}]})
        except ValidationError as exc:
            errors = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
            problems.append({"step": i, "op": step.op, "errors": errors})
    if problems:
        raise HTTPException(status_code=422, detail={"steps": problems})
    return Recipe(steps=tuple(built))


_PROCESSED = LRU(48)
_BANDS = LRU(48)
_QC = LRU(48)


def _bands_for(
    group: Sequence[Entry], recipe: Recipe, params: BandParams
) -> tuple[SpectralSet, list[SpectrumBands]]:
    """Recipe output and band parameters of these spectra, both cached."""
    out = _run(recipe, group)
    key = (spectra_key(group), _recipe_key(recipe), params.model_dump_json())
    return out, _BANDS.get(key, partial(_compute_bands, out, params))


def _compute_bands(out: SpectralSet, params: BandParams) -> tuple[SpectralSet, list[SpectrumBands]]:
    return out, extract_bands(out, params)


def _qc_for(group: Sequence[Entry], params: QCParams) -> list[QCResult]:
    key = (spectra_key(group), params.model_dump_json())
    return _QC.get(key, partial(_compute_qc, group, params))  # type: ignore[no-any-return]


def _compute_qc(
    group: Sequence[Entry], params: QCParams
) -> tuple[tuple[Spectrum, ...], list[QCResult]]:
    return tuple(e.spectrum for e in group), run_qc(as_set(group), params)


def _recipe_key(recipe: Recipe) -> str:
    return json.dumps(recipe.to_dict(), sort_keys=True)


def _run(recipe: Recipe, group: Sequence[Entry]) -> SpectralSet:
    """The recipe output for these spectra, cached (same spectra + same recipe = reuse)."""

    def compute() -> tuple[tuple[Spectrum, ...], SpectralSet]:
        sset = as_set(group)
        # The spectra are kept with the result so their ids stay valid cache keys.
        return tuple(e.spectrum for e in group), (recipe.run(sset) if recipe.steps else sset)

    return _PROCESSED.get((spectra_key(group), _recipe_key(recipe)), compute)  # type: ignore[no-any-return]


def build_router(workspace: Workspace) -> APIRouter:
    router = APIRouter(prefix="/api")

    def lookup(ids: Sequence[str]) -> list[Entry]:
        try:
            return workspace.get(ids)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"unknown spectrum id(s): {exc}") from None

    def band_params(raw: Mapping[str, Any]) -> BandParams:
        try:
            return BandParams.model_validate(raw)
        except ValidationError as exc:
            errors = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
            raise HTTPException(status_code=422, detail={"params": errors}) from None

    @router.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "version": __version__}

    @router.get("/formats")
    def list_formats() -> list[dict[str, Any]]:
        return [
            {"name": f.name, "extensions": list(f.extensions), "description": f.description}
            for f in formats()
            if f.reader is not None
        ]

    @router.get("/spectra")
    def list_spectra() -> list[dict[str, Any]]:
        return [summary(e) for e in workspace.entries()]

    @router.get("/spectra/{entry_id}")
    def get_spectrum(entry_id: str) -> dict[str, Any]:
        return detail(lookup([entry_id])[0])

    @router.delete("/spectra/{entry_id}")
    def delete_spectrum(entry_id: str) -> dict[str, str]:
        try:
            workspace.remove(entry_id)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"unknown spectrum id {entry_id}") from None
        return {"deleted": entry_id}

    @router.delete("/spectra")
    def clear_spectra() -> dict[str, str]:
        workspace.clear()
        return {"status": "cleared"}

    @router.post("/spectra/upload")
    async def upload(files: list[UploadFile] = File(...)) -> dict[str, Any]:  # noqa: B008
        added: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for upload in files:
            filename = Path(upload.filename or "upload").name
            content = await upload.read()
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / filename
                path.write_bytes(content)
                try:
                    spectra = read(path)
                except (ValueError, OSError) as exc:
                    errors.append({"file": filename, "message": str(exc)})
                    continue
            spectra = [_with_source(s, filename) for s in spectra]
            added.extend(summary(e) for e in workspace.add(spectra, filename))
        return {"added": added, "errors": errors}

    @router.post("/spectra/examples")
    def load_examples() -> dict[str, Any]:
        from swirl.synthetic import generate_sample_set

        with tempfile.TemporaryDirectory() as tmp:
            truth = generate_sample_set(tmp)
            spectra = [
                _with_source(read(Path(tmp) / entry["file"])[0], entry["file"])
                for entry in truth["spectra"].values()
            ]
        return {"added": [summary(e) for e in workspace.add(spectra, "synthetic")], "errors": []}

    @router.post("/spectra/examples/hole")
    def load_example_hole() -> dict[str, Any]:
        from swirl.synthetic.drillhole import synthetic_drillhole

        spectra = synthetic_drillhole()
        return {
            "added": [summary(e) for e in workspace.add(spectra, "synthetic hole")],
            "errors": [],
        }

    @router.get("/holes")
    def list_holes() -> list[dict[str, Any]]:
        found = holes(e.spectrum for e in workspace.entries())
        return [
            {
                "hole_id": h,
                "n": len(samples),
                "top": samples[0].depth_from,
                "bottom": samples[-1].depth_to,
            }
            for h, samples in sorted(found.items())
        ]

    @router.post("/log")
    def hole_log(body: LogIn) -> dict[str, Any]:
        """Strip-log arrays of one hole: recipe output image, band parameters, QC, truth."""
        recipe = _recipe(body.steps)
        bparams = band_params(body.band_params)
        try:
            qparams = QCParams.model_validate(body.qc_params)
        except ValidationError as exc:
            errors = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
            raise HTTPException(status_code=422, detail={"qc_params": errors}) from None
        entries = [
            e
            for e in workspace.entries()
            if (smp := as_sample(e.spectrum)) and smp.hole_id == body.hole_id
        ]
        if not entries:
            raise HTTPException(status_code=404, detail=f"no samples for hole {body.hole_id!r}")
        by_spectrum = {id(e.spectrum): e.id for e in entries}
        samples = holes(e.spectrum for e in entries)[body.hole_id]
        position = {id(smp.spectrum): i for i, smp in enumerate(samples)}
        ordered = sorted(entries, key=lambda e: position[id(e.spectrum)])
        try:
            processed, band_results = _bands_for(ordered, recipe, bparams)
            qc_results = (
                _qc_for(ordered, qparams)
                if ordered[0].spectrum.quantity.value == "reflectance"
                else None
            )
            log = build_log(
                samples,
                recipe=recipe,
                band_params=bparams,
                qc_params=qparams,
                image_max_bands=body.image_max_bands,
                processed=processed,
                band_results=band_results,
                qc_results=qc_results,
            )
        except (ProcessingError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        return {
            "hole_id": log.hole_id,
            "ids": [by_spectrum[id(smp.spectrum)] for smp in samples],
            "names": log.names,
            "depth_from": array(log.depth_from),
            "depth_to": array(log.depth_to),
            "quantity": log.quantity.value,
            "image": {"wavelength": packed(log.image_wavelength), "values": packed(log.image)},
            "mean_reflectance": array(log.mean_reflectance),
            "bands": jsonable(log.bands),
            "ratios": {k: array(v) for k, v in log.ratios.items()},
            "qc": [list(r.flags) for r in log.qc] if log.qc is not None else None,
            "truth": (
                {
                    "composition": {k: array(v) for k, v in log.truth_composition.items()},
                    "aloh_center": array(log.truth_aloh_center)
                    if log.truth_aloh_center is not None
                    else None,
                }
                if log.truth_composition is not None
                else None
            ),
            "notes": log.notes,
        }

    @router.post("/project/save")
    def project_save(body: ProjectSaveIn) -> Response:
        """The workspace spectra and the session settings as a .swirl file."""
        entries = workspace.entries()
        index = {e.id: i for i, e in enumerate(entries)}
        ui = dict(body.settings.get("ui") or {})
        ui["visible"] = [index[i] for i in body.visible_ids if i in index]
        ui["focused"] = index.get(body.focused_id) if body.focused_id else None
        settings = {**body.settings, "ui": ui, "sources": [e.source for e in entries]}
        buf = io.BytesIO()
        save_project(
            buf, [e.spectrum for e in entries], settings, name=body.name, created=body.created
        )
        filename = (body.name or "project").replace('"', "") + EXTENSION
        return Response(
            buf.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @router.post("/project/open")
    async def project_open(file: UploadFile = File(...)) -> dict[str, Any]:  # noqa: B008
        """Replace the workspace with a project's spectra; return its settings."""
        try:
            project = load_project(io.BytesIO(await file.read()))
        except ProjectError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        settings = project.settings
        sources = settings.pop("sources", None) or []
        workspace.clear()
        added = []
        for i, s in enumerate(project.spectra):
            source = sources[i] if i < len(sources) else "project"
            added.extend(workspace.add([s], str(source)))
        ids = [e.id for e in added]
        ui = dict(settings.get("ui") or {})
        visible = [ids[i] for i in ui.pop("visible", []) or [] if 0 <= int(i) < len(ids)]
        focused = ui.pop("focused", None)
        focused_id = (
            ids[int(focused)] if focused is not None and 0 <= int(focused) < len(ids) else None
        )
        settings["ui"] = ui

        warnings = []
        for key, model in (("band_params", BandParams), ("qc_params", QCParams)):
            try:
                model.model_validate(settings.get(key) or {})
            except ValidationError as exc:
                warnings.append(
                    f"{key} from the project are invalid and were reset: {exc.errors()[0]['msg']}"
                )
                settings[key] = {}
        steps = (settings.get("recipe") or {}).get("steps") or []
        for i, st in enumerate(steps):
            try:
                get_operation(st["op"]).make_params(st.get("params") or {})
            except (ProcessingError, ValidationError, KeyError) as exc:
                warnings.append(f"recipe step {i + 1} ({st.get('op')}) is invalid: {exc}")
        return {
            "name": project.name or Path(file.filename or "project").stem,
            "created": project.created,
            "saved": project.saved,
            "swirl_version": project.swirl_version,
            "settings": settings,
            "spectra": [summary(e) for e in added],
            "visible_ids": visible,
            "focused_id": focused_id,
            "warnings": warnings,
        }

    tables: dict[str, SampleTable] = {}

    def key_of(entry: Entry, source: str) -> str:
        if source == "file":
            src = entry.spectrum.meta.get(mk.SOURCE_PATH)
            if src:
                return PurePath(str(src)).stem
        return entry.spectrum.name

    def preview_rows(
        entries: list[Entry], keys: list[str], found: list[tuple[str, float, float] | None]
    ) -> list[dict[str, Any]]:
        seen: dict[tuple[str, float], int] = {}
        for f in found:
            if f is not None:
                seen[(f[0], f[1])] = seen.get((f[0], f[1]), 0) + 1
        rows = []
        for e, k, f in zip(entries, keys, found, strict=True):
            status = "unmatched" if f is None else "duplicate" if seen[(f[0], f[1])] > 1 else "ok"
            rows.append(
                {
                    "id": e.id,
                    "key": k,
                    "hole_id": f[0] if f else None,
                    "depth_from": f[1] if f else None,
                    "depth_to": f[2] if f else None,
                    "current_hole": e.spectrum.meta.get(mk.HOLE_ID),
                    "status": status,
                }
            )
        return rows

    def naming_targets(body: NamingIn) -> list[Entry]:
        entries = workspace.entries()
        if body.only_unassigned:
            entries = [e for e in entries if as_sample(e.spectrum) is None]
        return entries

    def run_naming(
        body: NamingIn,
    ) -> tuple[list[Entry], list[str], Inference, list[tuple[str, float, float] | None]]:
        entries = naming_targets(body)
        keys = [key_of(e, body.source) for e in entries]
        try:
            inference = infer_rules(body.examples, keys)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        # Names give a point depth: the interval is [depth, depth].
        found = [(hd[0], hd[1], hd[1]) if hd else None for hd in apply_rules(inference.rules, keys)]
        return entries, keys, inference, found

    @router.post("/holes/naming/preview")
    def naming_preview(body: NamingIn) -> dict[str, Any]:
        entries, keys, inference, found = run_naming(body)
        return {
            "rules": [r.description for r in inference.rules],
            "single_rule": inference.single,
            "rows": preview_rows(entries, keys, found),
            "summary": summarize_assignments(found),
        }

    @router.post("/holes/naming/apply")
    def naming_apply(body: NamingIn) -> dict[str, Any]:
        entries, _, inference, found = run_naming(body)
        rule = " | ".join(r.description for r in inference.rules)
        applied = 0
        for e, f in zip(entries, found, strict=True):
            if f is not None:
                workspace.replace(
                    e.id,
                    assign_hole_depth(
                        e.spectrum, f[0], f[1], f[2], source=f"name ({body.source})", rule=rule
                    ),
                )
                applied += 1
        return {"applied": applied, "spectra": [summary(e) for e in workspace.entries()]}

    @router.post("/holes/table")
    async def table_upload(file: UploadFile = File(...)) -> dict[str, Any]:  # noqa: B008
        try:
            table = read_sample_table(await file.read(), file.filename or "table.csv")
        except SampleTableError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        table_id = f"t{len(tables) + 1}"
        tables[table_id] = table
        return {
            "table_id": table_id,
            "filename": table.filename,
            "columns": table.columns,
            "n_rows": len(table.rows),
            "head": table.rows[:8],
            "mapping": guess_mapping(table.columns),
        }

    def run_table(body: TableIn) -> tuple[list[Entry], list[str], MatchReport]:
        table = tables.get(body.table_id)
        if table is None:
            raise HTTPException(
                status_code=404, detail="the table is no longer loaded; upload it again"
            )
        entries = workspace.entries()
        keys = [key_of(e, body.mapping.match_on) for e in entries]
        try:
            report = match_table(table, body.mapping, keys)
        except SampleTableError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        return entries, keys, report

    @router.post("/holes/table/preview")
    def table_preview(body: TableIn) -> dict[str, Any]:
        entries, keys, report = run_table(body)
        found = [(a.hole_id, a.depth_from, a.depth_to) if a else None for a in report.assignments]
        s = summarize_assignments(found)
        if report.unused_rows:
            s["warnings"].append(
                f"{len(report.unused_rows)} table row(s) match no spectrum: "
                + ", ".join(report.unused_rows[:5])
                + ("…" if len(report.unused_rows) > 5 else "")
            )
        if report.duplicate_keys:
            s["warnings"].append(
                f"{len(report.duplicate_keys)} duplicated sample id(s) in the table (first kept)"
            )
        if report.bad_rows:
            s["warnings"].append(
                f"{len(report.bad_rows)} row(s) without hole or numeric depth ignored"
            )
        return {"rows": preview_rows(entries, keys, found), "summary": s}

    @router.post("/holes/table/apply")
    def table_apply(body: TableIn) -> dict[str, Any]:
        entries, _, report = run_table(body)
        table = tables[body.table_id]
        applied = 0
        for e, a in zip(entries, report.assignments, strict=True):
            if a is not None:
                workspace.replace(
                    e.id,
                    assign_hole_depth(
                        e.spectrum,
                        a.hole_id,
                        a.depth_from,
                        a.depth_to,
                        source=f"table {table.filename}",
                    ),
                )
                applied += 1
        return {"applied": applied, "spectra": [summary(e) for e in workspace.entries()]}

    @router.post("/holes/clear")
    def holes_clear(body: ClearIn) -> dict[str, Any]:
        targets = workspace.entries() if body.ids is None else lookup(body.ids)
        for e in targets:
            workspace.replace(e.id, clear_hole_depth(e.spectrum))
        return {"spectra": [summary(e) for e in workspace.entries()]}

    @router.post("/spectra/examples/named")
    def load_example_named() -> dict[str, Any]:
        from swirl.synthetic.drillhole import synthetic_named_samples

        spectra, _ = synthetic_named_samples()
        added = workspace.add(spectra, "synthetic named files")
        return {"added": [summary(e) for e in added], "errors": []}

    @router.get("/operations")
    def list_operations() -> list[dict[str, Any]]:
        return [
            {"name": op.name, "summary": op.summary, "schema": op.params.model_json_schema()}
            for op in operations()
        ]

    @router.post("/process")
    def process(body: ProcessIn) -> dict[str, Any]:
        recipe = _recipe(body.steps)
        grids = Grids()
        results: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for group in group_by_grid(lookup(body.ids)):
            try:
                out = _run(recipe, group)
            except ProcessingError as exc:
                errors.append({"ids": [e.id for e in group], "message": str(exc)})
                continue
            grid = grids.key(out.wavelength)
            for entry, s in zip(group, out, strict=True):
                results.append(
                    {
                        "id": entry.id,
                        "name": s.name,
                        "quantity": s.quantity.value,
                        "grid": grid,
                        "values": packed(s.values),
                        "history": [jsonable(h.to_dict()) for h in s.history],
                        "meta": jsonable(dict(s.meta)),
                    }
                )
        inputs = [detail(e, grids) for e in lookup(body.with_inputs)] if body.with_inputs else []
        return {"results": results, "errors": errors, "inputs": inputs, "grids": grids.packed}

    @router.post("/spectra/data")
    def spectra_data(body: IdsIn) -> dict[str, Any]:
        """Several spectra with their arrays in one request (wavelength axes sent once)."""
        grids = Grids()
        spectra = [detail(e, grids) for e in lookup(body.ids)]
        return {"spectra": spectra, "grids": grids.packed}

    @router.post("/recipe/parse")
    def parse_recipe(body: RecipeTextIn) -> dict[str, Any]:
        """Parse a TOML or JSON recipe file into validated steps."""
        try:
            if body.filename.lower().endswith(".json"):
                data = json.loads(body.text)
            else:
                data = tomllib.loads(body.text)
            recipe = Recipe.from_dict(data)
        except (ValueError, TypeError) as exc:  # JSON/TOML syntax and ProcessingError
            raise HTTPException(status_code=422, detail=str(exc)) from None
        return {
            "name": recipe.name,
            "description": recipe.description,
            "steps": [
                {"op": s.op, "params": s.params.model_dump(mode="json")} for s in recipe.steps
            ],
        }

    def run_bands(
        body: BandsIn,
    ) -> tuple[list[tuple[Entry, SpectrumBands, Spectrum]], list[dict[str, Any]]]:
        recipe, params = _recipe(body.steps), band_params(body.params)
        done: list[tuple[Entry, SpectrumBands, Spectrum]] = []
        errors: list[dict[str, Any]] = []
        for group in group_by_grid(lookup(body.ids)):
            try:
                out, results = _bands_for(group, recipe, params)
            except ProcessingError as exc:
                errors.append({"ids": [e.id for e in group], "message": str(exc)})
                continue
            done.extend(zip(group, results, out, strict=True))
        return done, errors

    @router.get("/bands/schema")
    def bands_schema() -> dict[str, Any]:
        return BandParams.model_json_schema()

    @router.post("/bands")
    def bands(body: BandsIn) -> dict[str, Any]:
        """Band parameters of the given spectra after the recipe; synthetic truth if known."""
        params = band_params(body.params)
        done, errors = run_bands(body)
        rows = []
        for entry, r, _ in done:
            truth = {}
            for b in params.bands:
                t = truth_in_window(entry.spectrum, b.lo, b.hi)
                if t is not None:
                    truth[b.name] = {
                        "center": t.center,
                        "depth": t.depth,
                        "fwhm": t.fwhm,
                        "assignment": t.assignment,
                    }
            rows.append(
                {
                    "id": entry.id,
                    "name": r.name,
                    "bands": {k: jsonable(asdict(m)) for k, m in r.bands.items()},
                    "ratios": jsonable(r.ratios),
                    "truth": truth if generative_bands(entry.spectrum) is not None else None,
                }
            )
        return {"rows": rows, "errors": errors}

    @router.post("/bands/export", response_class=PlainTextResponse)
    def bands_export(body: BandsIn) -> PlainTextResponse:
        params = band_params(body.params)
        done, errors = run_bands(body)
        if errors:
            raise HTTPException(status_code=422, detail="; ".join(e["message"] for e in errors))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bands.csv"
            write_band_table([r for _, r, _ in done], params, path)
            text = path.read_text(encoding="utf-8")
        return PlainTextResponse(
            text,
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="swirl_bands.csv"'},
        )

    @router.get("/qc/schema")
    def qc_schema() -> dict[str, Any]:
        return QCParams.model_json_schema()

    @router.post("/qc")
    def qc(body: QCIn) -> dict[str, Any]:
        try:
            params = QCParams.model_validate(body.params)
        except ValidationError as exc:
            errors = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
            raise HTTPException(status_code=422, detail={"params": errors}) from None
        results: list[dict[str, Any]] = []
        errors_out: list[dict[str, Any]] = []
        for group in group_by_grid(lookup(body.ids)):
            try:
                qc_results = _qc_for(group, params)
            except ProcessingError as exc:
                errors_out.append({"ids": [e.id for e in group], "message": str(exc)})
                continue
            for entry, r in zip(group, qc_results, strict=True):
                results.append(
                    {
                        "id": entry.id,
                        "name": r.name,
                        "metrics": jsonable(r.metrics),
                        "flags": list(r.flags),
                    }
                )
        return {"results": results, "errors": errors_out}

    @router.post("/export", response_class=PlainTextResponse)
    def export(body: ProcessIn) -> PlainTextResponse:
        recipe = _recipe(body.steps)
        groups = group_by_grid(lookup(body.ids))
        if len(groups) != 1:
            raise HTTPException(
                status_code=422,
                detail="the selected spectra are on different wavelength grids; add a "
                "'resample' step or export them separately",
            )
        try:
            out = _run(recipe, groups[0])
        except ProcessingError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "export.csv"
            write_text(_unique_names(out), path)
            text = path.read_text(encoding="utf-8")
        return PlainTextResponse(
            text,
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="swirl_export.csv"'},
        )

    return router


def _with_source(s: Spectrum, filename: str) -> Spectrum:
    """Replace the temporary upload path by the original file name."""
    return Spectrum(
        wavelength=s.wavelength,
        values=s.values,
        name=s.name,
        quantity=s.quantity,
        meta={**s.meta, mk.SOURCE_PATH: filename},
        history=s.history,
    )


def _unique_names(sset: SpectralSet) -> SpectralSet:
    seen: dict[str, int] = {}
    names = []
    for n in sset.names:
        clean = n.replace(",", "_").replace("]", "_") or "spectrum"
        seen[clean] = seen.get(clean, 0) + 1
        names.append(clean if seen[clean] == 1 else f"{clean}_{seen[clean]}")
    return SpectralSet(
        sset.wavelength,
        sset.values,
        names,
        quantity=sset.quantity,
        metas=sset.metas,
        histories=[s.history for s in sset],
    )
