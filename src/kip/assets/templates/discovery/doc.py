"""Discovery report -- small-molecule triage and a designed protein binder.

The files under input/ are examples in the formats the NVIDIA BioNeMo Agent
Toolkit's skills write: drug-discovery-pipeline results (GenMol molecules,
DiffDock docking confidence, Boltz-2 affinity) as CSV, ProteinMPNN designs as
FASTA, and a Boltz-2 co-folding model with its confidence JSON. Their values
are illustrative and the complex is a geometric stand-in, not a prediction:
replace them with your own run's files.
"""

from kip import *

report = run_document(__file__, subtitle="Hit triage and binder design")
hits = read_molecules("input/candidates.csv")      # id, smiles, docking_confidence, pic50, p_bind
designs = read_fasta("input/designs.fasta")        # target and ProteinMPNN designs
model = Structure.load("input/binder_complex.cif")  # target (A) with binder_01 (B)
scores = read_json("input/binder_confidence.json")  # Boltz-2 confidence summary

lead = hits.get("GM-002")
binder = designs["binder_01"]
pLDDT_binder = model.mean_plddt("B")


def meets_criteria(m):
    return m.pic50 >= pIC50_min and m.p_bind >= P_bind_min and m.qed >= QED_min


# %% text scope "Scope"
f"""
This report triages small molecules generated against the target and checks a
protein binder designed for it, using the drug-discovery and binder-design
workflows of the BioNeMo Agent Toolkit @src:bionemo. The example values in
input/ are illustrative; replace them with your own run.

The lead, {lead.name}, has a predicted pIC50 of @val:pIC50 (IC50 @val:IC50) and
passes every drug-likeness check. The designed binder co-folds with the target
at an interface confidence of @val:ipTM.
"""

# %% inputs criteria "Selection criteria"
pIC50_min = 6.0                  # predicted potency: sub-micromolar
P_bind_min = 0.7                 # predicted probability of binding
QED_min = 0.5                    # drug-likeness
ipTM_min = 0.8                   # interface confidence of the co-folded complex
pLDDT_min = 80                   # mean confidence of the binder chain
T = 298.15 * K                   # temperature for the free energy
R_gas = 8.314 * J / (mol * K)    # gas constant

# %% text chemistry "Small-molecule triage" section=1
"""
GenMol @src:genmol generated the candidates, DiffDock @src:diffdock docked
each one to the target, and Boltz-2 @src:boltz2 predicted its affinity as a
pIC50 and a probability of binding. QED @src:qed and the rule of five
@src:lipinski are computed here from each structure.
"""

# %% table candidates "Candidates, most potent first"
molecule_table(sorted(hits, key=lambda m: -m.pic50),
               "qed", "mass", "docking_confidence", "pic50", "p_bind",
               titles={"docking_confidence": "Docking conf.", "pic50": "pIC50", "p_bind": "P(bind)"},
               passes=meets_criteria,
               caption="Green rows meet every selection criterion.")

# %% draw lead_structure "Lead candidate"
lead

# %% calc lead_checks "Lead candidate checks" result=IC50,dG
pIC50 = lead.pic50
IC50 = 10 ** (-pIC50) * molar               # -> nM
dG = -R_gas * T * log(10) * pIC50           # -> kcal/mol
QED = lead.qed
MW = lead.mass                              # -> g/mol
logP = lead.logp
TPSA = lead.tpsa                            # -> angstrom**2
assert pIC50 >= pIC50_min, "Potency"
assert lead.p_bind >= P_bind_min, "Binding probability"
assert QED >= QED_min, "Drug-likeness"
assert MW <= 500 * g / mol, "Rule of five: mass"
assert logP <= 5, "Rule of five: logP"

# %% text binder_design "Binder design" section=1
"""
RFdiffusion @src:rfdiffusion generated the binder backbone, ProteinMPNN
@src:proteinmpnn designed sequences for it, and Boltz-2 co-folded each design
with the target. Confidence is coloured in the bands of @src:alphafold.
"""

# %% draw binder_sequence "Designed binder"
binder.listing(marks={"Interface": model.interface("B", "A")})

# %% table designs_table "ProteinMPNN designs"
Table([Column("name", "Design"), Column("length", "Length (aa)"),
       Column("mass", "Mass", unit="kDa"), Column("score", "ProteinMPNN score"),
       Column("identity", "Identity to binder_01", format="{:.0%}")],
      [(s.name, s.length, s.mass, s.score, s.identity(binder)) for s in designs[1:]])

# %% draw complex "Co-folded complex" caption="Target (A) and binder_01 (B), coloured by pLDDT."
model

# %% plot binder_plddt "Binder confidence by residue"
plot(model.residues("B"), model.plddt("B"), label="binder_01",
     xlabel="Residue", ylabel="pLDDT", ylim=(0, 100)).line(
     [1, len(binder)], [pLDDT_min, pLDDT_min], dash="dashed", label="Acceptance")

# %% calc binder_checks "Binder acceptance"
ipTM = scores.iptm
assert ipTM >= ipTM_min, "Interface confidence"
assert pLDDT_binder >= pLDDT_min, "Binder confidence"

# %% sources references "References"
Sources.load()
