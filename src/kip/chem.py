"""Molecules: structure diagrams, properties, and the files discovery tools write.

A :class:`Molecule` comes from SMILES or an SDF/MOL record; :func:`read_molecules`
reads the lists generative chemistry, docking and affinity models produce --
SDF poses with their scores, SMILES files, CSV or JSON results. Properties with
units are quantities (``mass`` in g/mol, ``tpsa`` in Å²), so a calc cell checks
them like any other value::

    # %% calc lead "Lead candidate"
    MW = lead.mass                         # -> g/mol
    assert MW <= 500 * g / mol, "Lipinski: molecular weight"

A draw cell whose last expression is a molecule shows its structure diagram,
and a molecule in a table cell shows its diagram in the cell. Diagrams follow
the ACS 1996 style and are vector, like everything else kip draws.

Needs RDKit: ``uv add rdkit`` (or install ``kip[chem]``).
"""
from __future__ import annotations

import csv
import json
import re

from .units import ureg

__all__ = ["Molecule", "Molecules", "read_molecules", "molecule_grid", "molecule_table"]

#: Printed bond length (mm): ACS 1996 for figures, smaller in a table cell.
FIGURE_BOND = 5.08
CELL_BOND = 3.0
#: The largest diagram a table cell holds (mm); larger molecules are drawn smaller.
CELL_BOX = (40.0, 20.0)
MIN_CELL_BOND = 1.6
#: RDKit draws an ACS 1996 bond this many SVG units long.
_ACS_BOND = 14.4

#: Column titles for the descriptors a :class:`Molecule` computes.
TITLES = {"name": "ID", "smiles": "SMILES", "formula": "Formula", "mass": "MW",
          "logp": "logP", "tpsa": "TPSA", "hbd": "HBD", "hba": "HBA", "qed": "QED",
          "rotatable_bonds": "Rot. bonds", "heavy_atoms": "Heavy atoms",
          "rule_of_five": "Ro5 violations"}
#: Descriptors with units: the unit a table column shows them in, and how pint spells it.
_UNITS = {"mass": ("g/mol", "g/mol"), "exact_mass": ("g/mol", "g/mol"), "tpsa": ("Å²", "angstrom**2")}


def _rdkit():
    try:
        from rdkit import Chem, RDLogger
    except ImportError as exc:
        raise ImportError("molecules need RDKit: run `uv add rdkit` in this project "
                          "(or install kip[chem])") from exc
    RDLogger.DisableLog("rdApp.*")
    return Chem


def _number(text):
    """An SD tag or CSV cell as the number it holds, else the text."""
    if not isinstance(text, str):
        return text
    stripped = text.strip()
    for kind in (int, float):
        try:
            return kind(stripped)
        except ValueError:
            pass
    return stripped


def _landscape(mol) -> None:
    """Turn a 2D depiction to its widest, flattest orientation.

    Only multiples of 30° are tried, so bonds keep the standard angles a
    depiction is drawn at, and only rotations, so stereo wedges keep their sense.
    """
    import math
    from rdkit.Geometry import Point3D

    if mol.GetNumAtoms() < 3:
        return
    conf = mol.GetConformer()
    points = [(p.x, p.y) for p in (conf.GetAtomPosition(i) for i in range(mol.GetNumAtoms()))]

    def turned(angle):
        c, s = math.cos(angle), math.sin(angle)
        return [(x * c - y * s, x * s + y * c) for x, y in points]

    def flatness(angle):
        xs, ys = zip(*turned(angle))
        return (max(ys) - min(ys)) / max(max(xs) - min(xs), 1e-6)

    best = min((math.radians(30 * k) for k in range(6)), key=lambda a: (round(flatness(a), 3), a))
    if best:
        for i, (x, y) in enumerate(turned(best)):
            conf.SetAtomPosition(i, Point3D(x, y, 0.0))


class Diagram:
    """A molecule drawn at a given bond length, as one cell of a table."""

    def __init__(self, molecule: "Molecule", bond: float):
        self.molecule, self.bond = molecule, bond

    @property
    def smiles(self) -> str:
        return self.molecule.smiles

    def __str__(self) -> str:
        return str(self.molecule)

    def kip_image(self) -> tuple[bytes, float, float]:
        return self.molecule.svg(bond=self.bond, box=CELL_BOX)


class Molecule:
    """One molecule, its properties, and its structure diagram.

    ``Molecule("CC(=O)Nc1ccc(O)cc1", name="paracetamol", pic50=5.2)``. Keyword
    arguments, SD tags and CSV columns become properties, read as attributes
    (``lead.pic50``) or items (``lead["pic50"]``).
    """

    def __init__(self, structure, name: str | None = None, **properties):
        Chem = _rdkit()
        if isinstance(structure, str):
            mol = Chem.MolFromSmiles(structure.strip())
            if mol is None:
                raise ValueError(f"not a valid SMILES string: {structure!r}")
        elif isinstance(structure, Chem.Mol):
            mol = structure
        else:
            raise TypeError(f"a Molecule is made from SMILES or an RDKit Mol, not {type(structure).__name__}")
        self.mol = mol
        if name is None and mol.HasProp("_Name") and mol.GetProp("_Name").strip():
            name = mol.GetProp("_Name").strip()
        self.name = name
        self.properties = {k: _number(v) for k, v in properties.items()}

    @classmethod
    def load(cls, path, **properties) -> "Molecule":
        """The first molecule in an SDF or MOL file."""
        molecules = read_molecules(path)
        if not molecules:
            raise ValueError(f"{path}: no molecule could be read")
        first = molecules[0]
        first.properties.update(properties)
        return first

    # -- identity -----------------------------------------------------------

    @property
    def smiles(self) -> str:
        return _rdkit().MolToSmiles(self.mol)

    @property
    def formula(self) -> str:
        from rdkit.Chem import rdMolDescriptors
        return rdMolDescriptors.CalcMolFormula(self.mol)

    def __str__(self) -> str:
        return self.name or self.smiles

    def __repr__(self) -> str:
        return f"Molecule({self.smiles!r}" + (f", name={self.name!r})" if self.name else ")")

    def __getitem__(self, key):
        return self.properties[key]

    def __getattr__(self, key):
        properties = self.__dict__.get("properties", {})
        if key in properties:
            return properties[key]
        raise AttributeError(f"{type(self).__name__} has no property {key!r}"
                             + (f"; it has {', '.join(sorted(properties))}" if properties else ""))

    # -- descriptors ----------------------------------------------------------

    @property
    def mass(self):
        """Average molecular weight, in g/mol."""
        from rdkit.Chem import Descriptors
        return Descriptors.MolWt(self.mol) * ureg.g / ureg.mol

    @property
    def exact_mass(self):
        """Monoisotopic mass, in g/mol."""
        from rdkit.Chem import Descriptors
        return Descriptors.ExactMolWt(self.mol) * ureg.g / ureg.mol

    @property
    def logp(self) -> float:
        """Crippen's estimate of the octanol-water partition coefficient."""
        from rdkit.Chem import Crippen
        return Crippen.MolLogP(self.mol)

    @property
    def tpsa(self):
        """Topological polar surface area, in Å²."""
        from rdkit.Chem import rdMolDescriptors
        return rdMolDescriptors.CalcTPSA(self.mol) * ureg.angstrom ** 2

    @property
    def hbd(self) -> int:
        from rdkit.Chem import Lipinski
        return Lipinski.NumHDonors(self.mol)

    @property
    def hba(self) -> int:
        from rdkit.Chem import Lipinski
        return Lipinski.NumHAcceptors(self.mol)

    @property
    def rotatable_bonds(self) -> int:
        from rdkit.Chem import Lipinski
        return Lipinski.NumRotatableBonds(self.mol)

    @property
    def heavy_atoms(self) -> int:
        return self.mol.GetNumHeavyAtoms()

    @property
    def qed(self) -> float:
        """Quantitative estimate of drug-likeness, 0 to 1."""
        from rdkit.Chem import QED
        return QED.qed(self.mol)

    @property
    def rule_of_five(self) -> int:
        """How many of Lipinski's four limits the molecule exceeds."""
        return sum((self.mass.magnitude > 500, self.logp > 5, self.hbd > 5, self.hba > 10))

    # -- diagrams -----------------------------------------------------------------

    def svg(self, *, bond: float = FIGURE_BOND, highlight: str | None = None,
            box: tuple[float, float] | None = None) -> tuple[bytes, float, float]:
        """The structure diagram as SVG, and its printed width and height in mm.

        ``bond`` is the printed bond length; ``box`` (width, height) draws a
        larger molecule smaller so it fits. ``highlight`` is a SMARTS pattern
        whose atoms and bonds are marked, such as a scaffold.
        """
        Chem = _rdkit()
        from rdkit.Chem import Draw, rdDepictor
        from rdkit.Chem.Draw import rdMolDraw2D

        mol = Chem.RemoveHs(self.mol, sanitize=False)  # a copy, so the pose keeps its coordinates
        rdDepictor.SetPreferCoordGen(True)
        rdDepictor.Compute2DCoords(mol)  # a docked pose's 3D coordinates are not a diagram
        _landscape(mol)
        atoms, bonds = [], []
        if highlight:
            pattern = Chem.MolFromSmarts(highlight)
            if pattern is None:
                raise ValueError(f"not a valid SMARTS pattern: {highlight!r}")
            for match in mol.GetSubstructMatches(pattern):
                atoms.extend(match)
                bonds.extend(b.GetIdx() for b in mol.GetBonds()
                             if b.GetBeginAtomIdx() in match and b.GetEndAtomIdx() in match)
        drawer = rdMolDraw2D.MolDraw2DSVG(-1, -1)
        options = drawer.drawOptions()
        Draw.SetACS1996Mode(options, Draw.MeanBondLength(mol) or 1.0)
        options.clearBackground = False
        if atoms:
            options.setHighlightColour((0.95, 0.75, 0.3, 0.6))
            drawer.DrawMolecule(mol, highlightAtoms=sorted(set(atoms)), highlightBonds=sorted(set(bonds)))
        else:
            drawer.DrawMolecule(mol)
        drawer.FinishDrawing()
        text = drawer.GetDrawingText()
        size = re.search(r"width='([\d.]+)px' height='([\d.]+)px'", text)
        units_w, units_h = float(size[1]), float(size[2])
        scale = bond / _ACS_BOND
        if box is not None:
            scale = min(scale, box[0] / units_w, box[1] / units_h)
        width, height = units_w * scale, units_h * scale
        text = text.replace(size[0], f"width='{width:.3f}mm' height='{height:.3f}mm'", 1)
        text = re.sub(r"^<\?xml[^>]*\?>\s*", "", text)
        return text.encode("utf-8"), width, height

    def drawing(self, *, caption: str | None = None, highlight: str | None = None,
                bond: float = FIGURE_BOND):
        """A :class:`~kip.content.Drawing` of the structure, for a draw cell."""
        from .content import Drawing
        svg, width, height = self.svg(bond=bond, highlight=highlight)
        return Drawing(svg=svg, width=width, caption=caption)

    def kip_image(self) -> tuple[bytes, float, float]:
        """The diagram a table cell shows."""
        return self.svg(bond=CELL_BOND, box=CELL_BOX)

    def kip_content(self, kind: str):
        return self.drawing() if kind == "draw" else None

    def kip_summary(self) -> str:
        from .units import fmt_quantity
        named = f"{self.name} " if self.name else ""
        return f"{named}{self.smiles}, {self.formula}, {fmt_quantity(self.mass)}"


class Molecules(list):
    """Molecules read from one file, in file order, with a table and a grid view."""

    def kip_summary(self) -> str:
        return f"{len(self)} molecule{'s' if len(self) != 1 else ''}"

    def table(self, *keys: str, structure: bool = True, titles: dict | None = None,
              passes=None, **options):
        return molecule_table(self, *keys, structure=structure, titles=titles,
                              passes=passes, **options)

    def grid(self, **options):
        return molecule_grid(self, **options)

    def get(self, name: str) -> Molecule:
        """The molecule called ``name``."""
        for molecule in self:
            if molecule.name == name:
                return molecule
        raise KeyError(f"no molecule named {name!r}; names are "
                       + ", ".join(str(m.name) for m in self[:8]) + ("..." if len(self) > 8 else ""))


def _column(row: dict, wanted: str | None, candidates: tuple[str, ...]) -> str | None:
    lower = {k.lower(): k for k in row}
    if wanted is not None:
        if wanted not in row:
            raise ValueError(f"no {wanted!r} column; columns are {', '.join(row)}")
        return wanted
    return next((lower[c] for c in candidates if c in lower), None)


def _from_records(records: list[dict], smiles: str | None, name: str | None, path) -> Molecules:
    if not records:
        return Molecules()
    smiles = _column(records[0], smiles, ("smiles", "canonical_smiles", "ligand", "molecule", "smi"))
    if smiles is None:
        raise ValueError(f"{path}: no SMILES column; name it with smiles=\"...\"")
    name = _column(records[0], name, ("id", "name", "title", "compound", "compound_id", "mol_id"))
    out = Molecules()
    for i, record in enumerate(records, start=1):
        properties = {k: v for k, v in record.items() if k not in (smiles, name)}
        try:
            out.append(Molecule(record[smiles], name=str(record[name] or "") or None if name else None,
                                **{_identifier(k): v for k, v in properties.items()}))
        except ValueError as exc:
            raise ValueError(f"{path}: record {i}: {exc}") from None
    return out


def _identifier(key: str) -> str:
    """A column title as an attribute name: "Docking confidence" is docking_confidence."""
    text = re.sub(r"\W+", "_", key.strip()).strip("_").lower()
    return text if text and not text[0].isdigit() else f"_{text}"


def read_molecules(path, *, smiles: str | None = None, name: str | None = None) -> Molecules:
    """Every molecule in an SDF, SMILES, CSV or JSON file, with its properties.

    - ``.sdf`` / ``.mol``: each record's SD tags become properties -- a docking
      pose file keeps its confidence or score.
    - ``.smi``: one ``SMILES name`` per line.
    - ``.csv`` / ``.tsv``: a SMILES column (``smiles``, or name it) and an
      optional id column; every other column is a property.
    - ``.json``: a list of records, or an object holding one -- GenMol's
      ``{"molecules": [{"smiles": ..., "score": ...}]}`` reads as it is.

    Column names become attribute names: "Docking confidence" is read as
    ``m.docking_confidence``.
    """
    from .authoring import project_path
    path = project_path(path)
    Chem = _rdkit()
    suffix = path.suffix.lower()
    if suffix in (".sdf", ".mol", ".sd"):
        out = Molecules()
        supplier = Chem.SDMolSupplier(str(path), removeHs=False)
        for i, mol in enumerate(supplier, start=1):
            if mol is None:
                raise ValueError(f"{path}: record {i} is not a valid molecule")
            props = {_identifier(k): mol.GetProp(k) for k in mol.GetPropNames()}
            out.append(Molecule(mol, **props))
        return out
    if suffix in (".smi", ".smiles"):
        records = []
        for line in path.read_text(encoding="utf-8").splitlines():
            parts = line.split(None, 1)
            if parts and not parts[0].startswith("#"):
                records.append({"smiles": parts[0], "id": parts[1].strip() if len(parts) > 1 else ""})
        return _from_records(records, "smiles", "id" if any(r["id"] for r in records) else None, path)
    if suffix in (".csv", ".tsv"):
        with path.open(newline="", encoding="utf-8-sig") as stream:
            records = list(csv.DictReader(stream, delimiter="\t" if suffix == ".tsv" else ","))
        return _from_records(records, smiles, name, path)
    if suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            lists = [v for v in data.values() if isinstance(v, list) and v and isinstance(v[0], dict)]
            if len(lists) != 1:
                raise ValueError(f"{path}: expected one list of molecule records")
            data = lists[0]
        return _from_records(list(data), smiles, name, path)
    raise ValueError(f"{path}: read_molecules reads .sdf, .mol, .smi, .csv, .tsv and .json files")


def molecule_table(molecules, *keys: str, structure: bool = True, titles: dict | None = None,
                   passes=None, **options):
    """A table with a structure diagram per row, the id, and the named properties.

    Each key is a property from the file (``"pic50"``) or a computed descriptor
    (``"mass"``, ``"logp"``, ``"tpsa"``, ``"qed"``, ``"hbd"``, ``"hba"``,
    ``"rule_of_five"``). ``passes`` is a function of a molecule; rows it
    rejects are printed in the failure colour.
    """
    from .content import Column, Table
    molecules = list(molecules)
    titles = {**TITLES, **(titles or {})}
    columns = ([Column("structure", "Structure")] if structure else []) + [Column("name", titles["name"])]
    columns += [Column(k, f"{titles.get(k, k)} ({_UNITS[k][0]})", unit=_UNITS[k][1]) if k in _UNITS
                else Column(k, titles.get(k, k)) for k in keys]
    # One scale for every structure, as a chemist draws a series: the bond
    # length at which the largest still fits a cell. An outlier far larger than
    # the rest is drawn smaller on its own rather than shrink them all.
    bond = CELL_BOND
    for m in molecules if structure else ():
        _, w, h = m.svg(bond=CELL_BOND)
        bond = min(bond, CELL_BOND * CELL_BOX[0] / w, CELL_BOND * CELL_BOX[1] / h)
    bond = max(bond, MIN_CELL_BOND)
    rows = []
    for m in molecules:
        values = [getattr(m, k) for k in keys]
        rows.append(([Diagram(m, bond)] if structure else []) + [m.name or m.smiles] + values)
    if passes is not None:
        options.setdefault("highlight", {i: "ok" if passes(m) else "fail" for i, m in enumerate(molecules)})
    return Table(columns, rows, **options)


def molecule_grid(molecules, *, labels=None, columns: int = 4, bond: float = 4.0,
                  caption: str | None = None, width: float = 170):
    """Structure diagrams side by side, drawn to one scale, each with its label.

    ``labels`` defaults to each molecule's name; pass a list of strings, or a
    function of a molecule (``lambda m: f"{m.name}  pIC50 {m.pic50:.1f}"``).
    """
    from .content import Drawing
    molecules = list(molecules)
    if not molecules or columns < 1:
        raise ValueError("a molecule grid needs molecules and a positive number of columns")
    if labels is None:
        labels = [str(m) for m in molecules]
    elif callable(labels):
        labels = [labels(m) for m in molecules]
    if len(labels) != len(molecules):
        raise ValueError("give one label per molecule")
    columns = min(columns, len(molecules))
    cell_w = width / columns
    drawn = [m.svg(bond=bond, box=(cell_w - 4, 3 * cell_w)) for m in molecules]
    cell_h = max(h for _, _, h in drawn) + 7  # room for the label below
    rows = -(-len(molecules) // columns)
    parts = []
    for i, ((svg, w, h), label) in enumerate(zip(drawn, labels)):
        x0, y0 = (i % columns) * cell_w, (i // columns) * cell_h
        inner = svg.decode("utf-8")
        inner = re.sub(r"<svg\b[^>]*>", lambda m: re.sub(
            r"width='[^']*' height='[^']*'",
            f"x='{x0 + (cell_w - w) / 2:.3f}' y='{y0 + (cell_h - 7 - h) / 2:.3f}' "
            f"width='{w:.3f}' height='{h:.3f}'", m[0], count=1), inner, count=1)
        parts.append(inner)
        text = (str(label).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        parts.append(f"<text x='{x0 + cell_w / 2:.3f}' y='{y0 + cell_h - 2.2:.3f}' "
                     f"text-anchor='middle' font-family='Libertinus Serif' font-size='3'>{text}</text>")
    total_h = rows * cell_h
    svg = (f"<svg xmlns='http://www.w3.org/2000/svg' xmlns:rdkit='http://www.rdkit.org/xml' "
           f"xmlns:xlink='http://www.w3.org/1999/xlink' width='{width:.3f}mm' height='{total_h:.3f}mm' "
           f"viewBox='0 0 {width:.3f} {total_h:.3f}'>" + "".join(parts) + "</svg>")
    return Drawing(svg=svg.encode("utf-8"), width=width, caption=caption)
