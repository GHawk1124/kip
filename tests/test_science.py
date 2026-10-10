"""Chemistry and biology: the files discovery tools write, read and shown."""
import json
import math
import unicodedata

import pymupdf
import pytest
from typer.testing import CliRunner

from kip import (Molecule, Sequence, Structure, molecule_grid, molecule_table, read_a3m,
                 read_fasta, read_json, read_molecules, read_vcf, variant_table)
from kip.cli import app
from kip.doc import build
from kip.render import emit
from kip.render.pdf import compile_pdf
from kip.units import fmt_quantity, ureg

pytest.importorskip("rdkit")

PARACETAMOL = "CC(=O)Nc1ccc(O)cc1"


def pdf_text(doc):
    pdf = pymupdf.open(stream=compile_pdf(emit(doc)), filetype="pdf")
    return pdf, unicodedata.normalize("NFKC", "".join(p.get_text() for p in pdf))


# -- molecules -------------------------------------------------------------------

def test_a_molecule_has_descriptors_with_units():
    m = Molecule(PARACETAMOL, name="paracetamol")
    assert m.formula == "C8H9NO2" and str(m) == "paracetamol"
    assert m.mass.to("g/mol").magnitude == pytest.approx(151.165, abs=0.01)
    assert m.tpsa.units == ureg.angstrom ** 2 and m.tpsa.magnitude == pytest.approx(49.33, abs=0.01)
    assert (m.hbd, m.hba, m.rule_of_five) == (2, 2, 0) and 0 < m.qed < 1
    assert fmt_quantity(m.mass) == "151.2 g/mol"
    with pytest.raises(ValueError, match="not a valid SMILES"):
        Molecule("C1CC")
    with pytest.raises(AttributeError, match="no property 'pic50'"):
        m.pic50


def test_molecules_read_from_csv_sdf_smi_and_genmol_json(tmp_path):
    (tmp_path / "hits.csv").write_text("ID,SMILES,Docking confidence,pIC50\nA-1,CCO,0.5,6.2\n"
                                       f"A-2,{PARACETAMOL},-0.1,5\n", encoding="utf-8")
    hits = read_molecules(tmp_path / "hits.csv")
    assert [m.name for m in hits] == ["A-1", "A-2"]
    assert hits.get("A-1").docking_confidence == 0.5 and hits[1].pic50 == 5

    from rdkit import Chem
    from rdkit.Chem import AllChem
    writer = Chem.SDWriter(str(tmp_path / "poses.sdf"))
    for rank, confidence in ((1, 0.71), (2, -0.4)):
        mol = Chem.AddHs(Chem.MolFromSmiles(PARACETAMOL))
        AllChem.EmbedMolecule(mol, randomSeed=rank)
        mol.SetProp("_Name", f"rank{rank}")
        mol.SetProp("confidence", str(confidence))
        writer.write(mol)
    writer.close()
    poses = read_molecules(tmp_path / "poses.sdf")
    assert [(p.name, p.confidence) for p in poses] == [("rank1", 0.71), ("rank2", -0.4)]
    assert poses[0].formula == "C8H9NO2"  # explicit hydrogens of a pose do not change it

    (tmp_path / "genmol.json").write_text(json.dumps(
        {"status": "success", "molecules": [{"smiles": "CCN", "score": 0.41}]}), encoding="utf-8")
    assert read_molecules(tmp_path / "genmol.json")[0].score == 0.41
    (tmp_path / "list.smi").write_text("CCO ethanol\nCCC\n", encoding="utf-8")
    assert [m.name for m in read_molecules(tmp_path / "list.smi")] == ["ethanol", None]
    (tmp_path / "bad.csv").write_text("id,smiles\nx,C1CC\n", encoding="utf-8")
    with pytest.raises(ValueError, match="record 1: not a valid SMILES"):
        read_molecules(tmp_path / "bad.csv")


def test_a_structure_diagram_is_vector_at_the_bond_length_asked_for():
    m = Molecule("CCCCCCCCCC")
    svg, width, height = m.svg(bond=5.0)
    assert b"<text" not in svg and b"<path" in svg  # labels are outlines, not fonts
    assert f"width='{width:.3f}mm'".encode() in svg and height < width  # drawn landscape
    _, wider, _ = m.svg(bond=10.0)
    assert wider == pytest.approx(2 * width, rel=0.01)
    _, boxed_w, boxed_h = Molecule("c1ccc2ccccc2c1").svg(bond=10.0, box=(20, 10))
    assert boxed_w <= 20.001 and boxed_h <= 10.001


def test_a_table_draws_each_structure_to_one_scale(tmp_path):
    (tmp_path / "c.csv").write_text(f"id,smiles,pic50\nsmall,CCO,6.1\nlarge,{'C' * 30},7\n", encoding="utf-8")
    hits = read_molecules(tmp_path / "c.csv")
    table = molecule_table(hits, "mass", "pic50", passes=lambda m: m.pic50 > 6.5)
    bonds = {row[0].bond for row in table.rows}
    assert len(bonds) == 1 and table.highlight == {0: "fail", 1: "ok"}
    assert table.headers[:4] == ["Structure", "ID", "MW (g/mol)", "pic50"]
    assert [c.align for c in table.columns][:2] == ["center", "left"]
    assert table.raw_value(table.rows[0][0], table.columns[0]) == "CCO"


def test_molecules_render_in_draw_and_table_cells_and_kip_show(tmp_path):
    source = f'''from kip import *
lead = Molecule("{PARACETAMOL}", name="APAP", pic50=5.2)
# %% draw lead_structure "Lead"
lead
# %% table hits "Hits"
molecule_table([lead, Molecule("CCO", name="EtOH", pic50=3.0)], "qed", "pic50")
# %% draw series "Series"
molecule_grid([lead, Molecule("CCO", name="EtOH")], labels=lambda m: m.name)
# %% calc checks "Checks"
MW = lead.mass   # -> g/mol
IC50 = 10 ** (-lead.pic50) * molar   # -> uM
assert MW <= 500 * g / mol, "Rule of five: mass"
'''
    doc = build(source=source, path="doc.py")
    pdf, text = pdf_text(doc)
    assert "APAP" in text and "EtOH" in text and "6.31 μM" in text.replace("µ", "μ")
    assert len(pdf[0].get_drawings()) > 40  # the structures are drawn, as vectors
    path = tmp_path / "doc.py"
    path.write_text(source, encoding="utf-8")
    shown = CliRunner().invoke(app, ["show", str(path)]).output
    assert "IC50 = 6.31 μM" in shown.replace("µ", "μ")
    from kip.report import _value
    assert _value(doc.namespace["lead"]) == {"text": f"APAP {PARACETAMOL}, C8H9NO2, 151.2 g/mol"}
    assert _value(Sequence("MKV", "s"))["text"] == "s · 3 aa · 0.3765 kDa: MKV"


# -- sequences -------------------------------------------------------------------

def test_sequence_properties_follow_protparam_and_oligocalc():
    protein = Sequence("ACDEFGHIKLMNPQRSTVWY", "all20")
    assert protein.kind == "protein" and protein.mass.magnitude == pytest.approx(2395.7, abs=0.1)
    assert protein.extinction().to("1/(molar*cm)").magnitude == 5500 + 1490
    dna = Sequence("ATGGCCTAA")
    assert dna.kind == "dna" and dna.gc == pytest.approx(4 / 9)
    assert str(dna.translate()) == "MA*" and str(dna.translate(to_stop=True)) == "MA"
    assert str(Sequence("ATGC").reverse_complement()) == "GCAT"
    assert Sequence("ACDE").mutations(Sequence("ACGE")) == ["D3G"]
    assert Sequence("ACDE").identity(Sequence("ACGE")) == 0.75
    with pytest.raises(ValueError, match="J is not a protein letter"):
        Sequence("ACJ", kind="protein")
    with pytest.raises(ValueError, match="for a DNA or RNA sequence"):
        protein.gc


def test_fasta_headers_keep_their_scores(tmp_path):
    (tmp_path / "d.fasta").write_text(">target_A a target domain\nMKV\nLLE\n"
                                      ">T=0.1, sample=1, score=0.84, seq_recovery=0.42\nMKA\n",
                                      encoding="utf-8")
    seqs = read_fasta(tmp_path / "d.fasta")
    assert [s.name for s in seqs] == ["target_A", "seq2"]
    assert str(seqs["target_A"]) == "MKVLLE" and seqs["target_A"].description == "a target domain"
    assert seqs["seq2"].score == 0.84 and seqs[1].seq_recovery == 0.42
    with pytest.raises(KeyError, match="no sequence named 'x'"):
        seqs["x"]


def test_a_sequence_listing_is_set_on_the_rules_with_marked_positions():
    source = '''from kip import *
s = Sequence("MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQAPILSRVGDGTQDNLSGAEKAVQVKVKALPDAQFEVVHSLAKWKRQTLGQHDFSAGEGLYTHMKALRPDEDRLSPLHSVYVDQWDWERVMGDGERQFSTLKSTVEAIWAGIKATEAAVSEEFGLAPFLPDQIHFVHSQELLSRYPDLDAKGRERAIAKDLGAVFLVGIGGKLSDGHRHDVRAPDYDDWSTPSELGHAGLNGDILVWNPVLEDAFELSSMGIRVDADTLKHQLALTGDEDRLELEWHQALLRGEMPQTIGGGIGQSRLTMLLLQLPHIGQVQAGVWPAACRESVDALL", "long")
# %% draw seq "Sequence"
s.listing(marks={"Hotspot": [3, 4, 5], "Mutation": 70})
'''
    pdf, text = pdf_text(build(source=source, path="doc.py"))
    assert "Hotspot" in text and "Mutation" in text and "long · 330 aa" in text
    rows = [(s["origin"][1], s["text"]) for p in pdf for b in p.get_text("dict")["blocks"]
            for line in b.get("lines", []) for s in line["spans"] if "Mono" in s["font"]]
    assert rows and len({round(y, 2) for y, _ in rows}) >= 4  # several rows of groups
    for y, _ in rows:
        cells = (y * 25.4 / 72 - (279.4 % 5) / 2) / 5
        assert cells == pytest.approx(round(cells), abs=0.002)
    with pytest.raises(ValueError, match="outside 1-3"):
        Sequence("MKV").listing(marks={"x": [4]})


# -- structures --------------------------------------------------------------------

PDB = """\
ATOM      1  N   MET A   1      11.104   6.134  -6.504  1.00  0.91           N
ATOM      2  CA  MET A   1      11.639   6.071  -5.147  1.00  0.91           C
ATOM      3  CA  LYS A   2      13.420   8.000  -2.900  1.00  0.75           C
ATOM      4  CA  VAL A   3      15.900   9.100  -0.600  1.00  0.42           C
ATOM      5  CA  GLY B   1      20.000   9.000   0.000  1.00  0.88           C
ATOM      6  CA  SER B   2      23.500  10.000   1.000  1.00  0.88           C
HETATM    7  C1  LIG B 101      18.000   8.000  -1.000  1.00  0.50           C
HETATM    8  O1  LIG B 101      18.900   8.700  -1.600  1.00  0.50           O
HETATM    9  O   HOH B 201      30.000  30.000  30.000  1.00  0.00           O
END
"""


def test_a_pdb_model_reads_chains_sequence_confidence_and_ligands():
    s = Structure.parse(PDB, name="m")
    assert s.chains == ["A", "B"] and str(s.sequence("A")) == "MKV"
    assert s.plddt("A") == pytest.approx([91, 75, 42])  # a 0-1 scale reads as 0-100
    assert s.ligands == ["LIG B:101"] and s.residues("B") == [1, 2]
    assert s.interface("A", "B", cutoff=5.0) == [3]
    with pytest.raises(ValueError, match="give chain=, one of A, B"):
        s.sequence()


def test_rmsd_is_zero_for_a_moved_copy_and_measures_a_change():
    import numpy as np
    s = Structure.load("src/kip/assets/templates/discovery/input/binder_complex.cif")
    turn = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]], dtype=float)
    moved = Structure.parse("\n".join(
        f"ATOM  {i:5d}  CA  ALA {a.chain}{a.resseq:4d}    "
        + "".join(f"{v:8.3f}" for v in (turn @ np.array(a.xyz) + 5.0)) + "  1.00 90.00           C"
        for i, a in enumerate(s.atoms, start=1)))
    assert s.rmsd(moved, chain="B").to("angstrom").magnitude == pytest.approx(0, abs=1e-3)
    assert s.chains == ["A", "B"] and len(s.residues("A")) == 54 and len(s.residues("B")) == 60
    assert s.looks_predicted() and 85 < s.mean_plddt("B") < 100


def test_mmcif_values_in_quotes_are_read():
    cif = """data_x
loop_
_atom_site.group_PDB
_atom_site.type_symbol
_atom_site.label_atom_id
_atom_site.label_comp_id
_atom_site.label_asym_id
_atom_site.label_seq_id
_atom_site.Cartn_x
_atom_site.Cartn_y
_atom_site.Cartn_z
_atom_site.B_iso_or_equiv
ATOM C "C4'" DA A 1 0.0 0.0 0.0 80.0
ATOM C "C4'" DG A 2 6.0 0.0 0.0 82.0
ATOM C 'C4\'' DC A 3 12.0 0.0 0.0 84.0
#
"""
    s = Structure.parse(cif, format="cif")
    assert str(s.sequence()) == "AGC" and s.sequence().kind == "dna"


def test_a_structure_draws_its_backbone_with_a_legend_and_the_file(tmp_path):
    source = '''from kip import *
model = Structure.load("input/model.cif")
# %% draw complex "Complex"
model
# %% plot conf "Confidence"
plot(model.residues("B"), model.plddt("B"), xlabel="Residue", ylabel="pLDDT")
'''
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "model.cif").write_bytes(
        open("src/kip/assets/templates/discovery/input/binder_complex.cif", "rb").read())
    (tmp_path / "doc.py").write_text(source, encoding="utf-8")
    doc = build(source=source, path=tmp_path / "doc.py")
    drawing = doc.results["complex"].content
    assert b"Very high (pLDDT &gt; 90)" in drawing.svg and drawing.attachments.keys() == {"model.cif"}
    _, text = pdf_text(doc)
    assert "Open model.cif" in text and "(mm, 1:1)" not in text
    chains = Structure.load(tmp_path / "input" / "model.cif").drawing(color="chain").svg
    assert b"Chain A" in chains and b"Chain B" in chains


# -- alignments, variants, scores ----------------------------------------------------

def test_a3m_alignments_drop_insertions(tmp_path):
    (tmp_path / "q.a3m").write_text(">query\nMKVL\n>hit1\nMKaaVL\n>hit2\n-KV-\n", encoding="utf-8")
    msa = read_a3m(tmp_path / "q.a3m")
    assert msa.depth == 3 and str(msa.query) == "MKVL"
    assert msa.coverage() == pytest.approx([2 / 3, 1, 1, 2 / 3])
    assert msa.identity() == pytest.approx([1, 1, 1])


def test_vcf_records_and_their_table(tmp_path):
    (tmp_path / "calls.vcf").write_text(
        "##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1\n"
        "chr1\t1205\trs1\tA\tG\t50.5\tPASS\tDP=31;AF=0.48;DB\tGT\t0/1\n"
        "chr2\t88\t.\tCT\tC\t.\tLowQual\tDP=4\tGT\t1/1\n", encoding="utf-8")
    calls = read_vcf(tmp_path / "calls.vcf")
    assert calls[0]["info"] == {"DP": 31, "AF": 0.48, "DB": True}
    assert calls[1]["qual"] is None and calls[1]["samples"]["S1"] == {"GT": "1/1"}
    table = variant_table(calls, "DP", titles={"DP": "Depth"})
    assert table.headers[-1] == "Depth" and table.rows[1][2] == "-"


def test_json_scores_read_as_attributes(tmp_path):
    (tmp_path / "s.json").write_text('{"iptm": 0.84, "chains": {"B": {"ptm": 0.9}}}', encoding="utf-8")
    scores = read_json(tmp_path / "s.json")
    assert scores.iptm == 0.84 and scores.chains.B.ptm == 0.9
    with pytest.raises(AttributeError, match="no 'ptm' in this record; it has iptm, chains"):
        scores.ptm
    (tmp_path / "bad.json").write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="bad.json:1: not valid JSON"):
        read_json(tmp_path / "bad.json")


# -- units and the worked example ----------------------------------------------------

def test_laboratory_units_print_as_a_laboratory_writes_them():
    from kip import Da, angstrom, kcal, mol, mL, molar, ng, nM, uL, uM
    assert fmt_quantity(2.5 * uM) == "2.5 μM" and fmt_quantity((50 * nM).to(molar)) == "5×10⁻⁸ M"
    assert fmt_quantity(3 * ng / mL) == "3 ng/mL" and fmt_quantity(5 * uL) == "5 μL"
    assert fmt_quantity(1.5 * angstrom) == "1.5 Å" and fmt_quantity(-9.7 * kcal / mol) == "-9.7 kcal/mol"
    assert fmt_quantity(6.8 * Da * 1000) == "6800 Da"


def test_negative_leading_factor_reads_without_brackets():
    doc = build(source='''from kip import *
# %% inputs g
R_gas = 8.314 * J / (mol * K)
T = 298.15 * K
# %% calc c
dG = -R_gas * T * log(10) * 7.1   # -> kcal/mol
''', path="doc.py")
    row = doc.results["c"].equations[0].wide()
    assert '= -R_"gas" dot T dot ln(10) dot 7.1 = -(8.314 thin "J/(mol·K)") dot 298.15' in row


def test_the_discovery_template_builds_and_its_checks_pass(tmp_path):
    from kip.scaffold import create_project
    root = tmp_path / "report"
    create_project(root, template="discovery")
    assert (root / "input" / "candidates.csv").exists()
    assert "kip[chem]" in (root / "pyproject.toml").read_text(encoding="utf-8")
    result = CliRunner().invoke(app, ["check", str(root / "doc.py")])
    assert result.exit_code == 0, result.output
    assert "checks 7 passed" in result.output and "error" not in result.output
