"""Sequences, alignments, structures and variants: the files biology tools write.

Readers for what protein design, structure prediction and genomics pipelines
produce, needing nothing beyond numpy:

- FASTA -- targets and designed sequences: :func:`read_fasta`, :class:`Sequence`
- A3M multiple sequence alignments: :func:`read_a3m`, :class:`Alignment`
- PDB and mmCIF models, with the per-residue confidence (pLDDT) predictors
  write in the B-factor column: :class:`Structure`
- VCF variant calls: :func:`read_vcf`, :func:`variant_table`

A draw cell whose last expression is a sequence shows a numbered listing; one
that is a structure shows its backbone, coloured by confidence or by chain,
with a link to the model file.
"""
from __future__ import annotations

import gzip
import math
import re
from collections import Counter
from pathlib import Path

from .units import fmt_quantity, ureg

__all__ = ["Sequence", "Sequences", "read_fasta", "Alignment", "read_a3m",
           "Structure", "read_vcf", "variant_table"]

# -- sequences -------------------------------------------------------------------

_PROTEIN = frozenset("ACDEFGHIKLMNPQRSTVWYXBZUO*-")
_DNA = frozenset("ACGTN-")
_RNA = frozenset("ACGUN-")

#: Average residue masses (amino acid less water), Da, as ExPASy ProtParam uses.
_RESIDUE_MASS = {
    "A": 71.0788, "R": 156.1875, "N": 114.1038, "D": 115.0886, "C": 103.1388,
    "E": 129.1155, "Q": 128.1307, "G": 57.0519, "H": 137.1411, "I": 113.1594,
    "L": 113.1594, "K": 128.1741, "M": 131.1926, "F": 147.1766, "P": 97.1167,
    "S": 87.0782, "T": 101.1051, "W": 186.2132, "Y": 163.1760, "V": 99.1326,
    "U": 150.0388, "O": 237.3018,
}
_WATER = 18.01528

#: Nucleotide masses for a single strand (OligoCalc's anhydrous formula, Da).
_NUCLEOTIDE_MASS = {"dna": ({"A": 313.21, "C": 289.18, "G": 329.21, "T": 304.2}, -61.96),
                    "rna": ({"A": 329.2, "C": 305.2, "G": 345.2, "U": 306.2}, 159.0)}

_BASES = "TCAG"
_AMINO = "FFLLSSSSYY**CC*WLLLLPPPPHHQQRRRRIIIMTTTTNNKKSSRRVVVVAAAADDEEGGGG"
_CODONS = {a + b + c: _AMINO[16 * i + 4 * j + k]
           for i, a in enumerate(_BASES) for j, b in enumerate(_BASES) for k, c in enumerate(_BASES)}

#: Light fills for marked positions in a listing, one per mark in order.
_MARK_COLOURS = ("#f3cf7a", "#9fd0ee", "#a9dcc0", "#f2b5c8", "#d5c3ee", "#f6b38c")


class Sequence:
    """A protein, DNA or RNA sequence. Positions in methods are 1-based."""

    def __init__(self, letters, name: str | None = None, *, kind: str | None = None,
                 description: str = "", **properties):
        letters = re.sub(r"\s+", "", str(letters)).upper()
        if kind is None:
            used = set(letters)
            kind = "dna" if used <= _DNA else "rna" if used <= _RNA else "protein"
        if kind not in ("protein", "dna", "rna"):
            raise ValueError(f"a sequence kind is protein, dna or rna, not {kind!r}")
        allowed = {"protein": _PROTEIN, "dna": _DNA, "rna": _RNA}[kind]
        bad = sorted(set(letters) - allowed)
        if bad:
            raise ValueError(f"{name or 'sequence'}: {', '.join(bad)} is not a {kind} letter")
        self.letters, self.name, self.kind, self.description = letters, name, kind, description
        self.properties = dict(properties)

    def __len__(self) -> int:
        return len(self.letters)

    def __str__(self) -> str:
        return self.letters

    def __repr__(self) -> str:
        shown = self.letters if len(self) <= 20 else self.letters[:17] + "..."
        return f"Sequence({shown!r}" + (f", name={self.name!r})" if self.name else ")")

    def __eq__(self, other) -> bool:
        return isinstance(other, Sequence) and (self.letters, self.kind) == (other.letters, other.kind)

    def __hash__(self) -> int:
        return hash((self.letters, self.kind))

    def __getitem__(self, index) -> "Sequence | str":
        if isinstance(index, slice):
            return Sequence(self.letters[index], self.name, kind=self.kind)
        return self.letters[index]

    def __getattr__(self, key):
        properties = self.__dict__.get("properties", {})
        if key in properties:
            return properties[key]
        raise AttributeError(f"{type(self).__name__} has no property {key!r}"
                             + (f"; it has {', '.join(sorted(properties))}" if properties else ""))

    @property
    def length(self) -> int:
        return len(self.letters.replace("-", ""))

    @property
    def unit(self) -> str:
        """What a position counts: residues (aa) or bases (nt)."""
        return "aa" if self.kind == "protein" else "nt"

    @property
    def mass(self):
        """Average molecular mass, in Da: ProtParam's for a protein, OligoCalc's for a strand."""
        letters = self.letters.replace("-", "")
        if self.kind == "protein":
            unknown = sorted(set(letters) - set(_RESIDUE_MASS))
            if unknown:
                raise ValueError(f"{self.name or 'sequence'}: no mass for {', '.join(unknown)}")
            return (sum(_RESIDUE_MASS[c] for c in letters) + _WATER) * ureg.Da
        masses, end = _NUCLEOTIDE_MASS[self.kind]
        unknown = sorted(set(letters) - set(masses))
        if unknown:
            raise ValueError(f"{self.name or 'sequence'}: no mass for {', '.join(unknown)}")
        return (sum(masses[c] for c in letters) + end) * ureg.Da

    @property
    def gc(self) -> float:
        """Fraction of G and C bases."""
        self._nucleic("gc")
        letters = self.letters.replace("-", "")
        return sum(c in "GC" for c in letters) / len(letters) if letters else 0.0

    def composition(self) -> dict[str, int]:
        """How often each letter occurs, most frequent first."""
        return dict(Counter(self.letters.replace("-", "")).most_common())

    def extinction(self, *, reduced: bool = True):
        """Molar extinction coefficient at 280 nm in water (ProtParam): W, Y and,
        unless ``reduced``, cystines."""
        if self.kind != "protein":
            raise ValueError("an extinction coefficient at 280 nm is for a protein")
        n = Counter(self.letters)
        value = 5500 * n["W"] + 1490 * n["Y"] + (0 if reduced else 125 * (n["C"] // 2))
        return value / (ureg.molar * ureg.cm)

    def reverse_complement(self) -> "Sequence":
        self._nucleic("reverse_complement")
        table = str.maketrans("ACGTUN-", "TGCAAN-" if self.kind == "dna" else "UGCAAN-")
        return Sequence(self.letters.translate(table)[::-1], self.name, kind=self.kind)

    def translate(self, *, to_stop: bool = False) -> "Sequence":
        """The protein a coding sequence encodes, in the standard genetic code."""
        self._nucleic("translate")
        letters = self.letters.replace("-", "").replace("U", "T")
        amino = "".join(_CODONS.get(letters[i:i + 3], "X") for i in range(0, len(letters) - 2, 3))
        if to_stop:
            amino = amino.split("*", 1)[0]
        return Sequence(amino, self.name, kind="protein")

    def identity(self, other: "Sequence") -> float:
        """Fraction of positions that match another sequence of the same length."""
        self._same_length(other, "identity")
        return sum(a == b for a, b in zip(self.letters, other.letters)) / len(self) if len(self) else 1.0

    def differences(self, other: "Sequence") -> list[int]:
        """1-based positions where another sequence of the same length differs."""
        self._same_length(other, "differences")
        return [i for i, (a, b) in enumerate(zip(self.letters, other.letters), start=1) if a != b]

    def mutations(self, other: "Sequence") -> list[str]:
        """``other`` as substitutions of this sequence: ``["A23G", "K48R"]``."""
        return [f"{self.letters[i - 1]}{i}{other.letters[i - 1]}" for i in self.differences(other)]

    def listing(self, *, marks: dict | None = None, legend: dict | None = None,
                group: int = 10, start: int = 1, caption: str | None = None):
        """The sequence as a numbered listing for a draw cell.

        ``marks`` names positions to highlight: ``{"Hotspot": [23, 27, 31]}``.
        ``legend`` may give a mark its colour, ``{"Hotspot": "#f3cf7a"}``;
        otherwise each mark takes the next of a set of light fills.
        """
        from .content import Listing
        legend = dict(legend or {})
        positions: dict[int, str] = {}
        colours: dict[str, tuple[str, str]] = {}
        for i, (label, where) in enumerate((marks or {}).items()):
            colours[label] = (legend.get(label, _MARK_COLOURS[i % len(_MARK_COLOURS)]), label)
            for p in ([where] if isinstance(where, int) else where):
                positions[int(p)] = label
        if caption is None:
            bits = [self.name] if self.name else []
            bits.append(f"{self.length} {self.unit}")
            if self.kind == "protein" and set(self.letters) <= set(_RESIDUE_MASS) | {"-"}:
                bits.append(fmt_quantity(self.mass.to(ureg.kDa)))
            elif self.kind != "protein":
                bits.append(f"GC {self.gc:.1%}")
            caption = " · ".join(bits)
        return Listing(self.letters, start=start, group=group, marks=positions,
                       legend=colours, caption=caption)

    def kip_content(self, kind: str):
        return self.listing() if kind == "draw" else None

    def kip_summary(self) -> str:
        return self.listing().caption + (f": {self.letters}" if len(self) <= 60 else "")

    def _nucleic(self, what: str) -> None:
        if self.kind == "protein":
            raise ValueError(f"{what} is for a DNA or RNA sequence; {self.name or 'this'} is a protein")

    def _same_length(self, other: "Sequence", what: str) -> None:
        if len(self) != len(other):
            raise ValueError(f"{what} compares sequences of one length ({len(self)} and {len(other)}); "
                             "align them first")


class Sequences(list):
    """Sequences read from one file, in order; ``seqs["binder_1"]`` finds one by name."""

    def kip_summary(self) -> str:
        return f"{len(self)} sequence{'s' if len(self) != 1 else ''}: " + ", ".join(
            str(s.name) for s in list.__iter__(self))[:200]

    def __getitem__(self, key):
        if isinstance(key, str):
            for sequence in self:
                if sequence.name == key:
                    return sequence
            raise KeyError(f"no sequence named {key!r}; names are "
                           + ", ".join(str(s.name) for s in list.__iter__(self)))
        return list.__getitem__(self, key)


def _open_text(path: Path) -> str:
    data = path.read_bytes()
    if path.suffix.lower() == ".gz":
        data = gzip.decompress(data)
    return data.decode("utf-8")


def read_fasta(path, *, kind: str | None = None) -> Sequences:
    """Every sequence in a FASTA file: ``>name description`` then the letters.

    ``key=value`` pairs in a header become properties, so ProteinMPNN's
    ``>T=0.1, sample=1, score=0.92`` reads as ``seq.score``. A header that
    starts with such a pair names the sequence ``seq1``, ``seq2``, ...
    """
    from .authoring import project_path
    from .chem import _number
    path = project_path(path)
    out, name, description, lines, properties = Sequences(), None, "", [], {}

    def flush():
        if name is not None:
            out.append(Sequence("".join(lines), name, kind=kind, description=description,
                                **properties))

    for line in _open_text(path).splitlines():
        if line.startswith(">"):
            flush()
            header = line[1:].strip()
            first = header.split(None, 1)[0].rstrip(",") if header else ""
            name = first if first and "=" not in first else f"seq{len(out) + 1}"
            description = header[len(first):].strip(" ,") if "=" not in first else header
            properties = {k: _number(v) for k, v in re.findall(r"([A-Za-z_][\w.]*)=([^,\s]+)", header)}
            lines = []
        elif line.strip() and not line.startswith(";"):
            if name is None:
                raise ValueError(f"{path}: sequence letters before the first >name line")
            lines.append(line.strip())
    flush()
    return out


# -- alignments --------------------------------------------------------------------

class Alignment:
    """A multiple sequence alignment against its first (query) sequence."""

    def __init__(self, names: list[str], rows: list[str]):
        if not rows:
            raise ValueError("an alignment needs at least the query sequence")
        width = len(rows[0])
        if any(len(r) != width for r in rows):
            raise ValueError("alignment rows differ in length once insertions are removed")
        self.names, self.rows = names, rows

    @property
    def query(self) -> Sequence:
        return Sequence(self.rows[0].replace("-", ""), self.names[0])

    @property
    def depth(self) -> int:
        """Sequences in the alignment, the query included."""
        return len(self.rows)

    def coverage(self) -> list[float]:
        """Per query position, the fraction of sequences with a residue there."""
        return [sum(r[i] != "-" for r in self.rows) / self.depth for i in range(len(self.rows[0]))]

    def identity(self) -> list[float]:
        """Each sequence's identity to the query over the positions it covers."""
        query = self.rows[0]
        out = []
        for row in self.rows:
            covered = [(a, b) for a, b in zip(query, row) if b != "-" and a != "-"]
            out.append(sum(a == b for a, b in covered) / len(covered) if covered else 0.0)
        return out

    def __len__(self) -> int:
        return self.depth

    def __str__(self) -> str:
        return f"{self.depth} sequences × {len(self.rows[0])} positions"

    def kip_summary(self) -> str:
        return str(self)


def read_a3m(path) -> Alignment:
    """An A3M alignment (as MSA search writes it); lowercase insertions are dropped."""
    from .authoring import project_path
    path = project_path(path)
    names, rows = [], []
    for line in _open_text(path).splitlines():
        if line.startswith(">"):
            names.append(line[1:].strip().split(None, 1)[0] if line[1:].strip() else f"seq{len(names) + 1}")
            rows.append("")
        elif line.strip() and not line.startswith("#") and names:
            rows[-1] += re.sub(r"[a-z.]", "", line.strip())
    return Alignment(names, rows)


# -- structures --------------------------------------------------------------------

_THREE = {"ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C", "GLN": "Q", "GLU": "E",
          "GLY": "G", "HIS": "H", "ILE": "I", "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F",
          "PRO": "P", "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
          "MSE": "M", "SEC": "U", "PYL": "O"}
_NUCLEOTIDES = {"DA": "A", "DC": "C", "DG": "G", "DT": "T", "A": "A", "C": "C", "G": "G", "U": "U"}
_WATERS = {"HOH", "WAT", "DOD", "H2O"}

#: Confidence bands and colours as AlphaFold publishes them.
PLDDT_BANDS = ((90, "#0053d6", "Very high (pLDDT > 90)"), (70, "#65cbf3", "Confident (70–90)"),
               (50, "#ffdb13", "Low (50–70)"), (-1, "#ff7d45", "Very low (< 50)"))
#: Okabe-Ito colours, which stay distinct for colour-blind readers.
CHAIN_COLOURS = ("#0072b2", "#e69f00", "#009e73", "#cc79a7", "#56b4e9", "#d55e00", "#000000")
_PAPER = "#f7f2e3"


class _Atom:
    __slots__ = ("chain", "resseq", "icode", "resname", "name", "element", "xyz", "b", "hetero")

    def __init__(self, chain, resseq, icode, resname, name, element, xyz, b, hetero):
        self.chain, self.resseq, self.icode, self.resname = chain, resseq, icode, resname
        self.name, self.element, self.xyz, self.b, self.hetero = name, element, xyz, b, hetero

    @property
    def polymer(self) -> bool:
        return self.resname in _THREE or self.resname in _NUCLEOTIDES

    @property
    def trace(self) -> bool:
        """The one atom per residue a backbone trace joins."""
        if self.resname in _THREE:
            return self.name == "CA"
        return self.resname in _NUCLEOTIDES and self.name == "C4'"


def _pdb_atoms(text: str) -> list[_Atom]:
    atoms = []
    for line in text.splitlines():
        record = line[:6]
        if record.startswith("ENDMDL"):
            break  # the first model only
        if record not in ("ATOM  ", "HETATM"):
            continue
        if line[16:17] not in (" ", "A", ""):
            continue  # the first alternate location only
        name = line[12:16].strip()
        element = line[76:78].strip() or re.sub(r"[^A-Za-z]", "", name)[:1]
        try:
            xyz = (float(line[30:38]), float(line[38:46]), float(line[46:54]))
            b = float(line[60:66]) if line[60:66].strip() else 0.0
            resseq = int(line[22:26])
        except ValueError as exc:
            raise ValueError(f"unreadable PDB atom line: {line.rstrip()}") from exc
        atoms.append(_Atom(line[21:22].strip() or "A", resseq, line[26:27].strip(),
                           line[17:20].strip(), name, element.upper(), xyz, b, record == "HETATM"))
    return atoms


_CIF_TOKEN = re.compile(r"""'(?:[^']|'(?=\S))*'|"(?:[^"]|"(?=\S))*"|\S+""")


def _cif_atoms(text: str) -> list[_Atom]:
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].strip() != "loop_":
            i += 1
            continue
        j, names = i + 1, []
        while j < len(lines) and lines[j].strip().startswith("_"):
            names.append(lines[j].split()[0])
            j += 1
        if not names or not names[0].startswith("_atom_site."):
            i = j
            continue
        tokens: list[str] = []
        while j < len(lines):
            line = lines[j]
            stripped = line.strip()
            if stripped.startswith(("loop_", "_", "#", "data_")):
                break
            if line.startswith(";"):  # a multi-line text value
                block = [line[1:]]
                j += 1
                while j < len(lines) and not lines[j].startswith(";"):
                    block.append(lines[j])
                    j += 1
                tokens.append("\n".join(block))
            else:
                tokens.extend(t[1:-1] if t[:1] in "'\"" and len(t) > 1 else t
                              for t in _CIF_TOKEN.findall(line))
            j += 1
        return _cif_rows([n.split(".", 1)[1] for n in names], tokens)
    raise ValueError("no _atom_site loop: not an mmCIF model")


def _cif_rows(names: list[str], tokens: list[str]) -> list[_Atom]:
    if len(tokens) % len(names):
        raise ValueError("the mmCIF _atom_site loop has a short row")
    column = {n: k for k, n in enumerate(names)}

    def pick(row, *keys, default=""):
        for key in keys:
            if key in column and row[column[key]] not in (".", "?"):
                return row[column[key]]
        return default

    atoms, first_model = [], None
    for start in range(0, len(tokens), len(names)):
        row = tokens[start:start + len(names)]
        model = pick(row, "pdbx_PDB_model_num", default="1")
        first_model = first_model or model
        if model != first_model:
            break
        if pick(row, "label_alt_id") not in ("", "A"):
            continue
        name = pick(row, "auth_atom_id", "label_atom_id")
        try:
            xyz = (float(pick(row, "Cartn_x")), float(pick(row, "Cartn_y")), float(pick(row, "Cartn_z")))
            b = float(pick(row, "B_iso_or_equiv", default="0"))
            resseq = int(pick(row, "auth_seq_id", "label_seq_id", default="0"))
        except ValueError as exc:
            raise ValueError(f"unreadable mmCIF atom row: {' '.join(row)}") from exc
        atoms.append(_Atom(pick(row, "auth_asym_id", "label_asym_id", default="A"), resseq,
                           pick(row, "pdbx_PDB_ins_code"), pick(row, "auth_comp_id", "label_comp_id"),
                           name, (pick(row, "type_symbol") or name[:1]).upper(), xyz, b,
                           pick(row, "group_PDB") == "HETATM"))
    return atoms


def _kabsch_rmsd(p, q) -> float:
    import numpy as np
    p, q = p - p.mean(axis=0), q - q.mean(axis=0)
    u, _, vt = np.linalg.svd(p.T @ q)
    d = np.sign(np.linalg.det(vt.T @ u.T)) or 1.0
    rotation = vt.T @ np.diag([1.0, 1.0, d]) @ u.T
    return float(np.sqrt(((p @ rotation.T - q) ** 2).sum() / len(p)))


class Structure:
    """A PDB or mmCIF model: chains, sequences, confidence, ligands, and a picture.

    The first model and first alternate location are read. Predictors write
    per-residue pLDDT in the B-factor column, which :meth:`plddt` reads (on a
    0-100 scale, whichever scale the file uses).
    """

    def __init__(self, atoms: list, *, name: str = "", source: bytes | None = None,
                 filename: str | None = None):
        if not atoms:
            raise ValueError(f"{filename or 'structure'}: no atoms")
        self.atoms, self.name, self.source, self.filename = atoms, name, source, filename

    @classmethod
    def load(cls, path, *, name: str | None = None) -> "Structure":
        from .authoring import project_path
        path = project_path(path)
        data = path.read_bytes()
        stem = path.name.removesuffix(".gz")
        text = (gzip.decompress(data) if path.suffix.lower() == ".gz" else data).decode("utf-8")
        kind = "cif" if stem.lower().endswith((".cif", ".mmcif")) else "pdb"
        try:
            structure = cls.parse(text, format=kind, name=name or Path(stem).stem)
        except ValueError as exc:
            raise ValueError(f"{path}: {exc}") from None
        structure.source, structure.filename = data, path.name
        return structure

    @classmethod
    def parse(cls, text: str, *, format: str = "pdb", name: str = "") -> "Structure":
        if format not in ("pdb", "cif"):
            raise ValueError("a structure's format is 'pdb' or 'cif'")
        return cls(_cif_atoms(text) if format == "cif" else _pdb_atoms(text), name=name)

    # -- what is in it ------------------------------------------------------------

    @property
    def chains(self) -> list[str]:
        return list(dict.fromkeys(a.chain for a in self.atoms if a.polymer))

    def _traces(self, chain: str | None) -> list[_Atom]:
        if chain is not None and chain not in self.chains:
            raise ValueError(f"no chain {chain!r}; chains are {', '.join(self.chains)}")
        return [a for a in self.atoms if a.trace and (chain is None or a.chain == chain)]

    def residues(self, chain: str | None = None) -> list[int]:
        """Residue numbers, in order, of a chain (or of every chain)."""
        return [a.resseq for a in self._traces(chain)]

    def sequence(self, chain: str | None = None) -> Sequence:
        """A chain's sequence from its residues; a one-chain model needs no chain."""
        if chain is None:
            if len(self.chains) != 1:
                raise ValueError(f"give chain=, one of {', '.join(self.chains)}")
            chain = self.chains[0]
        traces = self._traces(chain)
        nucleic = all(a.resname in _NUCLEOTIDES for a in traces)
        letters = "".join((_NUCLEOTIDES if nucleic else _THREE).get(a.resname, "X") for a in traces)
        return Sequence(letters, f"{self.name}:{chain}" if self.name else chain,
                        kind=("rna" if "U" in letters else "dna") if nucleic else "protein")

    def plddt(self, chain: str | None = None) -> list[float]:
        """Per-residue confidence from the B-factor column, on a 0-100 scale."""
        values = [a.b for a in self._traces(chain)]
        scale = 100.0 if values and max(values) <= 1.0 else 1.0
        return [v * scale for v in values]

    def mean_plddt(self, chain: str | None = None) -> float:
        values = self.plddt(chain)
        return sum(values) / len(values) if values else float("nan")

    @property
    def ligands(self) -> list[str]:
        """Each small molecule bound in the model, as ``NAME chain:number``."""
        groups = dict.fromkeys((a.resname, a.chain, a.resseq) for a in self.atoms
                               if not a.polymer and a.resname not in _WATERS)
        return [f"{n} {c}:{r}" for n, c, r in groups]

    def interface(self, chain: str, partner: str | None = None, *, cutoff: float = 8.0) -> list[int]:
        """Residue numbers of ``chain`` within ``cutoff`` Å (trace atom to trace
        atom) of ``partner``, or of any other chain."""
        others = [a.xyz for a in self._traces(partner) if a.chain != chain]
        if not others:
            raise ValueError(f"no other chain to find {chain}'s interface with")
        return [a.resseq for a in self._traces(chain)
                if any(math.dist(a.xyz, xyz) <= cutoff for xyz in others)]

    def ca(self, chain: str | None = None):
        """Trace-atom coordinates (Å) as an N×3 array."""
        import numpy as np
        return np.array([a.xyz for a in self._traces(chain)], dtype=float)

    def rmsd(self, other: "Structure", chain: str | None = None, other_chain: str | None = None):
        """Backbone RMSD after superposition, over the residues both models number alike."""
        import numpy as np
        mine = {(a.resseq, a.icode): a.xyz for a in self._traces(chain)}
        theirs = {(a.resseq, a.icode): a.xyz for a in other._traces(other_chain or chain)}
        common = [k for k in mine if k in theirs]
        if len(common) < 3:
            raise ValueError("an RMSD needs at least three residues numbered alike in both models")
        return _kabsch_rmsd(np.array([mine[k] for k in common]),
                            np.array([theirs[k] for k in common])) * ureg.angstrom

    def looks_predicted(self) -> bool:
        """Whether the B-factors read as confidences: 0-100 and one value per residue."""
        values = [a.b for a in self.atoms if a.polymer]
        if not values or min(values) < 0 or max(values) > 100:
            return False
        per_residue: dict = {}
        for a in self.atoms:
            if a.polymer:
                per_residue.setdefault((a.chain, a.resseq, a.icode), set()).add(round(a.b, 2))
        return all(len(v) == 1 for v in per_residue.values())

    def __str__(self) -> str:
        chains = ", ".join(f"{c} ({len(self._traces(c))})" for c in self.chains)
        text = f"{self.filename or self.name or 'structure'}: chains {chains}"
        if self.looks_predicted():
            text += f"; mean pLDDT {self.mean_plddt():.1f}"
        if self.ligands:
            text += "; ligands " + ", ".join(self.ligands)
        return text

    # -- the picture ----------------------------------------------------------------

    def drawing(self, *, color: str | None = None, width: float = 90, caption: str | None = None,
                attach: bool = True):
        """The backbone, oriented to show its longest extent, as a vector drawing.

        ``color`` is ``"plddt"`` (AlphaFold's confidence bands) or ``"chain"``;
        by default a predicted model is coloured by confidence. Bound ligands
        are drawn as atoms and bonds. ``attach`` links the model file under the
        picture, so a reader can open it in a molecular viewer.
        """
        from .content import Drawing
        color = color or ("plddt" if self.looks_predicted() else "chain")
        if color not in ("plddt", "chain"):
            raise ValueError("color is 'plddt' or 'chain'")
        svg = _trace_svg(self, color, width)
        attachments = {self.filename: self.source} if attach and self.source and self.filename else {}
        return Drawing(svg=svg, width=width, caption=caption, attachments=attachments)

    def kip_content(self, kind: str):
        return self.drawing() if kind == "draw" else None

    def kip_summary(self) -> str:
        return str(self)


def _band(value: float) -> str:
    return next(colour for limit, colour, _ in PLDDT_BANDS if value > limit)


def _trace_svg(structure: Structure, color: str, width: float) -> bytes:
    import numpy as np

    traces = structure._traces(None)
    ligand = [a for a in structure.atoms if not a.polymer and a.resname not in _WATERS and a.element != "H"]
    if not traces:
        raise ValueError("no protein or nucleic-acid backbone to draw")
    points = np.array([a.xyz for a in traces] + [a.xyz for a in ligand], dtype=float)
    centre = points[: len(traces)].mean(axis=0)
    _, vectors = np.linalg.eigh(np.cov((points[: len(traces)] - centre).T) if len(traces) > 2
                                else np.eye(3))
    axes = vectors[:, ::-1]  # longest extent first
    for k in range(3):  # a stable orientation: each axis's largest component positive
        if axes[np.argmax(np.abs(axes[:, k])), k] < 0:
            axes[:, k] *= -1
    projected = (points - centre) @ axes
    margin = 2.0
    span = np.ptp(projected[:, :2], axis=0)
    scale = min((width - 2 * margin) / max(span[0], 1e-6), 110.0 / max(span[1], 1e-6))
    x = (projected[:, 0] - projected[:, 0].min()) * scale + margin
    y = (projected[:, 1].max() - projected[:, 1]) * scale + margin
    z = projected[:, 2]
    zmin, zmax = z.min(), z.max()
    depth = (z - zmin) / (zmax - zmin) if zmax > zmin else np.full(len(z), 0.5)
    height = span[1] * scale + 2 * margin

    chains = structure.chains
    plddt = structure.plddt() if color == "plddt" else None
    # Consecutive trace atoms of one chain are joined unless the chain breaks.
    linked = [a.chain == b.chain and math.dist(a.xyz, b.xyz) <= 7.5
              for a, b in zip(traces, traces[1:])] + [False]
    segments = []
    for i in range(len(traces) - 1):
        if not linked[i]:
            continue
        a = traces[i]
        colour = (_band((plddt[i] + plddt[i + 1]) / 2) if plddt is not None
                  else CHAIN_COLOURS[chains.index(a.chain) % len(CHAIN_COLOURS)])
        segments.append(((depth[i] + depth[i + 1]) / 2, i, i + 1, colour))
    lig = range(len(traces), len(points))
    bonds = [(i, j) for i in lig for j in lig if i < j
             and math.dist(ligand[i - len(traces)].xyz, ligand[j - len(traces)].xyz) < 1.9]
    items = [(d, "segment", i, j, c) for d, i, j, c in segments]
    items += [((depth[i] + depth[j]) / 2, "bond", i, j, "#2b2b2b") for i, j in bonds]
    items += [(depth[i], "atom", i, i, "#2b2b2b") for i in lig]
    parts = []
    for d, kind, i, j, colour in sorted(items):  # back to front
        w = 0.45 + 0.4 * d
        if kind == "atom":
            parts.append(f"<circle cx='{x[i]:.2f}' cy='{y[i]:.2f}' r='{0.35 + 0.15 * d:.2f}' "
                         f"fill='{colour}' stroke='{_PAPER}' stroke-width='0.15'/>")
            continue
        if kind == "bond":
            w, curve = 0.3, f"M {x[i]:.2f} {y[i]:.2f} L {x[j]:.2f} {y[j]:.2f}"
        else:  # a Catmull-Rom curve through the neighbouring trace atoms
            h = i - 1 if i and linked[i - 1] else i
            k = j + 1 if linked[j] else j
            c1 = (x[i] + (x[j] - x[h]) / 6, y[i] + (y[j] - y[h]) / 6)
            c2 = (x[j] - (x[k] - x[i]) / 6, y[j] - (y[k] - y[i]) / 6)
            curve = (f"M {x[i]:.2f} {y[i]:.2f} C {c1[0]:.2f} {c1[1]:.2f} "
                     f"{c2[0]:.2f} {c2[1]:.2f} {x[j]:.2f} {y[j]:.2f}")
        parts.append(f"<path d='{curve}' fill='none' stroke='{_PAPER}' stroke-width='{w + 0.35:.2f}' "
                     "stroke-linecap='round'/>")
        parts.append(f"<path d='{curve}' fill='none' stroke='{colour}' stroke-width='{w:.2f}' "
                     "stroke-linecap='round'/>")
    keys = ([(colour, label) for _, colour, label in PLDDT_BANDS] if plddt is not None
            else [(CHAIN_COLOURS[k % len(CHAIN_COLOURS)], f"Chain {c}") for k, c in enumerate(chains)])
    if ligand:
        keys.append(("#2b2b2b", "Ligand"))
    lx, ly = margin, height + 2.5
    for colour, label in keys:
        step = 3.2 + 1.3 * len(label) + 3.5  # swatch, words at about 1.3 mm a letter, gap
        if lx > margin and lx + step - 3.5 > width - margin:
            lx, ly = margin, ly + 4.0  # the legend wraps
        text = label.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        parts.append(f"<rect x='{lx:.2f}' y='{ly - 2.1:.2f}' width='2.4' height='2.4' rx='0.3' fill='{colour}'/>")
        parts.append(f"<text x='{lx + 3.2:.2f}' y='{ly:.2f}' font-family='Libertinus Serif' "
                     f"font-size='2.8' fill='#3a342b'>{text}</text>")
        lx += step
    total = ly + 1.5
    return (f"<svg xmlns='http://www.w3.org/2000/svg' width='{width:.2f}mm' height='{total:.2f}mm' "
            f"viewBox='0 0 {width:.2f} {total:.2f}'>" + "".join(parts) + "</svg>").encode("utf-8")


# -- variants ------------------------------------------------------------------------

def read_vcf(path) -> list[dict]:
    """Variant calls from a VCF (or .vcf.gz): one dict per record.

    Each has ``chrom``, ``pos``, ``id``, ``ref``, ``alt``, ``qual``, ``filter``
    and ``info`` (a dict; a flag is ``True``); sample columns are kept under
    ``samples`` by name.
    """
    from .authoring import project_path
    path = project_path(path)
    header: list[str] = []
    out = []
    for line in _open_text(path).splitlines():
        if line.startswith("##") or not line.strip():
            continue
        if line.startswith("#"):
            header = line[1:].split("\t")
            continue
        fields = line.split("\t")
        if len(fields) < 8:
            raise ValueError(f"{path}: a VCF record has eight tab-separated fields: {line[:60]}")
        info = {}
        for item in fields[7].split(";"):
            if item and item != ".":
                key, sep, value = item.partition("=")
                info[key] = _vcf_value(value) if sep else True
        record = {"chrom": fields[0], "pos": int(fields[1]), "id": fields[2] if fields[2] != "." else "",
                  "ref": fields[3], "alt": fields[4],
                  "qual": float(fields[5]) if fields[5] != "." else None,
                  "filter": fields[6], "info": info}
        if len(fields) > 9 and header:
            keys = fields[8].split(":")
            record["samples"] = {name: dict(zip(keys, value.split(":")))
                                 for name, value in zip(header[9:], fields[9:])}
        out.append(record)
    return out


def _vcf_value(text: str):
    parts = [p for p in text.split(",")]
    values = []
    for part in parts:
        try:
            values.append(int(part))
        except ValueError:
            try:
                values.append(float(part))
            except ValueError:
                values.append(part)
    return values[0] if len(values) == 1 else values


def variant_table(variants, *info: str, titles: dict | None = None, **options):
    """Variants as a table: position, change, quality, filter and chosen INFO fields."""
    from .content import Column, Table
    titles = titles or {}
    columns = [Column("chrom", "Chrom"), Column("pos", "Position"), Column("id", "ID"),
               Column("ref", "Ref"), Column("alt", "Alt"), Column("qual", "Qual"),
               Column("filter", "Filter")]
    columns += [Column(key, titles.get(key, key)) for key in info]
    rows = [[v["chrom"], v["pos"], v["id"] or "-", v["ref"], v["alt"],
             v["qual"] if v["qual"] is not None else "-", v["filter"]]
            + [v["info"].get(key, "-") for key in info] for v in variants]
    return Table(columns, rows, **options)
