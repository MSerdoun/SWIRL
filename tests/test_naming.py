import pytest
from pydantic import ValidationError

from swirl.drillhole import assign_hole_depth, clear_hole_depth, holes, summarize_assignments
from swirl.naming import NamingExample, apply_rules, infer_rules, tokenize
from swirl.sampletable import (
    SampleTableError,
    TableMapping,
    guess_mapping,
    match_table,
    read_sample_table,
)
from swirl.synthetic.drillhole import synthetic_named_samples


def ex(name, hole, depth):
    h, d = name.index(hole), name.rindex(depth)
    return NamingExample(name=name, hole=(h, h + len(hole)), depth=(d, d + len(depth)))


@pytest.fixture(scope="module")
def named():
    return synthetic_named_samples()


def test_tokenize():
    assert [t.text for t in tokenize("SYN_02_354.5")] == ["SYN", "_", "02", "_", "354", ".", "5"]
    assert [t.kind for t in tokenize("DDH-12A")] == ["alpha", "sep", "digit", "alpha"]


def test_example_validation():
    with pytest.raises(ValidationError, match="not a number"):
        NamingExample(name="SYN_02_354", hole=(7, 10), depth=(0, 3))
    with pytest.raises(ValidationError, match="overlap"):
        NamingExample(name="SYN_02_354", hole=(0, 8), depth=(7, 10))
    with pytest.raises(ValidationError, match="outside"):
        NamingExample(name="SYN_02_354", hole=(0, 6), depth=(7, 30))


def test_one_example_reads_every_synthetic_sample(named):
    spectra, _ = named
    names = [s.name for s in spectra]
    inference = infer_rules([ex("SYN_02_354", "SYN_02", "354")], names)
    assert inference.single and "hole" in inference.rules[0].description
    got = apply_rules(inference.rules, names)
    for s, g in zip(spectra, got, strict=True):
        if s.name == "WHITE_REF":
            assert g is None
        else:
            assert g == (s.meta["synthetic_true_hole"], s.meta["synthetic_true_depth"])


def test_second_example_makes_the_rule_explicit(named):
    spectra, _ = named
    names = [s.name for s in spectra]
    examples = [ex("SYN_02_354", "SYN_02", "354"), ex("SYN_03_110_rep", "SYN_03", "110")]
    inference = infer_rules(examples, names)
    got = dict(zip(names, apply_rules(inference.rules, names), strict=True))
    assert got["SYN_03_110_rep"] == ("SYN_03", 110.0)
    assert got["SYN_02_301.5"] == ("SYN_02", 301.5)


@pytest.mark.parametrize(
    ("example", "names", "expected"),
    [
        (
            ("DDH-12A_354.5", "DDH-12A", "354.5"),
            ["DDH-7_12", "RC21-003 45.5", "SYN_02_354,25"],
            [("DDH-7", 12.0), ("RC21-003", 45.5), ("SYN_02", 354.25)],
        ),
        (("354_SYN02", "SYN02", "354"), ["12.5_SYN03", "7_ABC1"], [("SYN03", 12.5), ("ABC1", 7.0)]),
        (("ASD_DH1-044.txt", "DH1", "044"), ["ASD_DH2-120.txt"], [("DH2", 120.0)]),
        (("hole7 depth 12", "hole7", "12"), ["hole12 depth 3.5"], [("hole12", 3.5)]),
    ],
)
def test_various_name_structures(example, names, expected):
    inference = infer_rules([ex(*example)], [example[0], *names])
    assert apply_rules(inference.rules, names) == expected


def test_incompatible_examples_give_one_rule_each():
    names = ["SYN_02_354", "354-DDH7"]
    examples = [ex("SYN_02_354", "SYN_02", "354"), ex("354-DDH7", "DDH7", "354")]
    inference = infer_rules(examples, names)
    assert not inference.single and len(inference.rules) == 2
    assert apply_rules(inference.rules, names) == [("SYN_02", 354.0), ("DDH7", 354.0)]


def test_assign_clear_and_group(named):
    spectra, _ = named
    s = assign_hole_depth(spectra[0], "SYN_01", 0.0, source="name", rule="r")
    assert s.meta["hole_id"] == "SYN_01" and s.meta["depth_to"] == 0.0
    assert s.history[-1].name == "assign_hole_depth"
    assert holes([s])["SYN_01"][0].depth_from == 0.0
    c = clear_hole_depth(s)
    assert "hole_id" not in c.meta and c.history[-1].name == "clear_hole_depth"
    assert clear_hole_depth(spectra[0]) is spectra[0]


def test_summary_warnings():
    found = [("A", 1.0, 1.0), ("A", 2.0, 2.0), ("A", 2.0, 2.0), ("B", 5.0, 5.0), None]
    s = summarize_assignments(found)
    assert s["matched"] == 4 and s["unmatched"] == 1
    assert s["holes"][0] == {"hole_id": "A", "n": 3, "top": 1.0, "bottom": 2.0}
    assert any("single sample" in w for w in s["warnings"])
    assert any("same depth" in w for w in s["warnings"])


# --- sample tables -------------------------------------------------------------------------


def test_table_from_synthetic_set(named):
    spectra, text = named
    table = read_sample_table(text.encode(), "samples.csv")
    mapping = guess_mapping(table.columns)
    assert mapping == {"key": "SampleID", "hole": "HoleID", "depth_from": "From", "depth_to": "To"}
    report = match_table(table, TableMapping(**mapping), [s.name for s in spectra])
    names = [s.name for s in spectra]
    assert [names[i] for i in report.unmatched_spectra] == ["SYN_03_110_rep", "WHITE_REF"]
    assert sorted(report.unused_rows) == ["syn_01_999", "syn_04_12"]
    a = report.assignments[names.index("SYN_02_301.5")]
    assert (a.hole_id, a.depth_from, a.depth_to) == ("SYN_02", 301.5, 303.0)


def test_table_delimiters_decimal_comma_and_extensions():
    text = "Sample;Hole;Depth\nA.asd;DH1;12,5\nb;DH1;13\n;DH1;1\nc;;4\n"
    table = read_sample_table(text)
    m = TableMapping(**{**guess_mapping(table.columns), "depth_to": None})
    report = match_table(table, m, ["a", "B", "zz"])
    assert report.assignments[0].depth_from == 12.5 and report.assignments[0].depth_to == 12.5
    assert report.assignments[1].hole_id == "DH1"
    assert report.unmatched_spectra == [2] and report.bad_rows == ["c"]
    tsv = read_sample_table("id\tbhid\tfrom\tto\nx\tH\t1\t2\n")
    assert guess_mapping(tsv.columns)["hole"] == "bhid"


def test_table_errors():
    with pytest.raises(SampleTableError):
        read_sample_table("only a header\n")
    table = read_sample_table("a,b\n1,2\n")
    with pytest.raises(SampleTableError, match="not in the table"):
        match_table(table, TableMapping(key="a", hole="nope", depth_from="b"), ["x"])
