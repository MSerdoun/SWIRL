"""Command-line interface: ``swirl info | ops | process | qc | synth``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from swirl._version import __version__
from swirl.core.spectrum import SpectralSet, Spectrum
from swirl.io import read, write


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
                if not step_.name.startswith("read_") and step_.name != "synthesize":
                    print(f"    applied: {step_.name} {dict(step_.params)}")
    return status


def _cmd_synth(args: argparse.Namespace) -> int:
    from swirl.synthetic import SampleSetConfig, generate_sample_set

    truth = generate_sample_set(args.outdir, config=SampleSetConfig(seed=args.seed))
    print(f"wrote {len(truth['spectra'])} spectra and truth.json to {Path(args.outdir)}")
    return 0


def _cmd_ops(args: argparse.Namespace) -> int:
    from pydantic_core import PydanticUndefined

    from swirl.preprocess import get_operation, operations

    ops = [get_operation(n) for n in args.names] if args.names else operations()
    for op in ops:
        print(f"{op.name}: {op.summary}")
        for fname, f in op.params.model_fields.items():
            if f.default is not PydanticUndefined:
                default = repr(f.default)
            elif f.default_factory is not None:
                default = repr(f.default_factory())  # type: ignore[call-arg]
            else:
                default = "required"
            kind = str(f.annotation).replace("typing.", "")
            print(f"    {fname} [{kind}] = {default}\n        {f.description or ''}")
    return 0


def _read_all(files: Sequence[Path], fmt: str | None) -> list[tuple[Path, list[Spectrum]]]:
    return [(path, read(path, format=fmt)) for path in files]


def _cmd_process(args: argparse.Namespace) -> int:
    from swirl.preprocess import load_recipe

    recipe = load_recipe(args.recipe)
    inputs = _read_all(args.files, args.format)
    if args.merge is not None:
        out = recipe.run(SpectralSet.from_spectra([s for _, spectra in inputs for s in spectra]))
        args.merge.parent.mkdir(parents=True, exist_ok=True)
        write(out, args.merge)
        print(f"{len(out)} spectra -> {args.merge}")
        return 0
    if args.outdir is None:
        print("error: give --outdir or --merge", file=sys.stderr)
        return 2
    args.outdir.mkdir(parents=True, exist_ok=True)
    for path, spectra in inputs:
        target = args.outdir / f"{path.stem}.csv"
        write(recipe.run(spectra), target)
        print(f"{path} -> {target}")
    return 0


def _cmd_qc(args: argparse.Namespace) -> int:
    import tomllib

    from swirl.preprocess import QCParams, run_qc

    config = tomllib.loads(args.config.read_text(encoding="utf-8")) if args.config else {}
    params = QCParams.model_validate(config)
    header = (
        f"{'spectrum':<28} {'max':>7} {'mean':>7} {'NaN%':>6} {'noise':>8} {'splice':>7}  flags"
    )
    print(header)
    flagged = 0
    for path, spectra in _read_all(args.files, args.format):
        del path
        for r in run_qc(SpectralSet.from_spectra(spectra), params):
            m = r.metrics
            flagged += not r.ok
            print(
                f"{r.name[:28]:<28} {m['max_reflectance']:>7.3f} {m['mean_reflectance']:>7.3f} "
                f"{100 * m['nan_fraction']:>6.1f} {m['noise_rms']:>8.5f} "
                f"{m['max_splice_step']:>7.4f}  {', '.join(r.flags) or 'ok'}"
            )
    return 1 if args.strict and flagged else 0


def _cmd_app(args: argparse.Namespace) -> int:
    try:
        from swirl.app import launch
    except ImportError as exc:
        print(f"the app needs the 'app' extra (pip install swirl-spectra[app]): {exc}")
        return 2
    launch(host=args.host, port=args.port, open_browser=not args.no_browser)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="swirl", description=__doc__)
    parser.add_argument("--version", action="version", version=f"swirl {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    info = sub.add_parser("info", help="summarise the spectra in one or more files")
    info.add_argument("files", nargs="+", type=Path)
    info.add_argument("--format", default=None, help="force a format instead of the extension")
    info.set_defaults(func=_cmd_info)

    ops = sub.add_parser("ops", help="list processing operations and their parameters")
    ops.add_argument("names", nargs="*")
    ops.set_defaults(func=_cmd_ops)

    process = sub.add_parser("process", help="apply a recipe (TOML or JSON) to files")
    process.add_argument("recipe", type=Path)
    process.add_argument("files", nargs="+", type=Path)
    process.add_argument("--outdir", type=Path, help="write one processed file per input")
    process.add_argument("--merge", type=Path, help="process all spectra as one set, one file")
    process.add_argument("--format", default=None, help="force an input format")
    process.set_defaults(func=_cmd_process)

    qc = sub.add_parser("qc", help="quality-control report")
    qc.add_argument("files", nargs="+", type=Path)
    qc.add_argument("--config", type=Path, help="TOML file of QC thresholds")
    qc.add_argument("--format", default=None, help="force an input format")
    qc.add_argument("--strict", action="store_true", help="exit with 1 if anything is flagged")
    qc.set_defaults(func=_cmd_qc)

    app = sub.add_parser("app", help="start the graphical interface in the browser")
    app.add_argument("--host", default="127.0.0.1")
    app.add_argument("--port", type=int, default=8765)
    app.add_argument("--no-browser", action="store_true", help="do not open a browser")
    app.set_defaults(func=_cmd_app)

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
