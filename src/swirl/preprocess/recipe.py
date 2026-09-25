"""Recipes: an ordered list of operations with their parameters, stored as TOML or JSON.

TOML example::

    name = "TerraSpec core"

    [[steps]]
    op = "splice_correction"
    reference_segment = 1

    [[steps]]
    op = "smooth"
    window = 11

    [[steps]]
    op = "continuum_removal"
    start = 1300
    stop = 2500

Every parameter is validated when the recipe is loaded, before any spectrum is processed.
"""

from __future__ import annotations

import json
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from swirl.core.spectrum import SpectralSet, Spectrum
from swirl.preprocess.registry import Params, ProcessingError, get_operation


@dataclass(frozen=True)
class RecipeStep:
    op: str
    params: Params

    def to_dict(self) -> dict[str, Any]:
        return {"op": self.op, **self.params.model_dump(mode="json")}


@dataclass(frozen=True)
class Recipe:
    steps: tuple[RecipeStep, ...]
    name: str = ""
    description: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Recipe:
        raw_steps = data.get("steps")
        if not isinstance(raw_steps, Sequence) or not raw_steps:
            raise ProcessingError("a recipe needs a non-empty 'steps' list")
        steps = []
        for i, raw in enumerate(raw_steps, start=1):
            params = dict(raw)
            name = params.pop("op", None)
            if not name:
                raise ProcessingError(f"step {i} has no 'op'")
            op = get_operation(str(name))
            try:
                steps.append(RecipeStep(op.name, op.make_params(params)))
            except ValidationError as exc:
                raise ProcessingError(f"step {i} ({name}): {exc}") from None
        return cls(
            steps=tuple(steps),
            name=str(data.get("name", "")),
            description=str(data.get("description", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "steps": [s.to_dict() for s in self.steps],
        }

    def run(self, data: SpectralSet | Sequence[Spectrum]) -> SpectralSet:
        sset = data if isinstance(data, SpectralSet) else SpectralSet.from_spectra(data)
        for step in self.steps:
            sset = get_operation(step.op).run(sset, step.params)
        return sset


def load_recipe(path: str | Path) -> Recipe:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    data = json.loads(text) if path.suffix.lower() == ".json" else tomllib.loads(text)
    return Recipe.from_dict(data)


def save_recipe(recipe: Recipe, path: str | Path) -> None:
    """Save as JSON (loadable again with :func:`load_recipe`)."""
    Path(path).write_text(json.dumps(recipe.to_dict(), indent=2) + "\n", encoding="utf-8")
