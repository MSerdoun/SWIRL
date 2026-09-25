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
