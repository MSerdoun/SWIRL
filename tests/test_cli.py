from swirl.cli import main


def test_info(synthetic_dir, capsys):
    assert main(["info", str(synthetic_dir / "illite_noisy.txt")]) == 0
    out = capsys.readouterr().out
    assert "2151 bands" in out and "apply_splice_offsets" in out


def test_info_reports_errors(tmp_path, capsys):
    bad = tmp_path / "bad.txt"
    bad.write_text("nothing here\n")
    assert main(["info", str(bad)]) == 1


def test_synth(tmp_path, capsys):
    assert main(["synth", str(tmp_path)]) == 0
    assert (tmp_path / "truth.json").exists()
    assert len(list(tmp_path.glob("*.txt"))) == 8


def test_ops(capsys):
    assert main(["ops", "smooth"]) == 0
    assert "window" in capsys.readouterr().out


def test_process_outdir_and_merge(tmp_path, synthetic_dir):
    recipe = tmp_path / "r.toml"
    recipe.write_text('[[steps]]\nop = "splice_correction"\n\n[[steps]]\nop = "smooth"\n')
    files = [str(synthetic_dir / f"{m}_noisy.txt") for m in ("illite", "chlorite")]
    assert main(["process", str(recipe), *files, "--outdir", str(tmp_path / "out")]) == 0
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == [
        "chlorite_noisy.csv",
        "illite_noisy.csv",
    ]
    merged = tmp_path / "all.csv"
    assert main(["process", str(recipe), *files, "--merge", str(merged)]) == 0
    from swirl import read

    assert [s.name for s in read(merged)] == ["illite_noisy", "chlorite_noisy"]


def test_qc_cli(tmp_path, synthetic_dir, capsys):
    f = str(synthetic_dir / "illite_noisy.txt")
    assert main(["qc", f]) == 0
    assert "splice_step" in capsys.readouterr().out
    assert main(["qc", f, "--strict"]) == 1
    cfg = tmp_path / "qc.toml"
    cfg.write_text("max_splice_step = 0.5\n")
    assert main(["qc", f, "--config", str(cfg), "--strict"]) == 0


def test_bands_cli(tmp_path, synthetic_dir):
    recipe = tmp_path / "r.toml"
    recipe.write_text('[[steps]]\nop = "continuum_removal"\nstart = 1300\nstop = 2500\n')
    cfg = tmp_path / "b.toml"
    cfg.write_text('position_method = "gaussian"\nratios = []\n')
    out = tmp_path / "bands.csv"
    f = str(synthetic_dir / "illite.txt")
    assert main(["bands", f, "--recipe", str(recipe), "--config", str(cfg), "--out", str(out)]) == 0
    assert "gaussian" in out.read_text()
