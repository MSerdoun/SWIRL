"""Synthetic spectra with known ground truth, for development, tests and calibration.

End-members are defined in ``minerals.toml`` (continuum anchors + Gaussian absorption bands).
Everything is deterministic for a given seed, and the generating parameters are written next
to the spectra so any algorithm can be scored against what was put in.
"""

from __future__ import annotations

import json
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import ArrayLike
from scipy.interpolate import PchipInterpolator

from swirl.core.spectrum import FloatArray, ProcessingStep, Spectrum
from swirl.io.text import write_text

# ASD FieldSpec / TerraSpec detector boundaries (nm): VNIR ≤ 1000 < SWIR1 ≤ 1800 < SWIR2.
ASD_VNIR_END = 1000.0
ASD_SWIR1_END = 1800.0


@dataclass(frozen=True)
class Band:
    """A Gaussian absorption band, defined relative to the continuum."""

    center: float
    fwhm: float
    depth: float
    assignment: str = ""

    def __post_init__(self) -> None:
        if not 0.0 <= self.depth < 1.0:
            raise ValueError(f"band depth must be in [0, 1), got {self.depth}")
        if self.fwhm <= 0:
            raise ValueError(f"band fwhm must be positive, got {self.fwhm}")


@dataclass(frozen=True)
class EndMember:
    key: str
    label: str
    continuum: tuple[tuple[float, float], ...]
    features: tuple[Band, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "continuum": [list(p) for p in self.continuum],
            "features": [asdict(b) for b in self.features],
        }


@dataclass(frozen=True)
class NoiseModel:
    """Additive Gaussian noise whose sigma rises at both ends of the range (detector fall-off).

    sigma(λ) = base · (1 + low_boost · exp(-(λ - λmin)/low_scale)
                         + high_boost · exp((λ - λmax)/high_scale))
    """

    base: float = 0.0015
    low_boost: float = 4.0
    low_scale: float = 30.0
    high_boost: float = 3.0
    high_scale: float = 60.0

    def sigma(self, wavelength: FloatArray) -> FloatArray:
        lo, hi = wavelength[0], wavelength[-1]
        profile = (
            1.0
            + self.low_boost * np.exp(-(wavelength - lo) / self.low_scale)
            + self.high_boost * np.exp((wavelength - hi) / self.high_scale)
        )
        return np.asarray(self.base * profile, dtype=np.float64)


@dataclass(frozen=True)
class SpliceOffsets:
    """Relative steps applied to the ASD VNIR and SWIR2 detectors, SWIR1 being the reference."""

    vnir: float = 0.0
    swir2: float = 0.0


@dataclass(frozen=True)
class SampleSetConfig:
    seed: int = 20260925
    grid_start: float = 350.0
    grid_stop: float = 2500.0
    grid_step: float = 1.0
    noise: NoiseModel = field(default_factory=NoiseModel)
    max_vnir_offset: float = 0.02
    max_swir2_offset: float = 0.015


def default_grid(start: float = 350.0, stop: float = 2500.0, step: float = 1.0) -> FloatArray:
    n = round((stop - start) / step) + 1
    return np.asarray(start + step * np.arange(n), dtype=np.float64)


def load_end_members(path: str | Path | None = None) -> dict[str, EndMember]:
    """Load end-member definitions (the bundled ``minerals.toml`` by default)."""
    if path is None:
        raw = resources.files("swirl.synthetic").joinpath("minerals.toml").read_bytes()
    else:
        raw = Path(path).read_bytes()
    data = tomllib.loads(raw.decode("utf-8"))
    out = {}
    for key, entry in data.items():
        anchors = tuple((float(w), float(r)) for w, r in entry["continuum"])
        bands = tuple(
            Band(
                center=float(f["center"]),
                fwhm=float(f["fwhm"]),
                depth=float(f["depth"]),
                assignment=str(f.get("assignment", "")),
            )
            for f in entry.get("features", [])
        )
        out[key] = EndMember(
            key=key, label=str(entry.get("label", key)), continuum=anchors, features=bands
        )
    return out


def continuum(end_member: EndMember, wavelength: ArrayLike) -> FloatArray:
    wl = np.asarray(wavelength, dtype=np.float64)
    anchors = np.array(end_member.continuum, dtype=np.float64)
    interp = PchipInterpolator(anchors[:, 0], anchors[:, 1], extrapolate=True)
    return np.asarray(interp(wl), dtype=np.float64)


def band_profile(band: Band, wavelength: FloatArray) -> FloatArray:
    """Transmission factor of one band: 1 - depth · Gaussian."""
    g = np.exp(-4.0 * np.log(2.0) * (wavelength - band.center) ** 2 / band.fwhm**2)
    return np.asarray(1.0 - band.depth * g, dtype=np.float64)


def synthesize(end_member: EndMember, wavelength: ArrayLike | None = None) -> Spectrum:
    """Noise-free reflectance of an end-member."""
    wl = default_grid() if wavelength is None else np.asarray(wavelength, dtype=np.float64)
    values = continuum(end_member, wl)
    for band in end_member.features:
        values = values * band_profile(band, wl)
    return Spectrum(
        wavelength=wl,
        values=values,
        name=end_member.key,
        meta={"synthetic": True, "end_member": end_member.key, "label": end_member.label},
        history=(ProcessingStep("synthesize", {"end_member": end_member.to_dict()}),),
    )


def mix(spectra: Sequence[Spectrum], weights: Sequence[float], name: str) -> Spectrum:
    """Linear (areal) mixture of reflectance spectra on a common grid."""
    if len(spectra) != len(weights) or not spectra:
        raise ValueError("need one weight per spectrum")
    w = np.asarray(weights, dtype=np.float64)
    if np.any(w < 0) or not np.isclose(w.sum(), 1.0):
        raise ValueError("weights must be non-negative and sum to 1")
    wl = spectra[0].wavelength
    if any(not np.array_equal(s.wavelength, wl) for s in spectra[1:]):
        raise ValueError("spectra must share a wavelength grid")
    values = np.sum([wi * s.values for wi, s in zip(w, spectra, strict=True)], axis=0)
    parts = {s.name: float(wi) for s, wi in zip(spectra, w, strict=True)}
    return Spectrum(
        wavelength=wl,
        values=values,
        name=name,
        meta={"synthetic": True, "mixture": parts},
        history=(ProcessingStep("mix", {"weights": parts}),),
    )


def add_noise(spectrum: Spectrum, rng: np.random.Generator, noise: NoiseModel) -> Spectrum:
    sigma = noise.sigma(spectrum.wavelength)
    values = spectrum.values + rng.standard_normal(spectrum.n_bands) * sigma
    return spectrum.derive(ProcessingStep("add_noise", asdict(noise)), values=values)


def apply_splice_offsets(spectrum: Spectrum, offsets: SpliceOffsets) -> Spectrum:
    """Simulate ASD detector steps: scale VNIR and SWIR2 by (1 + offset)."""
    wl = spectrum.wavelength
    factor = np.ones_like(wl)
    factor[wl <= ASD_VNIR_END] += offsets.vnir
    factor[wl > ASD_SWIR1_END] += offsets.swir2
    return spectrum.derive(
        ProcessingStep("apply_splice_offsets", asdict(offsets)), values=spectrum.values * factor
    )


def generate_sample_set(
    outdir: str | Path,
    *,
    config: SampleSetConfig | None = None,
    end_members: Mapping[str, EndMember] | None = None,
) -> dict[str, Any]:
    """Write clean and noisy spectra of every end-member, plus ``truth.json``.

    Returns the ground truth that was written.
    """
    cfg = config or SampleSetConfig()
    ems = load_end_members() if end_members is None else end_members
    wl = default_grid(cfg.grid_start, cfg.grid_stop, cfg.grid_step)
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)

    truth: dict[str, Any] = {
        "seed": cfg.seed,
        "grid": {"start": cfg.grid_start, "stop": cfg.grid_stop, "step": cfg.grid_step},
        "noise": asdict(cfg.noise),
        "spectra": {},
    }
    for index, (key, em) in enumerate(sorted(ems.items())):
        clean = synthesize(em, wl)
        rng = np.random.default_rng([cfg.seed, index])
        offsets = SpliceOffsets(
            vnir=float(rng.uniform(-cfg.max_vnir_offset, cfg.max_vnir_offset)),
            swir2=float(rng.uniform(-cfg.max_swir2_offset, cfg.max_swir2_offset)),
        )
        noisy = apply_splice_offsets(add_noise(clean, rng, cfg.noise), offsets)
        noisy = Spectrum(
            wavelength=noisy.wavelength,
            values=noisy.values,
            name=f"{key}_noisy",
            meta={**noisy.meta, "seed": [cfg.seed, index]},
            history=noisy.history,
        )
        write_text([clean], out / f"{key}.txt")
        write_text([noisy], out / f"{key}_noisy.txt")
        truth["spectra"][key] = {**em.to_dict(), "file": f"{key}.txt"}
        truth["spectra"][f"{key}_noisy"] = {
            **em.to_dict(),
            "file": f"{key}_noisy.txt",
            "seed": [cfg.seed, index],
            "splice_offsets": asdict(offsets),
        }
    (out / "truth.json").write_text(json.dumps(truth, indent=2) + "\n", encoding="utf-8")
    return truth


__all__ = [
    "ASD_SWIR1_END",
    "ASD_VNIR_END",
    "Band",
    "EndMember",
    "NoiseModel",
    "SampleSetConfig",
    "SpliceOffsets",
    "add_noise",
    "apply_splice_offsets",
    "band_profile",
    "continuum",
    "default_grid",
    "generate_sample_set",
    "load_end_members",
    "mix",
    "synthesize",
]
