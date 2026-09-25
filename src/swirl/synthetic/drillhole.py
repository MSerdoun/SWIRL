"""A synthetic drill hole with a known alteration zonation, to develop and validate down-hole
views and interpretation against a known answer.

Each sample is a linear mixture of the end-members, with a composition set by depth zones
(blended linearly across ``transition`` metres at each zone boundary) plus a small random
jitter. The white-mica AlOH band centre drifts linearly with depth (a composition vector to
recover). A few samples are darkened (as wet or dark core would be) to exercise QC. Noise
and ASD splice steps are added as for the noisy end-members.

The truth travels with every spectrum in its metadata:
``synthetic_composition`` (end-member -> fraction), ``synthetic_aloh_center`` (nm) and
``synthetic_dark`` (bool).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Self

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from swirl.core import meta as mk
from swirl.core.spectrum import ProcessingStep, Spectrum
from swirl.synthetic import (
    EndMember,
    NoiseModel,
    SpliceOffsets,
    add_noise,
    apply_splice_offsets,
    default_grid,
    load_end_members,
    synthesize,
)


class Zone(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    top: float = Field(description="Top of the zone (m).")
    bottom: float = Field(description="Bottom of the zone (m).")
    composition: dict[str, float] = Field(description="End-member -> fraction (sums to 1).")

    @model_validator(mode="after")
    def _valid(self) -> Self:
        if self.bottom <= self.top:
            raise ValueError("zone bottom must be below its top")
        if any(v < 0 for v in self.composition.values()):
            raise ValueError("fractions must be non-negative")
        if not np.isclose(sum(self.composition.values()), 1.0):
            raise ValueError("fractions must sum to 1")
        return self


DEFAULT_ZONES = [
    Zone(top=0, bottom=60, composition={"white_mica": 0.85, "illite": 0.15}),
    Zone(top=60, bottom=110, composition={"illite": 0.8, "white_mica": 0.1, "chlorite": 0.1}),
    Zone(top=110, bottom=160, composition={"chlorite": 0.75, "illite": 0.25}),
    Zone(top=160, bottom=200, composition={"chlorite": 0.65, "hematite": 0.35}),
]


class DrillholeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    hole_id: str = Field("SYN-DH01", description="Hole identifier.")
    top: float = Field(0.0, description="Depth of the first sample (m).")
    bottom: float = Field(200.0, description="Depth below the last sample (m).")
    interval: float = Field(1.0, gt=0, description="Sample length (m).")
    zones: list[Zone] = Field(default=DEFAULT_ZONES, description="Alteration zones.")
    transition: float = Field(8.0, ge=0, description="Width of the blend at zone boundaries (m).")
    composition_jitter: float = Field(
        0.04, ge=0, description="Random perturbation of each fraction before renormalising."
    )
    aloh_center_top: float = Field(2196.0, description="White-mica AlOH centre at the top (nm).")
    aloh_center_bottom: float = Field(
        2214.0, description="White-mica AlOH centre at the bottom (nm)."
    )
    dark_samples: int = Field(3, ge=0, description="Number of darkened samples (QC test).")
    dark_factor: float = Field(0.06, gt=0, le=1, description="Albedo factor of dark samples.")
    noise: NoiseModel = Field(default_factory=NoiseModel)
    max_vnir_offset: float = Field(0.02, ge=0, description="Maximum ASD VNIR splice step.")
    max_swir2_offset: float = Field(0.015, ge=0, description="Maximum ASD SWIR2 splice step.")
    seed: int = Field(20260926, description="Random seed.")

    @model_validator(mode="after")
    def _valid(self) -> Self:
        if self.bottom <= self.top:
            raise ValueError("bottom must be below top")
        return self


def composition_at(depth: float, zones: list[Zone], transition: float) -> dict[str, float]:
    """Zone composition at ``depth``, blended linearly across each boundary."""
    zones = sorted(zones, key=lambda z: z.top)
    names = sorted({k for z in zones for k in z.composition})

    def vec(z: Zone) -> np.ndarray:
        return np.array([z.composition.get(n, 0.0) for n in names])

    idx = next((i for i, z in enumerate(zones) if z.top <= depth < z.bottom), None)
    if idx is None:
        idx = 0 if depth < zones[0].top else len(zones) - 1
    v = vec(zones[idx])
    half = transition / 2
    if half > 0:
        if idx > 0 and depth < zones[idx].top + half:
            t = 0.5 + (depth - zones[idx].top) / transition
            v = t * v + (1 - t) * vec(zones[idx - 1])
        elif idx < len(zones) - 1 and depth > zones[idx].bottom - half:
            t = 0.5 + (zones[idx].bottom - depth) / transition
            v = t * v + (1 - t) * vec(zones[idx + 1])
    return {n: float(x) for n, x in zip(names, v, strict=True) if x > 0}


def _with_aloh_center(em: EndMember, center: float) -> EndMember:
    feats = tuple(replace(b, center=center) if b.assignment == "AlOH" else b for b in em.features)
    return replace(em, features=feats)


def synthetic_drillhole(
    config: DrillholeConfig | None = None,
    end_members: Mapping[str, EndMember] | None = None,
) -> list[Spectrum]:
    """Generate the samples of a synthetic drill hole, top to bottom."""
    cfg = config or DrillholeConfig()
    ems = dict(load_end_members() if end_members is None else end_members)
    unknown = {k for z in cfg.zones for k in z.composition} - set(ems)
    if unknown:
        raise ValueError(f"unknown end-members in zones: {sorted(unknown)}")
    wl = default_grid()
    rng = np.random.default_rng(cfg.seed)
    n = round((cfg.bottom - cfg.top) / cfg.interval)
    dark = set(rng.choice(n, size=min(cfg.dark_samples, n), replace=False).tolist())
    fixed = {k: synthesize(em, wl).values for k, em in ems.items() if k != "white_mica"}

    samples = []
    for i in range(n):
        top = cfg.top + i * cfg.interval
        mid = top + cfg.interval / 2
        comp = composition_at(mid, cfg.zones, cfg.transition)
        keys = sorted(comp)
        w = np.array([comp[k] for k in keys])
        if cfg.composition_jitter:
            w = np.clip(w * (1 + cfg.composition_jitter * rng.standard_normal(w.size)), 0, None)
        w = w / w.sum()
        comp = {k: float(x) for k, x in zip(keys, w, strict=True)}
        frac = (mid - cfg.top) / (cfg.bottom - cfg.top)
        aloh = cfg.aloh_center_top + frac * (cfg.aloh_center_bottom - cfg.aloh_center_top)

        values = np.zeros(wl.size)
        for k, x in comp.items():
            if k == "white_mica":
                values += x * synthesize(_with_aloh_center(ems[k], aloh), wl).values
            else:
                values += x * fixed[k]
        is_dark = i in dark
        if is_dark:
            values = values * cfg.dark_factor

        name = f"{cfg.hole_id}_{top:06.1f}"
        clean = Spectrum(
            wavelength=wl,
            values=values,
            name=name,
            meta={
                mk.HOLE_ID: cfg.hole_id,
                mk.DEPTH_FROM: round(top, 6),
                mk.DEPTH_TO: round(top + cfg.interval, 6),
                mk.SAMPLE_ID: name,
                "synthetic": True,
                "synthetic_composition": comp,
                "synthetic_aloh_center": round(aloh, 4),
                "synthetic_dark": is_dark,
            },
            history=(
                ProcessingStep(
                    "synthesize_mixture",
                    {"composition": comp, "aloh_center": aloh, "dark": is_dark},
                ),
            ),
        )
        offsets = SpliceOffsets(
            vnir=float(rng.uniform(-cfg.max_vnir_offset, cfg.max_vnir_offset)),
            swir2=float(rng.uniform(-cfg.max_swir2_offset, cfg.max_swir2_offset)),
        )
        samples.append(apply_splice_offsets(add_noise(clean, rng, cfg.noise), offsets))
    return samples


# --- samples whose hole and depth are only in their names --------------------------------

NAMED_HOLES = (
    # hole id, top, bottom, interval (m); SYN_02 uses a 1.5 m interval, hence decimal depths.
    ("SYN_01", 0.0, 120.0, 3.0),
    ("SYN_02", 300.0, 360.0, 1.5),
    ("SYN_03", 50.0, 170.0, 3.0),
)


def _depth_text(depth: float) -> str:
    return f"{depth:g}"


def synthetic_named_samples(seed: int = 20260927) -> tuple[list[Spectrum], str]:
    """Samples of three synthetic holes named ``<hole>_<depth>`` (e.g. ``SYN_02_301.5``),
    without hole or depth metadata, plus the matching sample table (CSV text).

    Two traps are included: a replicate ``SYN_03_110_rep`` and a white reference
    ``WHITE_REF``, which carry no depth. The true hole and depth are kept in
    ``synthetic_true_hole`` / ``synthetic_true_depth`` for testing. The table lists every
    regular sample (not the traps) plus two samples that are not in the set.
    """
    spectra: list[Spectrum] = []
    rows = ["SampleID,HoleID,From,To"]
    for k, (hole, top, bottom, interval) in enumerate(NAMED_HOLES):
        cfg = DrillholeConfig(
            hole_id=hole, top=top, bottom=bottom, interval=interval, seed=seed + k, dark_samples=0
        )
        for s in synthetic_drillhole(cfg):
            depth = float(s.meta[mk.DEPTH_FROM])
            name = f"{hole}_{_depth_text(depth)}"
            meta = {
                key: v
                for key, v in s.meta.items()
                if key not in (mk.HOLE_ID, mk.DEPTH_FROM, mk.DEPTH_TO, mk.SAMPLE_ID)
            }
            meta.update({"synthetic_true_hole": hole, "synthetic_true_depth": depth})
            spectra.append(
                Spectrum(
                    wavelength=s.wavelength,
                    values=s.values,
                    name=name,
                    meta=meta,
                    history=s.history,
                )
            )
            rows.append(f"{name},{hole},{_depth_text(depth)},{_depth_text(depth + interval)}")
    base = next(s for s in spectra if s.name == "SYN_03_110")
    spectra.append(
        Spectrum(
            wavelength=base.wavelength,
            values=base.values * 1.01,
            name="SYN_03_110_rep",
            meta={**base.meta},
            history=base.history,
        )
    )
    wl = spectra[0].wavelength
    spectra.append(
        Spectrum(
            wavelength=wl,
            values=np.full(wl.size, 0.98),
            name="WHITE_REF",
            meta={"synthetic": True, "synthetic_true_hole": None, "synthetic_true_depth": None},
        )
    )
    rows += ["SYN_01_999,SYN_01,999,1002", "SYN_04_12,SYN_04,12,15"]
    return spectra, "\n".join(rows) + "\n"
