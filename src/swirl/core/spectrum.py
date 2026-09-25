"""Core data model: a single spectrum, a set of spectra on a shared grid, and provenance.

Conventions (see docs/ARCHITECTURE.md):

* wavelength is in nanometres, finite and strictly increasing;
* reflectance is a fraction (0-1), never a percentage;
* objects are immutable — every processing step returns a new object and appends a
  :class:`ProcessingStep` to its history, so any product can be traced back to its inputs.
"""

from __future__ import annotations

import enum
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

import numpy as np
from numpy.typing import ArrayLike, NDArray

from swirl._version import __version__

FloatArray = NDArray[np.float64]


class Quantity(enum.StrEnum):
    """Physical meaning of the values carried by a spectrum."""

    REFLECTANCE = "reflectance"
    """Reflectance as a fraction (0-1)."""
    CONTINUUM_REMOVED = "continuum_removed"
    """Reflectance divided by its continuum (hull quotient)."""


@dataclass(frozen=True)
class ProcessingStep:
    """One entry of a spectrum's provenance: what was done, with which parameters."""

    name: str
    params: Mapping[str, Any] = field(default_factory=dict)
    swirl_version: str = __version__

    def __post_init__(self) -> None:
        object.__setattr__(self, "params", MappingProxyType(dict(self.params)))

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "params": dict(self.params), "swirl_version": self.swirl_version}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ProcessingStep:
        return cls(
            name=str(data["name"]),
            params=dict(data.get("params", {})),
            swirl_version=str(data.get("swirl_version", "unknown")),
        )


def _frozen_array(values: ArrayLike, what: str) -> FloatArray:
    arr = np.array(values, dtype=np.float64, copy=True)
    if arr.ndim != 1:
        raise ValueError(f"{what} must be one-dimensional, got shape {arr.shape}")
    arr.flags.writeable = False
    return arr


def _check_wavelength(wavelength: FloatArray) -> None:
    if wavelength.size < 2:
        raise ValueError("a spectrum needs at least two wavelengths")
    if not np.all(np.isfinite(wavelength)):
        raise ValueError("wavelength contains non-finite values")
    if not np.all(np.diff(wavelength) > 0):
        raise ValueError("wavelength must be strictly increasing")


@dataclass(frozen=True, eq=False)
class Spectrum:
    """A single spectrum: values sampled on a wavelength axis, plus metadata and provenance.

    ``values`` may contain NaN (masked or bad bands); ``wavelength`` may not.
    ``meta`` holds free-form metadata; the conventional keys are listed in
    :mod:`swirl.core.meta`.
    """

    wavelength: FloatArray
    values: FloatArray
    name: str
    quantity: Quantity = Quantity.REFLECTANCE
    meta: Mapping[str, Any] = field(default_factory=dict)
    history: tuple[ProcessingStep, ...] = ()

    def __post_init__(self) -> None:
        wl = _frozen_array(self.wavelength, "wavelength")
        vals = _frozen_array(self.values, "values")
        _check_wavelength(wl)
        if vals.shape != wl.shape:
            raise ValueError(
                f"values ({vals.size}) and wavelength ({wl.size}) must have the same length"
            )
        object.__setattr__(self, "wavelength", wl)
        object.__setattr__(self, "values", vals)
        object.__setattr__(self, "quantity", Quantity(self.quantity))
        object.__setattr__(self, "meta", MappingProxyType(dict(self.meta)))
        object.__setattr__(self, "history", tuple(self.history))

    @property
    def n_bands(self) -> int:
        return int(self.wavelength.size)

    def derive(
        self,
        step: ProcessingStep,
        *,
        values: ArrayLike | None = None,
        wavelength: ArrayLike | None = None,
        quantity: Quantity | None = None,
        meta: Mapping[str, Any] | None = None,
    ) -> Spectrum:
        """Return a new spectrum produced by ``step``, with ``step`` appended to the history."""
        return Spectrum(
            wavelength=self.wavelength if wavelength is None else np.asarray(wavelength),
            values=self.values if values is None else np.asarray(values),
            name=self.name,
            quantity=self.quantity if quantity is None else quantity,
            meta=self.meta if meta is None else meta,
            history=(*self.history, step),
        )

    def __repr__(self) -> str:
        return (
            f"Spectrum(name={self.name!r}, quantity={self.quantity.value}, "
            f"bands={self.n_bands}, range={self.wavelength[0]:g}-{self.wavelength[-1]:g} nm, "
            f"steps={len(self.history)})"
        )


class SpectralSet(Sequence[Spectrum]):
    """Several spectra sharing one wavelength grid, stored as a 2-D array for batch processing.

    Building a set never resamples silently: spectra on different grids are rejected, and
    resampling must be an explicit processing step.
    """

    __slots__ = ("_histories", "_metas", "_names", "_quantity", "_values", "_wavelength")

    def __init__(
        self,
        wavelength: ArrayLike,
        values: ArrayLike,
        names: Sequence[str],
        *,
        quantity: Quantity = Quantity.REFLECTANCE,
        metas: Sequence[Mapping[str, Any]] | None = None,
        histories: Sequence[Sequence[ProcessingStep]] | None = None,
    ) -> None:
        wl = _frozen_array(wavelength, "wavelength")
        _check_wavelength(wl)
        vals = np.array(values, dtype=np.float64, copy=True)
        if vals.ndim != 2 or vals.shape[1] != wl.size:
            raise ValueError(f"values must have shape (n_spectra, {wl.size}), got {vals.shape}")
        n = vals.shape[0]
        if len(names) != n:
            raise ValueError(f"expected {n} names, got {len(names)}")
        metas = [{}] * n if metas is None else metas
        histories = [()] * n if histories is None else histories
        if len(metas) != n or len(histories) != n:
            raise ValueError("metas and histories must have one entry per spectrum")
        vals.flags.writeable = False
        self._wavelength = wl
        self._values = vals
        self._names = tuple(str(x) for x in names)
        self._quantity = Quantity(quantity)
        self._metas = tuple(MappingProxyType(dict(m)) for m in metas)
        self._histories = tuple(tuple(h) for h in histories)

    @classmethod
    def from_spectra(cls, spectra: Sequence[Spectrum]) -> SpectralSet:
        if not spectra:
            raise ValueError("cannot build a SpectralSet from zero spectra")
        first = spectra[0]
        for s in spectra[1:]:
            if not np.array_equal(s.wavelength, first.wavelength):
                raise ValueError(
                    f"spectrum {s.name!r} is not on the same wavelength grid as "
                    f"{first.name!r}; resample explicitly before building a set"
                )
            if s.quantity != first.quantity:
                raise ValueError(
                    f"spectrum {s.name!r} is {s.quantity.value}, expected {first.quantity.value}"
                )
        return cls(
            first.wavelength,
            np.vstack([s.values for s in spectra]),
            [s.name for s in spectra],
            quantity=first.quantity,
            metas=[s.meta for s in spectra],
            histories=[s.history for s in spectra],
        )

    @property
    def wavelength(self) -> FloatArray:
        return self._wavelength

    @property
    def values(self) -> FloatArray:
        return self._values

    @property
    def names(self) -> tuple[str, ...]:
        return self._names

    @property
    def quantity(self) -> Quantity:
        return self._quantity

    def __len__(self) -> int:
        return int(self._values.shape[0])

    def __getitem__(self, index: int) -> Spectrum:  # type: ignore[override]
        if not isinstance(index, int | np.integer):
            raise TypeError("SpectralSet indices must be integers")
        i = int(index)
        return Spectrum(
            wavelength=self._wavelength,
            values=self._values[i],
            name=self._names[i],
            quantity=self._quantity,
            meta=self._metas[i],
            history=self._histories[i],
        )

    def __iter__(self) -> Iterator[Spectrum]:
        for i in range(len(self)):
            yield self[i]

    def derive(
        self,
        step: ProcessingStep,
        *,
        values: ArrayLike,
        wavelength: ArrayLike | None = None,
        quantity: Quantity | None = None,
    ) -> SpectralSet:
        """Return a new set produced by ``step`` applied to every spectrum."""
        return SpectralSet(
            self._wavelength if wavelength is None else wavelength,
            values,
            self._names,
            quantity=self._quantity if quantity is None else quantity,
            metas=self._metas,
            histories=[(*h, step) for h in self._histories],
        )

    def __repr__(self) -> str:
        return (
            f"SpectralSet(n={len(self)}, quantity={self._quantity.value}, "
            f"bands={self._wavelength.size}, "
            f"range={self._wavelength[0]:g}-{self._wavelength[-1]:g} nm)"
        )
