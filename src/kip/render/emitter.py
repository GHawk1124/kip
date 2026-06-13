"""Emit an executed document as one vector Typst project."""

from __future__ import annotations

import re
from pathlib import Path

from ..content import Drawing, Figure, Source, Sources, Table, Symbol, Math
from ..doc.kernel import BlockResult, Document
from ..math.handcalc_bridge import MITEX_VERSION
from ..units import fmt_quantity
from .layout import Layout

__all__ = ["emit", "emit_body", "emit_debug", "collect_sources", "TYPST_LIB",
           "LILAQ_VERSION", "CETZ_VERSION"]

from ..resources import TYPST

TYPST_LIB = TYPST / "lib"

LILAQ_VERSION = "0.5.0"
CETZ_VERSION = "0.4.2"

# primitives


def _s(value) -> str:
    """Quote a Python string as a Typst string literal."""
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _opt(value) -> str:
    return _s(value) if value else "none"


def _num(x: float) -> str:
    x = float(x)
    if x != x or x in (float("inf"), float("-inf")):
        return "0"
    return f"{x:.10g}"


def _array(values) -> str:
    return "(" + ", ".join(_num(v) for v in values) + ",)"


def _raw_block(body: str) -> str:
    """Wrap text in a Typst raw block with a fence long enough to be safe."""
    fence = "`"
    while fence * 3 in body:
        fence += "`"
    return f"{fence * 3}\n{body}\n{fence * 3}"


def _mitex(latex: str) -> str:
    # handcalcs owns the algebra; kip owns the baseline pitch. Its outer
    # aligned environment adds unrelated padding and row spacing.
    body = latex.strip()
    if body.startswith(r"\begin{aligned}") and body.endswith(r"\end{aligned}"):
        body = body[len(r"\begin{aligned}"):-len(r"\end{aligned}")]
        rows = re.split(r"\\\\(?:\[[^\]]*\])?", body)
    else:
        rows = [body]
    return "\n".join(
        f"#grid-math(math.display(mitex({_raw_block(row.strip())}, block: false)))"
        for row in rows if row.strip()
    )

# prose


def _markdown_to_typst(text: str) -> str:
    """Minimal prose conversion: ATX headings become Typst headings.

    Prose is authored as Markdown-ish text because that is what an AI writes
    naturally; Typst markup otherwise passes through unchanged.
    """
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#") and not stripped.startswith("#("):
            level = len(stripped) - len(stripped.lstrip("#"))
            rest = stripped[level:].strip()
            if rest:
                out.append("=" * level + " " + rest)
                continue
        out.append(line)
    return "\n".join(out)


def _resolve_refs(text: str, known_blocks: dict[str, str],
                  sources: dict[str, tuple[int, Source]]) -> str:
    """Resolve ``@blk:``, ``@src:`` and ``@req:`` citations.

    A reference to a block that does not exist degrades to plain text: Typst
    raises a hard "label does not exist" error for a dangling link, which would
    fail the whole build over one typo in prose. ``kip check`` reports dangling
    references separately.
    """
    def blk(m):
        target = m.group(1)
        if target not in known_blocks:
            return target
        shown = known_blocks[target] or target
        return f"#link(label({_s('blk-' + target)}))[{shown}]"

    def req(m):
        return ("#box(fill: kip-colors.chip, inset: (x: 3pt, y: 0pt), "
                f"radius: 2pt)[{m.group(1)}]")

    def src(m):
        entry = sources.get(m.group(1))
        if entry is None:
            return m.group(1)
        n, source = entry
        return f"#kip-cite({n}, {_s(source.short())}, url: {_opt(source.url)})"

    text = re.sub(r"@blk:([A-Za-z_][A-Za-z0-9_]*)", blk, text)
    text = re.sub(r"@src:([A-Za-z_][A-Za-z0-9_\-]*)", src, text)
    text = re.sub(r"@req:([A-Za-z][A-Za-z0-9_\-]*)", req, text)
    return text

# rich content


#: Friendly mark names -> lilaq's matplotlib-style short names. Passing an
#: unknown name straight through would surface as a Typst assertion failure
#: deep inside the package, so unknown names raise a Python error instead.
_MARK_ALIASES = {
    "o": "o", "circle": "o",
    "s": "s", "square": "s",
    "d": "d", "diamond": "d",
    "^": "^", "triangle": "^", "triangle-up": "^",
    "v": "v", "triangle-down": "v",
    "<": "<", ">": ">",
    "x": "x", "cross": "x",
    "+": "+", "plus": "+",
    "*": "*", "asterisk": "*",
    "star": "star",
    ".": ".", "point": ".",
}


def _mark(name: str | None) -> str:
    if not name:
        return "none"
    key = _MARK_ALIASES.get(name)
    if key is None:
        raise ValueError(
            f"unknown plot mark {name!r}; expected one of "
            + ", ".join(sorted(set(_MARK_ALIASES)))
        )
    return _s(key)


def _figure(fig: Figure, *, snapped: bool = False) -> str:
    """Render a :class:`Figure` as a lilaq diagram -- fully vector."""
    parts: list[str] = []
    for s in fig.series:
        args = [_array(s.x), _array(s.y)]
        if s.kind == "bar":
            call = "lq.bar"
        elif s.kind == "scatter":
            call = "lq.scatter"
            args.append(f"mark: {_mark(s.mark or 'o')}")
        else:
            call = "lq.plot"
            args.append(f"mark: {_mark(s.mark)}")
            if s.dash:
                args.append(f"stroke: (dash: {_s(s.dash)})")
        if s.color:
            args.append(f"color: rgb({_s(s.color)})")
        if s.label:
            args.append(f"label: [{s.label}]")
        parts.append(f"  {call}({', '.join(args)}),")

    opts = [f"  width: {_num(fig.width)}mm", f"  height: {_num(fig.height)}mm",
            '  fill: rgb("#fdfbf4")']
    if fig.xlabel:
        opts.append(f"  xlabel: [{fig.xlabel}]")
    if fig.ylabel:
        opts.append(f"  ylabel: [{fig.ylabel}]")
    if fig.title:
        opts.append(f"  title: [{fig.title}]")
    if fig.xscale == "log":
        opts.append('  xscale: "log"')
    if fig.yscale == "log":
        opts.append('  yscale: "log"')
    if fig.xlim:
        opts.append(f"  xlim: ({_num(fig.xlim[0])}, {_num(fig.xlim[1])})")
    if fig.ylim:
        opts.append(f"  ylim: ({_num(fig.ylim[0])}, {_num(fig.ylim[1])})")

    markup = "#lq.diagram(\n" + ",\n".join(opts) + ",\n" + "\n".join(parts) + "\n)"
    if snapped:
        markup = markup.replace(f"{_num(fig.width)}mm", f"calc.max(1, calc.floor({_num(fig.width)}mm / g)) * g", 1)
        markup = markup.replace(f"{_num(fig.height)}mm", f"calc.max(1, calc.floor({_num(fig.height)}mm / g)) * g", 1)
        return "#context { let g = kip-grid.get();\nshow box: it => {\n if type(it.inset) == dictionary and it.inset.keys().sorted() == (\"bottom\", \"left\", \"right\", \"top\") and it.inset.values().any(v => calc.abs(v / g - calc.round(v / g)) > 0.0001) {\n [#show box: it => it\n#box(inset: it.inset.map(v => calc.ceil(v / g) * g), it.body)]\n } else { it }\n}\n" + markup[1:] + "\n}"
    return markup


def _drawing(d: Drawing, svg_path: str | None = None) -> str:
    """Render a :class:`Drawing` through CeTZ.

    ``cetz.canvas`` sizes itself from its content and its ``length`` unit --
    it accepts no width/height. A requested width is a maximum; smaller
    canvases retain their intrinsic bounds, including when a panel is enabled.
    """
    if d.svg is not None:
        canvas = f"#image({_s(svg_path or 'drawing.svg')}" + (f", height: {_num(d.height)}mm" if d.height else "") + ")"
        return f"#drawing-width({_num(d.width or 80)}mm)[{canvas}]"
    canvas = (f"#cetz.canvas(length: {d.length}, {{\n"
              f"  import cetz.draw: *\n{d.body}\n}})")
    if d.width is not None:
        return f"#drawing-width({_num(d.width)}mm)[{canvas}]"
    return canvas


def _cell(tbl: Table, value, column=None) -> str:
    """Keep prose literal; only explicitly typed mathematics enters math mode."""
    from sympy import Basic
    from ..math.printer import render_name, typst_math

    if isinstance(value, Symbol):
        return f"[${render_name(value.name)}$]"
    if isinstance(value, Math):
        return f"[${value.body}$]"
    if isinstance(value, Basic):
        return f"[${typst_math(value)}$]"
    if column is not None and column.math and isinstance(value, str) and value != "-":
        return f"[${render_name(value)}$]"
    text = tbl.cell_text(value, column) if column is not None else str(value)
    return f"[#text({_s(text)})]"


def _table_kwargs(tbl: Table, xlsx_href: str | None) -> dict:
    rows, hidden = tbl.display_rows()
    headers = "(" + ", ".join(_cell(tbl, h) for h in tbl.headers) + ",)"
    shown = tbl.rows if tbl.max_rows is None else tbl.rows[:tbl.max_rows]
    body = "(" + ", ".join(
        "(" + ", ".join(_cell(tbl, v, c) for v, c in zip(row, tbl.columns)) + ",)" for row in shown
    ) + ",)"
    aligns = "(" + ", ".join(c.align for c in tbl.columns) + ",)"
    # Preserve long identifiers and numbers where possible; prose receives the
    # remaining width according to its measured wrapping demand in Typst.
    all_rows = [tbl.headers, *rows]
    if tbl.total_row:
        all_rows.append([tbl.cell_text(v, c) for v, c in zip(tbl.total_row, tbl.columns)])
    token_columns = []
    for i in range(len(tbl.columns)):
        words = sorted({word for row in all_rows for word in str(row[i]).split()})
        token_columns.append("(" + ", ".join(_s(w) for w in words) + ",)" if words else "()")
    tokens = "(" + ", ".join(token_columns) + ",)"
    marks = ("(" + ", ".join(f"{_s(str(i))}: {_s(v)}"
                             for i, v in tbl.highlight.items()) + ")"
             if tbl.highlight else "(:)")

    note = None
    if hidden:
        note = (f"{hidden} further row{'s' if hidden != 1 else ''} omitted; "
                "the workbook has the complete data set.")

    total = None
    if tbl.total_row:
        total = "(" + ", ".join(
            _cell(tbl, v, c)
            for v, c in zip(tbl.total_row, tbl.columns)) + ",)"

    # A short table must not break, or its footnote and the xlsx link can be
    # orphaned onto the next page. A genuinely long one has to break or it
    # would overflow the page entirely.
    breakable = len(rows) > 18

    return {
        "breakable": "true" if breakable else "false",
        "headers": headers, "rows": body, "aligns": aligns, "marks": marks,
        "tokens": tokens,
        "total": total, "note": _opt(note),
        "zebra": "true" if tbl.zebra else "false",
        "link_to": _opt(xlsx_href),
        "link_text": _opt(f"Open {Path(xlsx_href).name}" if xlsx_href else None),
        "caption": _opt(tbl.caption),
    }

# blocks


def _result_chip(block, result: BlockResult) -> str:
    """Spreadsheet-style output marker showing the block's final value."""
    if block.kind != "calc" or not result.values:
        return "none"
    from ..math.handcalc_bridge import last_assigned_names
    from ..math.printer import render_name

    names = [n for n in last_assigned_names(block.source) if n in result.values]
    if not names:
        return "none"
    name = names[-1]
    value = fmt_quantity(result.values[name], block.precision)
    return f"result-chip(${render_name(name)}$, {_s(value)})"


#: Below this rendered width (mm) a calc is stacked rather than laid out in
#: handcalcs' three-column form, which needs room it does not have in a column.
NARROW_MM = 120.0


def _calc_latex(result: BlockResult, width_mm: float | None) -> str:
    if width_mm is not None and width_mm < NARROW_MM and result.latex_long:
        return result.latex_long
    return result.latex or ""


def _emit_block(block, result: BlockResult, known: dict[str, str],
                sources: dict[str, tuple[int, Source]],
                assets: dict[str, str], width_mm: float | None = None) -> str:
    bid = _s(block.id)
    lbl = _opt(block.meta.get("label"))

    if result.failed:
        return (f"#kip-error(id: {bid}, "
                f"message: {_s(result.error or 'unknown error')}, "
                f"detail: {_s((result.traceback or '').strip()[-400:])})")

    kind = block.kind

    if kind == "text":
        body = _resolve_refs(_markdown_to_typst(result.text or ""), known, sources)
        return f"#kip-text(id: {bid}, label: {lbl})[\n{body}\n]"

    if kind == "given":
        from ..math.printer import render_name
        from ..math.handcalc_bridge import last_assigned_names
        rows = ", ".join(
            f"(name: [${render_name(name)}$], value: {_s(fmt_quantity(value, block.precision))})"
            for name in last_assigned_names(block.source)
            if name in result.values
            for value in [result.values[name]]
        )
        return f"#kip-given(id: {bid}, label: {lbl}, rows: ({rows},))" if rows else ""

    if kind == "calc":
        if not result.latex:
            return ""
        body = _mitex(_calc_latex(result, width_mm))
        return (f"#kip-calc(id: {bid}, label: {lbl}, "
                f"chip: {_result_chip(block, result)})[\n{body}\n]")

    if kind == "controlled":
        from ..math.printer import render_name
        rows = ", ".join(
            "(name: {}, value: {}, source: {}, owner: {})".format(
                f"[${render_name(name)}$]", _s(fmt_quantity(value)),
                _s(var.source or "-"), _s(var.owner or "-"))
            for name, value, var in result.controlled
        )
        return f"#kip-controlled(id: {bid}, label: {lbl}, rows: ({rows},))"

    if kind == "verify":
        rows = ", ".join(
            "(id: {}, method: {}, result: {}, status: {}, passed: {})".format(
                _s(c.req_id), _s(c.method.title()),
                _s(f"{fmt_quantity(c.value)} {c.criterion}"),
                _s(c.status), "true" if c.passed else "false")
            for c in result.checks
        )
        return f"#kip-verify(id: {bid}, label: {lbl}, rows: ({rows},))"

    if kind == "requirements":
        reqs = result.content
        if reqs is None:
            return ""
        lineage = ", ".join(
            "(kind: {}, id: {}, name: {}, rev: {})".format(
                _s(it.kind), _s(it.id), _s(it.name or ""), _s(it.revision or ""))
            for it in reqs.lineage()
        )
        n_req = len(reqs.requirements)
        n_var = len(reqs.all_variables())
        summary = (f"{n_req} requirement{'s' if n_req != 1 else ''}, "
                   f"{n_var} controlled variable{'s' if n_var != 1 else ''} "
                   f"visible to this item.")
        return (f"#kip-item(id: {bid}, label: {lbl}, lineage: ({lineage},), "
                f"summary: {_s(summary)})")

    if kind == "symbolic":
        if not result.typst:
            return ""
        rows = "\n".join(f"#grid-math(math.display[${row}$])"
                         for row in result.typst.split("\\\n") if row.strip())
        return f"#kip-symbolic(id: {bid}, label: {lbl})[\n{rows}\n]"

    if kind == "plot" and isinstance(result.content, Figure):
        return (f"#kip-figure(id: {bid}, label: {lbl}, "
                f"caption: {_opt(block.meta.get('caption'))})"
                f"[\n{_figure(result.content, snapped=True)}\n]")

    if kind == "draw" and isinstance(result.content, Drawing):
        cap = result.content.caption or block.meta.get("caption")
        downloads = "(" + ", ".join(_s(name) for name in result.content.attachments) + ",)" if result.content.attachments else "()"
        return (f"#kip-drawing(id: {bid}, label: {lbl}, caption: {_opt(cap)}, downloads: {downloads})"
                f"[\n{_drawing(result.content, 'drawings/' + block.id + '.svg')}\n]")

    if kind == "table" and isinstance(result.content, Table):
        kw = _table_kwargs(result.content, assets.get(block.id))
        out = ["#kip-table(",
               f"  id: {bid}, label: {lbl}, caption: {kw['caption']},",
               f"  headers: {kw['headers']},",
               f"  rows: {kw['rows']},",
               f"  aligns: {kw['aligns']},",
               f"  tokens: {kw['tokens']},",
               f"  zebra: {kw['zebra']}, marks: {kw['marks']},"]
        if kw["total"]:
            out.append(f"  total: {kw['total']},")
        out.append(f"  note: {kw['note']},")
        out.append(f"  breakable: {kw['breakable']},")
        out.append(f"  link-to: {kw['link_to']}, link-text: {kw['link_text']},")
        out.append(")")
        return "\n".join(out)

    if kind == "sources":
        declared = result.content if isinstance(result.content, Sources) else {}
        items = []
        for key, (n, src) in sources.items():
            if declared and key not in declared:
                continue
            display = _short_url(src.url)
            items.append(
                f"(n: {n}, full: {_s(src.full())}, url: {_opt(src.url)}, "
                f"display: {_s(display.rstrip('/'))})")
        if not items:
            return ""
        return (f"#kip-references(id: {bid}, label: {lbl}, "
                f"items: ({', '.join(items)},))")

    return ""

# document


def _short_url(url: str | None, limit: int = 48) -> str:
    """Display form of a URL: scheme dropped, long tails elided.

    The link target keeps the full address; only the visible text shrinks, so
    a 90-character query string does not wrap across three lines. The head of
    a path carries the meaning, so the tail is what gets cut.
    """
    if not url:
        return ""
    text = url
    for prefix in ("https://", "http://"):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    text = text.rstrip("/")
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip("/?&-") + "…"


def collect_sources(doc: Document) -> dict[str, tuple[int, Source]]:
    """Number every declared source in document order for stable citations."""
    out: dict[str, tuple[int, Source]] = {}
    n = 1
    for block in doc.blocks:
        result = doc.results.get(block.id)
        content = getattr(result, "content", None) if result else None
        if isinstance(content, Sources):
            for key, src in content.items():
                if key not in out:
                    out[key] = (n, src)
                    n += 1
    return out


def emit_body(doc: Document, layout: Layout | None = None,
              assets: dict[str, str] | None = None, *, intro_id: str | None = None) -> str:
    layout = layout or Layout()
    assets = assets or {}
    parts: list[str] = []
    known = {b.id: b.meta.get("label", "") for b in doc.blocks}
    sources = collect_sources(doc)
    margin = layout.page.snapped_margin()

    # Placed blocks are grouped by page. Absolutely-placed content does not
    # flow, so without an explicit break every page's blocks would be drawn on
    # top of page 1.
    placed: dict[int, list[str]] = {}
    flowed: list[str] = []
    flow_columns = layout.page.columns
    opened_columns = 1

    def column_geometry(count):
        import math
        full = layout.width_hint or layout.page.content_width
        if count == 1:
            return full, 0.0
        g = layout.page.grid_step
        gutter = max(g, round(layout.page.gutter / g) * g)
        width = math.floor((full - gutter * (count - 1)) / count / g) * g
        if width <= 0:
            raise ValueError("columns leave no usable content width")
        return width, (full - count * width) / (count - 1)

    for block in doc.ordered_blocks():
        if block.id == intro_id:
            continue
        result = doc.results.get(block.id)
        if result is None:
            continue
        pos = layout.position(block.id)
        if pos is None and "columns" in block.meta:
            flow_columns = int(block.meta["columns"])
            if flow_columns not in (1, 2):
                raise ValueError(f"block {block.id}: columns must be 1 or 2")
        if pos is not None:
            width_mm = pos.w
        elif layout.width_hint is not None:
            width_mm = layout.width_hint
        elif flow_columns > 1:
            width_mm = column_geometry(flow_columns)[0]
        else:
            width_mm = None

        markup = _emit_block(block, result, known, sources, assets, width_mm)
        if not markup:
            continue
        # Template options are also available on the Python block marker.
        options = []
        for key in ("snap", "frame", "panel"):
            if key not in block.meta or (key == "panel" and block.kind != "draw"):
                continue
            value = block.meta[key].lower()
            if value not in ("true", "false"):
                raise ValueError(f"block {block.id}: {key} must be true or false")
            if result.failed and key != "snap":
                continue
            options.append(f"{key}: {value}")
        if options:
            markup = re.sub(r"^(#kip-[a-z]+\()", lambda m: m[1] + ", ".join(options) + ", ", markup, count=1)
        markup = f"#[{markup}#label({_s('blk-' + block.id)})]"

        if pos is not None:
            y = pos.y
            if block.meta.get("snap", "true").lower() != "false":
                y = round(y / layout.page.grid_step) * layout.page.grid_step
            # `place` is relative to the CONTENT box (inside the margins), but
            # layout.toml coordinates are page-absolute -- which is what someone
            # dragging a block expects. Without subtracting the margin every
            # block lands one margin too far down and to the right.
            placed.setdefault(max(1, pos.page), []).append(
                f"#place(top + left, dx: {_num(pos.x - margin - (layout.page.size[0] % layout.page.grid_step) / 2)}mm, "
                f"dy: {_num(y - max(margin, 3 * layout.page.grid_step) - ((layout.page.size[1] % layout.page.grid_step) / 2 if block.meta.get("snap", "true").lower() == "false" else 0))}mm, "
                f"box(width: {_num(pos.w)}mm)[\n{markup}\n])")
        else:
            page_break = block.meta.get("pagebreak", "false").lower()
            if page_break not in ("true", "false"):
                raise ValueError(f"block {block.id}: pagebreak must be true or false")
            if opened_columns != flow_columns or page_break == "true":
                if opened_columns > 1:
                    flowed.append("]")
                if page_break == "true":
                    flowed.append("#pagebreak(weak: true)")
                if flow_columns > 1:
                    gutter = column_geometry(flow_columns)[1]
                    flowed.append(f"#columns({flow_columns}, gutter: {_num(gutter)}mm)[")
                opened_columns = flow_columns
            flowed.append(markup)
            flowed.append("")

    if opened_columns > 1:
        flowed.append("]")

    if placed:
        for n, page in enumerate(sorted(placed)):
            if n:
                parts.append("#pagebreak()")
            parts.extend(placed[page])
        if flowed:
            parts.append("#pagebreak()")

    parts.extend(flowed)

    if layout.position_count == 0:
        parts.append('#kip-anchor("__end__", "end")')

    return "\n".join(parts)


def emit(doc: Document, layout: Layout | None = None,
         assets: dict[str, str] | None = None) -> dict[str, bytes]:
    """Emit the complete Typst project as ``{filename: bytes}``."""
    layout = layout or Layout()
    page = layout.page

    tf = page.title_fields()
    fields = ("(" + ", ".join(f"({_s(k)}, {_s(v)})" for k, v in tf) + ",)"
              if tf else "()")

    opening = [b for b in doc.ordered_blocks() if b.meta.get("wrap_title", "false") == "true"]
    if len(opening) > 1:
        raise ValueError("only one opening text block can use wrap_title=true")
    intro_id = None
    intro = "none"
    if opening:
        block = opening[0]
        if block.kind != "text" or layout.freeform:
            raise ValueError("wrap_title=true requires a text block in flow layout")
        result = doc.results[block.id]
        if not result.failed and page.title:
            intro_id = block.id
            known = {b.id: b.meta.get("label", "") for b in doc.blocks}
            content = _resolve_refs(_markdown_to_typst(result.text or ""), known, collect_sources(doc))
            intro = f"(id: {_s(block.id)}, label: {_opt(block.meta.get('label'))}, body: [{content}])"

    preamble = "\n".join([
        f'#import "@preview/mitex:{MITEX_VERSION}": *',
        f'#import "@preview/lilaq:{LILAQ_VERSION}" as lq',
        f'#import "@preview/cetz:{CETZ_VERSION}"',
        '#import "kip.typ": *',
        "",
        "#show: kip-doc.with(",
        f"  title: {_opt(page.title)},",
        f"  subtitle: {_opt(page.subtitle)},",
        f"  paper: {_s(page.paper)},",
        f"  width: {str(page.width) + 'mm' if page.width is not None else 'none'},",
        f"  height: {str(page.height) + 'mm' if page.height is not None else 'none'},",
        f"  margin: {_num(page.snapped_margin())}mm,",
        f"  grid-on: {'true' if page.grid else 'false'},",
        f"  grid-step: {_num(page.grid_step)}mm,",
        f"  frames: {'true' if page.frames else 'false'},",
        f"  size: {_num(page.font_size)}pt,",
        f"  header-left: {_opt(page.resolved_header_left())},",
        f"  header-right: {_opt(page.resolved_header_right())},",
        f"  footer-left: {_opt(page.resolved_footer_left())},",
        f"  marking: {_opt(page.marking)},",
        f"  title-fields: {fields},",
        f"  intro: {intro},",
        ")",
        "",
    ])

    files = {
        "main.typ": (preamble + emit_body(doc, layout, assets, intro_id=intro_id)).encode("utf-8"),
        "kip.typ": (TYPST_LIB / "kip.typ").read_bytes(),
    }
    for bid, result in doc.results.items():
        if isinstance(result.content, Drawing) and result.content.svg is not None:
            files[f"drawings/{bid}.svg"] = result.content.svg
    return files


def emit_debug(doc: Document, layout: Layout | None = None) -> str:
    """The generated ``main.typ`` as text, for troubleshooting."""
    return emit(doc, layout)["main.typ"].decode("utf-8")
