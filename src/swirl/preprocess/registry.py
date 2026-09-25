"""Operation registry: every processing operation is a function plus a parameter model.

The parameter model is the single definition of what the user can set: it validates input
(unknown or misspelt parameters are errors), carries defaults and descriptions, and gives
the GUI its forms (``model_json_schema()``).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar, overload

from pydantic import BaseModel, ConfigDict

from swirl.core.spectrum import ProcessingStep, SpectralSet, Spectrum


class Params(BaseModel):
    """Base class for operation parameters: immutable, unknown fields rejected."""

    model_config = ConfigDict(extra="forbid", frozen=True)


P = TypeVar("P", bound=Params)
OpFunc = Callable[[SpectralSet, Any, ProcessingStep], SpectralSet]


class ProcessingError(ValueError):
    """An operation cannot be applied to the given spectra with the given parameters."""


@dataclass(frozen=True)
class Operation:
    name: str
    params: type[Params]
    func: OpFunc
    summary: str

    def make_params(
        self, params: Params | Mapping[str, Any] | None = None, **kwargs: Any
    ) -> Params:
        if isinstance(params, Params):
            if not isinstance(params, self.params):
                raise TypeError(f"{self.name} expects {self.params.__name__}")
            if not kwargs:
                return params
            params = params.model_dump()
        return self.params.model_validate({**(params or {}), **kwargs})

    def run(self, sset: SpectralSet, params: Params) -> SpectralSet:
        step = ProcessingStep(self.name, params.model_dump(mode="json"))
        return self.func(sset, params, step)


_OPERATIONS: dict[str, Operation] = {}


def operation(name: str, params: type[P]) -> Callable[[OpFunc], OpFunc]:
    """Register ``func(sset, params, step) -> SpectralSet`` as operation ``name``."""

    def decorator(func: OpFunc) -> OpFunc:
        if name in _OPERATIONS:
            raise ValueError(f"operation {name!r} is already registered")
        doc = (func.__doc__ or "").strip()
        _OPERATIONS[name] = Operation(name, params, func, doc.splitlines()[0] if doc else "")
        return func

    return decorator


def get_operation(name: str) -> Operation:
    try:
        return _OPERATIONS[name]
    except KeyError:
        raise ProcessingError(f"unknown operation {name!r}; known: {sorted(_OPERATIONS)}") from None


def operations() -> list[Operation]:
    return [_OPERATIONS[k] for k in sorted(_OPERATIONS)]


@overload
def apply(
    name: str, data: Spectrum, params: Params | Mapping[str, Any] | None = ..., **kwargs: Any
) -> Spectrum: ...
@overload
def apply(
    name: str,
    data: SpectralSet | Sequence[Spectrum],
    params: Params | Mapping[str, Any] | None = ...,
    **kwargs: Any,
) -> SpectralSet: ...
def apply(
    name: str,
    data: Spectrum | SpectralSet | Sequence[Spectrum],
    params: Params | Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> Spectrum | SpectralSet:
    """Apply operation ``name`` to one spectrum or a set; parameters as a model, dict or kwargs."""
    op = get_operation(name)
    p = op.make_params(params, **kwargs)
    if isinstance(data, Spectrum):
        return op.run(SpectralSet.from_spectra([data]), p)[0]
    sset = data if isinstance(data, SpectralSet) else SpectralSet.from_spectra(data)
    return op.run(sset, p)
