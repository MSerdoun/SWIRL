"""HTTP API of the local app. It only translates between JSON and library calls."""

from __future__ import annotations

import json
import math
import tempfile
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field, ValidationError

from swirl._version import __version__
from swirl.app.workspace import Entry, Workspace, as_set, group_by_grid
from swirl.core import meta as mk
from swirl.core.spectrum import SpectralSet, Spectrum
from swirl.io import formats, read
from swirl.io.text import write_text
from swirl.preprocess import (
    ProcessingError,
    QCParams,
    Recipe,
    RecipeStep,
    get_operation,
    operations,
    run_qc,
)

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
    return [float(v) if math.isfinite(v) else None for v in values.tolist()]


def summary(entry: Entry) -> dict[str, Any]:
    s = entry.spectrum
    return {
        "id": entry.id,
        "name": s.name,
        "source": entry.source,
        "quantity": s.quantity.value,
        "n_bands": s.n_bands,
        "wl_min": float(s.wavelength[0]),
        "wl_max": float(s.wavelength[-1]),
    }


def detail(entry: Entry) -> dict[str, Any]:
    s = entry.spectrum
    return {
        **summary(entry),
        "wavelength": array(s.wavelength),
        "values": array(s.values),
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


class RecipeTextIn(BaseModel):
    text: str
    filename: str = "recipe.toml"


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


def _run(recipe: Recipe, group: Sequence[Entry]) -> SpectralSet:
    sset = as_set(group)
    return recipe.run(sset) if recipe.steps else sset


def build_router(workspace: Workspace) -> APIRouter:
    router = APIRouter(prefix="/api")

    def lookup(ids: Sequence[str]) -> list[Entry]:
        try:
            return workspace.get(ids)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"unknown spectrum id(s): {exc}") from None

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

    @router.get("/operations")
    def list_operations() -> list[dict[str, Any]]:
        return [
            {"name": op.name, "summary": op.summary, "schema": op.params.model_json_schema()}
            for op in operations()
        ]

    @router.post("/process")
    def process(body: ProcessIn) -> dict[str, Any]:
        recipe = _recipe(body.steps)
        results: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for group in group_by_grid(lookup(body.ids)):
            try:
                out = _run(recipe, group)
            except ProcessingError as exc:
                errors.append({"ids": [e.id for e in group], "message": str(exc)})
                continue
            for entry, s in zip(group, out, strict=True):
                results.append(
                    {
                        "id": entry.id,
                        "name": s.name,
                        "quantity": s.quantity.value,
                        "wavelength": array(s.wavelength),
                        "values": array(s.values),
                        "history": [jsonable(h.to_dict()) for h in s.history],
                        "meta": jsonable(dict(s.meta)),
                    }
                )
        return {"results": results, "errors": errors}

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
                qc_results = run_qc(as_set(group), params)
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
