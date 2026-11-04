// kip document template -- engineering notebook styling.
//
// Deliberately plain: aged cream graph paper, sepia rules, near-black ink.
// Compact amber inputs, teal outputs, and transparent vector graphics.
//
// The governing rule of this file is the GRID. One configurable step drives
// the printed paper, the page margin, the baseline pitch and the height of
// every block, so text lands on the printed rules instead of drifting across
// them. `grid-snap` is where that happens; read it first.
//
// Every block emits a <kipblk> metadata tag carrying its id and position, so
// typst.query() recovers exact block geometry for the GUI canvas without a
// second layout engine.

#let kip-colors = (
  paper:      rgb("#f7f2e3"),
  grid:       rgb("#ddd0b0"),
  grid-maj:   rgb("#cbba93"),
  ink:        rgb("#17140f"),
  faint:      rgb("#6d6455"),
  rule:       rgb("#b3a488"),
  // Inputs and results use two accents -- the spreadsheet
  // convention: given values in one colour, derived values in another.
  input:      rgb("#8a5a12"),   // amber accent  = INPUT
  input-bg:   rgb("#fbf4e0"),
  input-ink:  rgb("#5d3d0a"),
  output:     rgb("#125f63"),   // teal accent   = RESULT
  output-bg:  rgb("#eaf3f2"),
  output-ink: rgb("#0d4245"),
  link:       rgb("#123a6b"),
  card:       rgb("#fdfbf4"),   // opaque panel behind tables and matrices
  chip:       rgb("#ece2c8"),
  ok:         rgb("#1c6b3e"),
  fail:       rgb("#9b2b20"),
)

// ---------------------------------------------------------------------------
// the grid
// ---------------------------------------------------------------------------

#let kip-grid = state("kip-grid-step", 5mm)
#let kip-frames = state("kip-frames", false)
#let kip-base = state("kip-base", 10pt)
#let kip-snapping = state("kip-snapping", true)

// Width is a maximum, not an empty column around a small canvas.
#let drawing-width(limit, body) = context layout(size => {
  let m = measure(body)
  if m.width == 0pt { return body }
  let f = calc.min(1, calc.min(limit, size.width) / m.width)
  scale(x: f * 100%, y: f * 100%, reflow: true, body)
})

#let graph-paper(step: 5mm, major: 5) = {
  let maj = step * major
  tiling(size: (maj, maj), {
    for i in range(major) {
      place(line(start: (i * step, 0mm), end: (i * step, maj),
                 stroke: 0.3pt + kip-colors.grid))
      place(line(start: (0mm, i * step), end: (maj, i * step),
                 stroke: 0.3pt + kip-colors.grid))
    }
    place(line(start: (0mm, 0mm), end: (0mm, maj),
               stroke: 0.5pt + kip-colors.grid-maj))
    place(line(start: (0mm, 0mm), end: (maj, 0mm),
               stroke: 0.5pt + kip-colors.grid-maj))
  })
}

// The block a following grid-snap belongs to, set by kip-anchor.
#let kip-block-id = state("kip-block-id", none)

// Where a block ends, for the layout report `kip check` prints. It is placed
// inside the block, out of flow, so it stays with the content it marks.
#let kip-end(id) = place(context {
  let p = here().position()
  [#metadata((type: "end", id: id, page: p.page, y: p.y / 1mm)) <kiplayout>]
})

// Sections occupy whole grid cells. This local measurement avoids a chain of
// page-position-dependent layout passes (Typst only allows five such passes).
//
// `breakable: auto` keeps a block whole unless it is taller than a third of
// the page; a taller one breaks between its rows, which are whole cells each,
// rather than leaving most of a page empty above it.
#let grid-snap(body, frame: auto, snap: true, breakable: false) = context {
  let g = kip-grid.get()
  let framed = if frame == auto { kip-frames.get() } else { frame }
  let id = kip-block-id.get()
  layout(size => {
    let inset-x = if framed { 2.5mm } else { 0pt }
    let content = [#kip-snapping.update(snap)#body#kip-snapping.update(true)]
    // A multi-page table repeats its header. Its total height cannot be
    // measured in one region without shortening the final rows on later pages.
    let m = if breakable == true { none } else {
      measure(block(width: size.width - 2 * inset-x, spacing: 0pt, content))
    }
    let breakable = breakable == true or (breakable == auto and m.height > size.height / 3)
    let height = if breakable { auto } else {
      calc.ceil(m.height / g) * g + if framed { g } else { 0pt }
    }
    block(width: 100%, height: height,
      spacing: g, breakable: breakable,
      stroke: if framed { 0.4pt + black } else { none }, radius: 3pt,
      inset: (x: inset-x), [#content#if id != none { kip-end(id) }])
    kip-block-id.update(none)
  })
}

// ---------------------------------------------------------------------------
// block plumbing
// ---------------------------------------------------------------------------

#let kip-anchor(id, kind) = {
  kip-block-id.update(id)
  context {
    let p = here().position()
    [#metadata((id: id, kind: kind, page: p.page,
                x: p.x / 1mm, y: p.y / 1mm)) <kipblk>]
  }
}

// Scale content down when wider than its container. Engineering equations are
// unbreakable single lines, so a wide substitution step would otherwise
// overflow a narrow column and be clipped.
#let fit-width(body) = context layout(size => {
  let m = measure(body)
  if m.width > size.width and m.width > 0pt {
    let f = size.width / m.width
    block(width: 100%, height: m.height * f,
          scale(x: f * 100%, y: f * 100%, origin: top + left, body))
  } else { body }
})

// Inline math can be taller than a line of text. Up to half the leading it may
// overlap the gap between lines; beyond that its line grows by whole cells, so
// the rest of the paragraph stays on the rules.
#let inline-math(it, base, pitch, g) = {
  // The same box-and-baseline measurement grid-math uses, here for both sides.
  // Math already reports at least the text's line edges, so most formulas
  // fit and return unchanged.
  let lift = measure([#box(height: 1000pt, baseline: 1000pt)#it]).height - 1000pt
  let drop = measure([#box(height: 1000pt)#it]).height - 1000pt
  if lift <= 0.75 * base and drop <= 0.25 * base { return it }
  let slack = (pitch - base) / 2
  let up = 0.75 * base + calc.ceil(calc.max(0pt, lift - 0.75 * base - slack) / g) * g
  let down = 0.25 * base + calc.ceil(calc.max(0pt, drop - 0.25 * base - slack) / g) * g
  // A box takes its baseline from its content's first line; the (possibly
  // negative) pad puts that line `up` below the box's top.
  box(height: up + down, pad(top: up - lift, it))
}

// Each text row has a fixed baseline and a whole-cell advance. Small fonts
// retain the document line metrics, so labels and provenance share the rules.
#let grid-text(body, above: 0pt, below: 0pt) = block(above: above, below: below, context layout(size => {
  let g = kip-grid.get()
  let base = kip-base.get()
  let pitch = calc.ceil(base.to-absolute() / g) * g
  let content = [#show par: it => it
#set text(top-edge: 0.75 * base, bottom-edge: -0.25 * base)
#body]
  let m = measure(block(width: size.width, spacing: 0pt, content))
  if kip-snapping.get() {
    let pad = pitch - 0.75 * base
    let height = calc.ceil((pad + m.height - 0.25 * base) / g) * g
    // Quantise using the final inset, rather than a fixed block height.
    // Fixed-height paragraphs can compress their last fragment after a page
    // or column break, especially when inline fractions increase line height.
    block(width: 100%, spacing: 0pt,
      inset: (top: pad, bottom: height - pad - m.height), content)
  } else { block(spacing: 0pt, content) }
}))

// Display type -- the title -- set like body text: each baseline on a rule,
// the first as high as its ascent allows, wrapped lines a whole number of
// cells apart. The descent of the last line hangs into the next cell.
#let grid-line(body, size: 10pt) = block(spacing: 0pt, breakable: false, context layout(bounds => {
  let g = kip-grid.get()
  let pitch = calc.ceil(size / g) * g
  let up = calc.ceil(0.75 * size / g) * g
  let content = [#show par: it => it
#set text(size: size, top-edge: 0.75 * size, bottom-edge: -0.25 * size)
#set par(justify: false, leading: pitch - size)
#body]
  let m = measure(block(width: bounds.width, spacing: 0pt, content))
  block(width: 100%, spacing: 0pt, inset: (top: up - 0.75 * size),
    height: calc.ceil((up + m.height - size) / g) * g, content)
}))

// Center the actual text bounds within a whole number of paper cells.
#let grid-cell(body, chip: false, fill: none, stroke: none) = block(spacing: 0pt, context layout(size => {
  // Measure the same styled content we render. Surrounding set/show rules
  // otherwise affect the rendered paragraph differently from measure().
  let styled(leading) = [#show par: it => it
#set text(top-edge: "cap-height", bottom-edge: "descender")
#set par(justify: false, leading: leading)
#body]
  let g = kip-grid.get()
  let pad = 2pt
  let width = if chip { auto } else { size.width }
  // Wrapped text keeps the paper's pitch: leading never changes where lines
  // break, so two measurements give the line count and the height of a line,
  // and each line then centres in a cell of its own. A single line keeps the
  // document leading, which math measures against.
  let normal = par.leading.to-absolute()
  let flat = measure(block(width: width, spacing: 0pt, styled(normal)))
  let lines = calc.round((measure(block(width: width, spacing: 0pt, styled(normal + g))).height - flat.height) / g) + 1
  let leading = if lines > 1 {
    calc.max(0pt, g - (flat.height - (lines - 1) * normal) / lines)
  } else { normal }
  let content = styled(leading)
  let m = (width: flat.width, height: flat.height + (lines - 1) * (leading - normal))
  let ht = calc.ceil((m.height + 2 * pad) / g) * g
  block(width: if chip { m.width + 10pt } else { 100% }, height: ht,
    spacing: 0pt, breakable: false, inset: (x: if chip { 5pt } else { 0pt }, y: pad),
    fill: fill, stroke: stroke, outset: if chip { -1pt } else { 0pt }, radius: 2pt, align(horizon, content))
}))

#let equation-number = counter("kip-equation")

// Inline math has real ascent/descent (fractions and scripts). A zero-width
// strut isolates its ascent, allowing the equation baseline to meet a rule.
// A stacked equation's continuation rows are unnumbered and left-aligned so
// their equals signs line up under the first row's.
//
// `rows` are the same equation one step per row. They replace it when it is
// too wide to read at 85% of full size, rather than shrinking it further;
// whatever must still shrink is reported by `kip check`.
//
// An equation never breaks across pages, and `sticky` keeps it on the page of
// what follows it: the last row of a calculation stays with its result.
#let grid-math(body, numbered: true, stacked: false, rows: none, sticky: false) = block(
  spacing: 0pt, breakable: false, sticky: sticky, context layout(size => {
  show par: it => it
  let g = kip-grid.get()
  let natural = measure(body)
  let f = if natural.width > 0pt { calc.min(1, (size.width - 12mm) / natural.width) } else { 1 }
  if rows != none and f < 0.85 {
    for (i, row) in rows.enumerate() {
      grid-math(row, numbered: numbered and i == 0, stacked: true)
    }
  } else {
    let content = text(size: text.size * f, top-edge: 0.75em, bottom-edge: -0.25em, body)
    set text(size: text.size * f, top-edge: 0.75em, bottom-edge: -0.25em)
    let m = measure(content)
    let ascent = measure([#box(height: 1000pt, baseline: 1000pt)#content]).height - 1000pt
    let pad = if kip-snapping.get() { calc.ceil(ascent / g) * g - ascent } else { 0pt }
    if numbered {
      block(width: 100%, height: 0pt, spacing: 0pt)[#equation-number.step()#place(top + right, dy: pad + ascent - 6pt, text(size: 8pt, top-edge: 6pt, bottom-edge: -2pt)[(#context equation-number.display("1"))])]
    }
    let shrunk = if f < 0.85 {
      let p = here().position()
      let n = if numbered { equation-number.get().first() + 1 } else { none }
      [#metadata((type: "shrunk", page: p.page, y: p.y / 1mm, scale: f, number: n)) <kiplayout>]
    }
    block(width: 100%, height: if kip-snapping.get() { calc.ceil((pad + m.height) / g) * g } else { m.height },
      spacing: 0pt, inset: (top: pad, left: if stacked { 2 * g } else { 0pt }),
      align(if stacked { left } else { center }, [#content#shrunk]))
  }
}))

// Graphics have intrinsic coordinates; quantise only their occupied height.
#let grid-graphic(body) = block(spacing: 0pt, context layout(size => {
  let m = measure(block(width: size.width, spacing: 0pt, body))
  let g = kip-grid.get()
  block(width: 100%, height: calc.ceil(m.height / g) * g,
    spacing: 0pt, body)
}))

// Block content written into prose -- a quote, a native table or grid, a
// figure -- takes a cell of air on each side and whole cells of height, so the
// text after it stays on the rules.
#let grid-display(body) = context {
  let g = kip-grid.get()
  block(width: 100%, above: g, below: g, layout(size => {
    let h = measure(block(width: size.width, spacing: 0pt, body)).height
    block(width: 100%, spacing: 0pt, inset: (bottom: calc.ceil(h / g) * g - h), body)
  }))
}

// Prose as text cells and the opening text write it. A display equation sets
// like a calculation row: centred, its baseline on a rule. A block quote's
// text is not a paragraph (it has no paragraph break), so it is set on the
// rules here rather than by the paragraph rule.
#let kip-prose(body) = context {
  let g = kip-grid.get()
  let base = kip-base.get()
  let pitch = calc.ceil(base.to-absolute() / g) * g
  // Inline math is set before its paragraph is, so this rule lives here rather
  // than in grid-text. Display rows are labelled to skip it: grid-math already
  // fits them to the rules.
  show math.equation.where(block: false): it => {
    if it.at("label", default: none) == <kip-display> { it }
    else { inline-math(it, base, pitch, g) }
  }
  // A cell of air above. Below, the row's descent cell is usually air enough;
  // a deep row (a tall denominator) takes one more cell, so the white space
  // under the formula matches the space over it to within half a cell.
  show math.equation.where(block: true): it => {
    let row = [#math.equation(block: false, math.display(it.body))<kip-display>]
    let lift = measure([#box(height: 1000pt, baseline: 1000pt)#row]).height - 1000pt
    let drop = measure([#box(height: 1000pt)#row]).height - 1000pt
    let over = g + calc.ceil(lift / g) * g - lift - 0.25 * base
    let under = calc.ceil(drop / g) * g + pitch - 0.75 * base - drop
    block(width: 100%, above: g, below: if under + g / 2 < over { g } else { 0pt },
      grid-math(row, numbered: false))
  }
  show quote.where(block: true): it => grid-display(pad(x: 1em, {
    grid-text(it.body)
    if it.attribution != none { grid-text(align(end)[--- #it.attribution]) }
  }))
  // Half the leading above and below each line makes a one-line row exactly one
  // cell, and wrapped lines keep the document pitch.
  set table(inset: (x: 5pt, y: (pitch - base) / 2))
  show table: grid-display
  show grid: grid-display
  show figure: grid-display
  body
}

// A numbered section heading. Levels beyond the three styled below keep the
// body size and simply indent through the numbering, which is what a deep
// sub-sub-section wants: the number carries the hierarchy, not the type size.
#let kip-section(level, body) = heading(level: level, body)

#let block-title(label, color: none) = {
  if label != none and label != "" {
    block(spacing: 0pt, sticky: true, grid-cell(text(size: 7.2pt,
      fill: if color == none { kip-colors.faint } else { color },
      weight: "semibold", tracking: 0.7pt, upper(label))))
  }
}

// One strip for both inputs and results: a thin accent rule on the left, a
// tinted ground, no heavy border. The tag rides at the end of the first line
// rather than claiming a row of its own.
#let kip-strip(tag, accent, bg, ink, body, label: none) = block(
  width: 100%, spacing: 0pt, breakable: false,
  fill: bg, stroke: (left: 1.6pt + accent),
  inset: (left: 5pt, right: 4pt, top: 1.5pt, bottom: 1.5pt),
)[
  #grid(columns: (1fr, auto), align: (start + horizon, end + top), gutter: 5pt,
    text(fill: ink, fit-width(body)),
    text(size: 6pt, fill: accent, weight: "bold", tracking: 0.8pt,
         upper(if label != none { label } else { tag })),
  )
]

// The value a calc block produced, rendered in the output accent.
#let result-chip(name, value) = align(right, grid-cell(chip: true,
  fill: kip-colors.output-bg, stroke: 0.5pt + kip-colors.output,
  text(size: 8.2pt, fill: kip-colors.output-ink, weight: "medium")[#name = #value]))

// ---------------------------------------------------------------------------
// block kinds
// ---------------------------------------------------------------------------

#let kip-text(id: "", label: none, snap: true, frame: auto, body) = {
  kip-anchor(id, "text")
  grid-snap(frame: frame, snap: snap, breakable: true)[
    #block-title(label)
    #kip-prose(body)
    #parbreak()
  ]
}

#let kip-calc(id: "", label: none, chip: none, snap: true, frame: auto, body) = {
  kip-anchor(id, "calc")
  grid-snap(frame: frame, snap: snap, breakable: auto)[
    #block-title(label)
    #body
    #if chip != none { chip }
  ]
}

#let kip-given(id: "", label: none, snap: true, frame: auto, rows: ()) = {
  kip-anchor(id, "given")
  grid-snap(frame: frame, snap: snap, breakable: auto)[
    #block-title(label, color: kip-colors.input)
    #for r in rows {
      grid-cell(chip: true, stroke: 0.4pt + black,
        text(fill: kip-colors.ink)[#r.name = #r.value])
    }
  ]
}

// An explicit results strip, the visual mirror of an input.
#let kip-result(id: "", label: none, snap: true, frame: auto, body) = {
  kip-anchor(id, "result")
  grid-snap(frame: frame, snap: snap, kip-strip(
    "result", kip-colors.output, kip-colors.output-bg, kip-colors.output-ink,
    body, label: label))
}

// Controlled inputs: the same input strip, but every row carries provenance --
// which requirement levies the value and which item owns it.
#let kip-controlled(id: "", label: none, rows: (), snap: true, frame: auto) = {
  kip-anchor(id, "controlled")
  grid-snap(frame: frame, snap: snap, breakable: auto)[
    #block-title(label, color: kip-colors.input)
    #for r in rows {
      // A bare grid takes paragraph spacing (one cell) above and below.
      block(spacing: 0pt, grid(columns: (auto, 1fr), gutter: 5pt, align: horizon,
        grid-cell(chip: true, stroke: 0.4pt + black,
          text(fill: kip-colors.ink)[#r.name = #r.value]),
        grid-cell(text(size: 7pt, fill: kip-colors.faint)[#r.source #sym.dot.c #r.owner])))
    }
  ]
}

// Product-breakdown lineage for the item this document covers.
#let kip-item(id: "", label: none, lineage: (), summary: none,
              snap: true, frame: auto) = {
  kip-anchor(id, "requirements")
  grid-snap(frame: frame, snap: snap, block(
    width: 100%, spacing: 0pt, breakable: false,
    stroke: 0.5pt + kip-colors.rule, fill: kip-colors.card,
    inset: (x: 7pt), radius: 1pt)[
    #block-title(if label == none { "Item" } else { label })
    #for (i, it) in lineage.enumerate() {
      grid-text[
        #h(i * 5mm)
        #text(size: 7pt, fill: kip-colors.faint, tracking: 0.5pt, upper(it.kind))
        #h(3pt)
        #text(size: 9pt, weight: "bold", it.id)
        #h(3pt)
        #text(size: 8.5pt, fill: kip-colors.faint, it.name)
        #if it.rev != "" { text(size: 7.5pt, fill: kip-colors.faint)[ (rev #it.rev)] }
      ]
    }
    #if summary != none {
      grid-cell(text(size: 8pt, fill: kip-colors.faint, summary))
    }
  ])
}

#let kip-symbolic(id: "", label: none, snap: true, frame: auto, body) = {
  kip-anchor(id, "symbolic")
  grid-snap(frame: frame, snap: snap, breakable: auto)[
    #block-title(label)
    #body
  ]
}

// A plot carries its own opaque data area (lilaq's `fill`), so the paper grid
// never shows through its gridlines. Outside that data area there is nothing
// to hide -- axis labels and captions belong on the paper like any other text,
// so this block draws no panel at all.
#let kip-figure(id: "", label: none, caption: none, snap: true, frame: auto,
                body) = {
  kip-anchor(id, "plot")
  grid-snap(frame: frame, snap: snap)[
    #block-title(label)
    #grid-graphic(context layout(size => {
      let g = kip-grid.get()
      let fitted = fit-width(body)
      let m = measure(fitted)
      let dx = calc.max(0pt, calc.floor((size.width - m.width) / (2 * g)) * g)
      block(spacing: 0pt, inset: (left: dx), fitted)
    }))
    #if caption != none {
      grid-text(align(center, text(size: 8pt, fill: kip-colors.faint, style: "italic", caption)))
    }
  ]
}

// A CeTZ drawing sits directly on the paper. `panel: true` puts a ground
// behind it -- shrink-wrapped to the drawing itself, never the full column
// width, because a drawing is rarely as wide as its block.
#let kip-drawing(id: "", label: none, caption: none, panel: false,
                 snap: true, frame: auto, downloads: (), body) = {
  kip-anchor(id, "draw")
  grid-snap(frame: frame, snap: snap)[
    #block-title(label)
    #grid-graphic(align(center, if panel {
      box(fill: kip-colors.card, stroke: 0.4pt + kip-colors.rule,
          inset: 4pt, radius: 1pt, fit-width(body))
    } else {
      fit-width(body)
    }))
    #if caption != none {
      grid-text(align(center, text(size: 8pt, fill: kip-colors.faint, style: "italic", caption)))
    }
    #for filename in downloads {
      grid-cell(align(center, text(size: 7.6pt, link(filename,
        [Open #filename#if filename.ends-with(".dxf") [ (mm, 1:1)]]))))
    }
  ]
}

// A structure diagram in a table cell, at the size kip drew it.
#let cell-image(data, width, height) = box(image(data, format: "svg", width: width, height: height))

// A sequence listing: rows of letters in groups, each row numbered by its
// first position and set on the rules like body text. As many groups fit a
// row as the column allows. Marked positions take their legend's fill.
#let kip-sequence(id: "", label: none, caption: none, letters: "", start: 1, group: 10,
                  marks: (:), legend: (:), snap: true, frame: auto) = {
  kip-anchor(id, "draw")
  grid-snap(frame: frame, snap: snap, breakable: auto)[
    #block-title(label)
    #context layout(size => {
      let mono(body) = text(font: ("DejaVu Sans Mono",), size: 8.4pt, body)
      let chars = letters.clusters()
      let n = chars.len()
      let last = str(start + calc.max(0, n - 1))
      let number-width = measure(text(size: 7.4pt, last)).width + 3mm
      let space = measure(mono("M M")).width - 2 * measure(mono("M")).width
      let group-width = measure(mono("M" * group)).width + space
      let per = calc.max(1, calc.floor((size.width - number-width + space) / group-width)) * group
      for first in range(0, n, step: per) {
        let row = range(first, calc.min(n, first + per)).map(i => {
          let key = marks.at(str(start + i), default: none)
          let c = mono(chars.at(i))
          let c = if key == none { c } else { highlight(fill: legend.at(key).at(0), extent: 0.6pt, c) }
          if calc.rem(i - first, group) == group - 1 and i < n - 1 { c + h(space) } else { c }
        })
        grid-text(grid(columns: (number-width, 1fr),
          align(right, text(size: 7.4pt, fill: kip-colors.faint, str(start + first)) + h(3mm)),
          row.join()))
      }
    })
    #if legend.len() > 0 {
      grid-text(text(size: 7.6pt, fill: kip-colors.faint, legend.values().map(((fill, words)) =>
        [#box(width: 7pt, height: 7pt, fill: fill, radius: 1pt, baseline: 1pt) #words]).join(h(4mm))))
    }
    #if caption != none {
      grid-text(align(center, text(size: 8pt, fill: kip-colors.faint, style: "italic", caption)))
    }
  ]
}

#let kip-error(id: "", message: "", detail: "", snap: true) = {
  kip-anchor(id, "error")
  grid-snap(frame: false, snap: snap, block(
    width: 100%, spacing: 0pt, fill: rgb("#fbeeea"),
    stroke: 0.6pt + kip-colors.fail, inset: 7pt, radius: 2pt)[
    #text(fill: kip-colors.fail, weight: "bold", size: 8.5pt)[block #raw(id) failed]
    #linebreak()
    #text(size: 8.5pt, raw(message))
    #if detail != "" [
      #linebreak() #text(size: 7.2pt, fill: kip-colors.faint, raw(detail))
    ]
  ])
}

// ---------------------------------------------------------------------------
// tables
// ---------------------------------------------------------------------------

// Allocate width to actual text rather than making every column equally wide.
#let table-columns(headers, rows, tokens, available) = {
  let n = headers.len()
  let natural = range(n).map(i => calc.max(..(rows + (headers,)).map(r => measure(text(size: 8.4pt, r.at(i))).width)) + 12pt)
  let minimum = range(n).map(i => {
    if tokens.len() == n and tokens.at(i).len() > 0 {
      calc.max(..tokens.at(i).map(t => measure(text(size: 8.4pt, t)).width)) + 12pt
    } else { calc.min(natural.at(i), available / n) }
  })
  let widths = minimum
  let total = widths.sum()
  if total >= available { return widths.map(w => w / total * available) }
  let remaining = available - total
  // Water-fill toward natural widths, with most space going to prose columns.
  for _ in range(n + 1) {
    let deficits = range(n).map(i => calc.max(0pt, natural.at(i) - widths.at(i)))
    let demand = deficits.sum()
    if demand <= 0pt { break }
    let amount = calc.min(remaining, demand)
    widths = range(n).map(i => widths.at(i) + amount * (deficits.at(i) / demand))
    remaining -= amount
    if remaining <= 0pt { break }
  }
  widths.map(w => w + remaining / n)
}

#let kip-table(
  id: "", label: none, caption: none,
  headers: (), rows: (), aligns: (), tokens: (), zebra: true,
  marks: (:), total: none, note: none, link-to: none, link-text: none,
  breakable: false, snap: true, frame: auto,
) = {
  kip-anchor(id, "table")
  let ncol = headers.len()
  let al = if aligns.len() == ncol { aligns } else { (right,) * ncol }

  grid-snap(frame: frame, snap: snap, breakable: breakable)[
    #block-title(label)
    #context layout(size => block(width: 100%, fill: kip-colors.card, stroke: 0.4pt + kip-colors.rule,
           inset: 0pt, radius: 1pt, clip: false, breakable: breakable, table(
      columns: table-columns(headers, rows, tokens, size.width),
      stroke: none,
      inset: (x: 6pt, y: 0pt),
      // Top, so a single-line cell shares the first baseline of a wrapped one.
      align: (col, _) => al.at(col) + top,
      fill: (col, row) => {
        if row == 0 { kip-colors.chip }
        else if zebra and calc.rem(row, 2) == 0 { rgb("#0000000a") }
        else { none }
      },
      table.header(..headers.map(h => grid-cell(text(size: 8.2pt, weight: "semibold", h)))),
      table.hline(y: 0, stroke: 0.7pt + kip-colors.ink),
      ..rows.enumerate().map(((i, r)) => {
        let mark = marks.at(str(i), default: none)
        let col = if mark == "ok" { kip-colors.ok }
                  else if mark == "fail" { kip-colors.fail }
                  else { kip-colors.ink }
        r.map(c => grid-cell(text(size: 8.4pt, fill: col, c)))
      }).flatten(),
      ..if total != none {
        (table.hline(stroke: 0.5pt + kip-colors.ink),)
          + total.map(c => grid-cell(text(size: 8.4pt, weight: "bold", c)))
      } else { () },
    )))
    #if note != none or link-to != none {
      grid-text(text(size: 7.6pt, fill: kip-colors.faint)[
        #if note != none { note }
        #if note != none and link-to != none [ #h(6pt) ]
        #if link-to != none {
          link(link-to, text(fill: kip-colors.input, weight: "medium", link-text))
        }
      ])
    }
    #if caption != none {
      grid-text(text(size: 8pt, fill: kip-colors.faint,
                             style: "italic", caption))
    }
  ]
}

// ---------------------------------------------------------------------------
// sources
// ---------------------------------------------------------------------------

// A citation inside a paragraph must not break the line rhythm, so it renders
// as a compact superscript marker; the reference list carries the detail.
#let kip-cite(n, short, url: none) = {
  let body = super(text(size: 0.92em, fill: kip-colors.link, weight: "medium")[[#n]])
  if url != none { link(url, body) } else { body }
}

#let kip-references(id: "", label: none, items: (), snap: true, frame: auto) = {
  kip-anchor(id, "sources")
  grid-snap(frame: frame, snap: snap, breakable: true)[
    #block-title(if label == none { "References" } else { label })
    #for it in items {
      grid-text(text(size: 8.4pt)[
        #box(width: 7mm, text(fill: kip-colors.faint)[[#it.n]])
        #it.full
        #if it.url != none [
          #h(3pt) #link(it.url, text(fill: kip-colors.link, it.display))
        ]
      ])
    }
  ]
}

// ---------------------------------------------------------------------------
// page furniture
// ---------------------------------------------------------------------------

#let marking-banner(body) = if body != none and body != "" {
  block(width: 100%, inset: (y: 2.5pt),
    align(center, text(size: 7.4pt, weight: "bold", tracking: 1.2pt,
                       fill: kip-colors.fail, upper(body))))
}

// NOTE: parameters must not be named `left`/`right`/`center` -- they would
// shadow Typst's alignment constants inside this scope, and `align: (left,
// right)` would then resolve to the *strings* passed in.
#let running-head(lead: none, trail: none, marking: none) = block(spacing: 0pt)[
  #grid(columns: (55%, 45%), align: (start, end),
    grid-cell(text(size: 7.8pt, fill: kip-colors.faint, if lead == none { "" } else { lead })),
    grid-cell(text(size: 7.8pt, fill: kip-colors.faint, if trail == none { "" } else { trail })))
]

#let page-foot(lead: none, marking: none) = block(spacing: 0pt)[
  #grid(columns: (45%, 10%, 45%), align: (start, center, end),
    grid-cell(text(size: 7.4pt, fill: kip-colors.faint, if lead == none { "" } else { lead })),
    grid-cell(context text(size: 7.4pt, fill: kip-colors.faint)[#counter(page).display("1") of #counter(page).final().first()]),
    [])
]

// Drawing-style title block, top right of page 1.
#let title-block(fields) = context {
  if fields.len() == 0 { return none }
  block(width: calc.ceil(60mm / kip-grid.get()) * kip-grid.get(), spacing: 0pt, stroke: 0.6pt + kip-colors.ink,
    table(
      columns: (30%, 70%),
      stroke: 0.35pt + kip-colors.rule,
      inset: (x: 5pt, y: 0pt),
      align: (right, left),
      ..fields.map(f => (
        grid-cell(text(size: 7pt, fill: kip-colors.faint, tracking: 0.4pt, upper(f.at(0)))),
        grid-cell(text(size: 8pt, fill: kip-colors.ink, weight: "medium", f.at(1))),
      )).flatten(),
    ))
}

// ---------------------------------------------------------------------------
// template
// ---------------------------------------------------------------------------

// Split only plain text and sequences. Styled spans, links, math, tables and
// grids remain intact, so wrapping never drops their formatting, destinations
// or structure.
#let sequence = [*a* b].func()
#let opening-tokens(body) = {
  if body.func() == text {
    body.text.matches(regex("\\S+\\s*|\\s+")).map(m => text(m.text))
  } else if body.func() == sequence {
    body.children.map(opening-tokens).flatten()
  } else { (body,) }
}

#let opening-flow(body, narrow, height) = context layout(size => {
  let tokens = opening-tokens(body)
  let lo = 0
  let hi = tokens.len()
  // Find the last complete word that fits beside the metadata table.
  while lo < hi {
    let mid = calc.ceil((lo + hi + 1) / 2)
    let candidate = tokens.slice(0, mid).join() + parbreak()
    let m = measure(block(width: narrow, spacing: 0pt, candidate))
    if m.height <= height { lo = mid } else { hi = mid - 1 }
  }
  if height > 0pt {
    block(width: narrow, height: height, spacing: 0pt,
      tokens.slice(0, lo).join() + parbreak())
  }
  if lo < tokens.len() {
    // Splitting exactly between paragraphs must keep the blank row between
    // them, unless the space left beside the title fields already gives one.
    let spaced = tokens.filter(t => t.func() != [ ].func())
    let edge = tokens.slice(0, lo).filter(t => t.func() != [ ].func())
    let used = measure(block(width: narrow, spacing: 0pt, tokens.slice(0, lo).join() + parbreak())).height
    let gap = edge.len() > 0 and edge.len() < spaced.len() and height - used < kip-grid.get() and (
      edge.last().func() == parbreak or spaced.at(edge.len()).func() == parbreak)
    block(width: 100%, above: if gap { kip-grid.get() } else { 0pt }, below: 0pt,
      tokens.slice(lo).join() + parbreak())
  }
})

// The title and subtitle on the rules, with a heavy rule one cell below.
#let title-heading(title, subtitle) = context {
  grid-line(size: 17pt, text(weight: "bold", title))
  if subtitle != none { grid-line(size: 9.5pt, text(fill: kip-colors.faint, subtitle)) }
  block(height: kip-grid.get(), spacing: 0pt, width: 100%,
    place(bottom + left, line(length: 100%, stroke: 0.9pt + kip-colors.ink)))
}

#let kip-doc(
  title: none,
  subtitle: none,
  paper: "us-letter",
  width: none,
  height: none,
  margin: 16mm,
  grid-on: true,
  grid-step: 5mm,
  frames: false,
  section-numbering: "1.1",
  font: ("Libertinus Serif", "DejaVu Serif", "Times New Roman"),
  size: 10pt,
  header-left: none,
  header-right: none,
  footer-left: none,
  marking: none,
  title-fields: (),
  intro: none,
  body,
) = {
  kip-base.update(size)
  kip-grid.update(grid-step)
  kip-frames.update(frames)

  let sizes = ("us-letter": (215.9mm, 279.4mm), "us-legal": (215.9mm, 355.6mm), "a4": (210mm, 297mm), "a3": (297mm, 420mm))
  let dims = if width != none and height != none { (width, height) } else { sizes.at(paper) }
  let ox = (dims.at(0) - calc.floor(dims.at(0) / grid-step) * grid-step) / 2
  let oy = (dims.at(1) - calc.floor(dims.at(1) / grid-step) * grid-step) / 2
  let top-margin = calc.max(margin, 3 * grid-step)
  set page(width: dims.at(0), height: dims.at(1),
    margin: (left: margin + ox, right: margin + ox, top: top-margin + oy, bottom: top-margin + oy),
    fill: kip-colors.paper,
    background: {
      if grid-on { place(top + left, dx: ox, dy: oy,
        rect(width: dims.at(0) - 2 * ox, height: dims.at(1) - 2 * oy, stroke: none, fill: graph-paper(step: grid-step))) }
      place(top + left, dx: margin + ox, dy: oy + grid-step,
        block(width: dims.at(0) - 2 * (margin + ox), spacing: 0pt)[
          #running-head(lead: header-left, trail: header-right)
        ])
      place(top + left, dx: margin + ox, dy: oy + 2 * grid-step,
        line(length: dims.at(0) - 2 * (margin + ox), stroke: 0.4pt + kip-colors.rule))
      place(top + left, dx: margin + ox, dy: dims.at(1) - oy - 2 * grid-step,
        block(width: dims.at(0) - 2 * (margin + ox), spacing: 0pt)[
          #place(line(length: 100%, stroke: 0.4pt + kip-colors.rule))
          #page-foot(lead: footer-left)
        ])
      if marking != none {
        place(top, dy: oy,
          block(width: dims.at(0), spacing: 0pt, align(center, block(height: grid-step, spacing: 0pt, align(horizon, text(size: 7.4pt, top-edge: "bounds", bottom-edge: "bounds", weight: "bold", fill: kip-colors.fail, upper(marking)))))))
        place(bottom, dy: -oy, block(width: dims.at(0), spacing: 0pt, align(center, block(height: grid-step, spacing: 0pt, align(horizon, text(size: 7.4pt, top-edge: "bounds", bottom-edge: "bounds", weight: "bold", fill: kip-colors.fail, upper(marking)))))))
      }
    },
  )

  // --- baseline grid -------------------------------------------------------
  // Pin the line box to exactly 1em (top-edge minus bottom-edge), then choose
  // the leading so that baseline-to-baseline equals the paper's grid pitch.
  // Combined with `grid-snap`'s whole-cell block heights, every line of body
  // text lands on a printed rule.
  set text(font: font, size: size, fill: kip-colors.ink,
           top-edge: 0.75 * size, bottom-edge: -0.25 * size)
  set par(justify: true, leading: calc.ceil(size / grid-step) * grid-step - size, spacing: grid-step)
  show par: it => context {
    let pitch = calc.ceil(size / grid-step) * grid-step
    // List line boxes already occupy a whole pitch. An identity show rule
    // inside a list does not cancel this outer paragraph transformation.
    if text.top-edge == pitch and text.bottom-edge == 0pt { it }
    // A blank row follows each paragraph. Spacing only below means a label or
    // heading keeps its text on the next row, and the row falls away at the
    // end of a cell.
    else { grid-text(it, below: grid-step) }
  }
  show math.equation.where(block: true): set block(spacing: grid-step)

  // Tight lists do not use the paragraph show rule. Give their text and
  // markers the same baseline pitch directly, including nested lists.
  let grid-list(body) = context {
    let base = size
    let pitch = calc.ceil(base / grid-step) * grid-step
    set text(top-edge: pitch, bottom-edge: 0pt)
    set par(leading: 0pt)
    body
  }
  set list(spacing: 0pt)
  set enum(spacing: 0pt)
  show list.where(tight: false): set list(spacing: grid-step)
  show enum.where(tight: false): set enum(spacing: grid-step)
  // A list ends with the same blank row as a paragraph. A nested list's row
  // falls away at the end of its item.
  show list: set block(above: 0pt, below: grid-step)
  show enum: set block(above: 0pt, below: grid-step)
  show list: grid-list
  show enum: grid-list
  show raw.where(block: true): set block(above: 0pt, below: 0pt)
  show raw.where(block: true): it => grid-text(it, above: grid-step, below: grid-step)

  // Headings retain the common line metrics.
  // One rule branching on level, rather than one rule per level: a document
  // may nest as deeply as it likes, and levels past the third share a
  // treatment because by then the number carries the hierarchy.
  let heading-style(level) = if level == 1 {
    (1.22 * size, "bold", "normal", true)
  } else if level == 2 {
    (1.06 * size, "bold", "normal", true)
  } else {
    (size, "semibold", "italic", false)
  }

  set heading(numbering: if section-numbering in (none, "") { none } else { section-numbering })
  show heading: set block(above: 0pt, below: 0pt)
  show heading: it => {
    let (hs, weight, style, ruled) = heading-style(it.level)
    let shown = if it.numbering == none { it.body } else {
      [#counter(heading).display(it.numbering)#h(0.6em)#it.body]
    }
    // Whole grid cells of air above, so the separation never costs alignment;
    // nothing below, because a heading belongs to what follows it. `sticky`
    // keeps it off the bottom of a page, orphaned from its own section.
    // The baseline sits on a rule like body text; a ruled heading draws its
    // rule on the next one.
    block(
      above: if it.level == 1 { 2 * grid-step } else { grid-step },
      below: 0pt, sticky: true,
    )[
      #grid-text(text(size: hs, weight: weight, style: style, shown))
      #if ruled {
        v(grid-step)
        place(bottom + left, line(length: 100%, stroke: 0.5pt + kip-colors.rule))
      }
    ]
  }

  show link: it => text(fill: kip-colors.link, it)

  if title != none and intro != none {
    context layout(size => {
      let metadata = title-block(title-fields)
      let mw = if metadata == none { 0pt } else { measure(metadata).width }
      let mh = if metadata == none { 0pt } else { measure(metadata).height }
      let narrow = size.width - mw - if mw > 0pt { 3 * grid-step } else { 0pt }
      let title-content = block(width: narrow, spacing: 0pt, title-heading(title, subtitle))
      let th = measure(title-content).height
      block(width: 100%, spacing: grid-step)[
        #place(top + right, metadata)
        #title-content
        #v(grid-step)
        #kip-anchor(intro.id, "text")
        // The wrapped opening block is still a section when it says it is, so
        // the numbering does not start one short.
        #if intro.at("level", default: none) != none {
          kip-section(intro.level)[#intro.label]
        } else {
          block-title(intro.label)
        }
        #kip-prose(opening-flow(intro.body, narrow, calc.max(0pt, mh - th - grid-step - if intro.label != none { grid-step } else { 0pt })))
        #label("blk-" + intro.id)
      ]
    })
  } else if title != none {
    grid-snap(frame: false)[
      #grid(columns: (1fr, auto), align: (left + top, right + top), gutter: 3 * grid-step,
        block(spacing: 0pt, title-heading(title, subtitle)),
        title-block(title-fields),
      )
    ]
  }
  body
}
