"""Command-line interface: ``swirl info`` and ``swirl synth``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from swirl._version import __version__
from swirl.io import read


def _cmd_info(args: argparse.Namespace) -> int:
    status = 0
    for path in args.files:
        try:
            spectra = read(path, format=args.format)
        except (OSError, ValueError) as exc:
            print(f"{path}: ERROR {exc}", file=sys.stderr)
            status = 1
            continue
        print(f"{path}: {len(spectra)} spectrum(s)")
        for s in spectra:
            steps = np.diff(s.wavelength)
            step = f"{steps[0]:g} nm" if np.allclose(steps, steps[0]) else "irregular"
            finite = s.values[np.isfinite(s.values)]
            vrange = f"{finite.min():.4f}-{finite.max():.4f}" if finite.size else "all NaN"
            print(
                f"  {s.name}: {s.quantity.value}, {s.n_bands} bands, "
                f"{s.wavelength[0]:g}-{s.wavelength[-1]:g} nm, step {step}, values {vrange}"
            )
            for step_ in s.history:
                if step_.name not in ("read_text", "synthesize"):
                    print(f"    applied: {step_.name} {dict(step_.params)}")
    return status


def _cmd_synth(args: argparse.Namespace) -> int:
    from swirl.synthetic import SampleSetConfig, generate_sample_set

    truth = generate_sample_set(args.outdir, config=SampleSetConfig(seed=args.seed))
    print(f"wrote {len(truth['spectra'])} spectra and truth.json to {Path(args.outdir)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="swirl", description=__doc__)
    parser.add_argument("--version", action="version", version=f"swirl {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    info = sub.add_parser("info", help="summarise the spectra in one or more files")
    info.add_argument("files", nargs="+", type=Path)
    info.add_argument("--format", default=None, help="force a format instead of the extension")
    info.set_defaults(func=_cmd_info)

    synth = sub.add_parser("synth", help="write the synthetic end-member sample set")
    synth.add_argument("outdir", type=Path)
    synth.add_argument("--seed", type=int, default=20260925)
    synth.set_defaults(func=_cmd_synth)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
