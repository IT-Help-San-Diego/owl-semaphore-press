"""The Owl Semaphore document template — the codified design language.

``build_typst_document`` is a faithful extraction of the template that
produced the owl-semaphore v3.0.0 release PDFs (generate_pdfs.py). Given the
same document spec, body, and a ``PressConfig`` loaded from the same release
constants, it emits **byte-identical** Typst source; the parity test in
``tests/test_parity_owl_semaphore.py`` enforces this against a live
owl-semaphore checkout.

The document spec is a plain dict (the same schema generate_pdfs.py uses):

    md, pdf            source markdown filename / output pdf filename
    badge              title-page + running-header badge image path
    contact_sheet      contact-sheet image path
    color, color_rgb   state color (hex, and Typst rgb() literal)
    label              letter-spaced display label
    state_token        literal state token (drives the banner tuple)
    title, subtitle_typst
    mathline, quote, standard_ref
    contact_caption, pdf_subject
    contact_width      optional, defaults to "85%"

MIGRATION NOTE (contact_width): the legacy generator hard-coded a 90%
contact-sheet width for OWL-SEMAPHORE-SYSTEM.md and 85% for everything else.
Here that rule is the spec key ``contact_width`` — a legacy DOCS dict passed
unchanged would silently render the SYSTEM sheet at 85%. Use the canonical
specs in ``owl_documents.OWL_SEMAPHORE_DOCS`` (which carry the key) instead
of hand-copying the legacy dicts.

Escaping: fields interpolated into Typst STRING context (paths, tokens,
titles, quotes) are escaped with ``typst_str``. Fields interpolated into
Typst MARKUP context (subtitle_typst, author, author_line, brand, repo_url,
ledger_title, copyright_line, contact_width, color_rgb) are intentionally
raw — they may carry Typst markup — so they must come from trusted config,
not arbitrary user input.

All release-level identity (version, author, DOI family, branding) comes from
``PressConfig`` — see config.py.
"""

from __future__ import annotations

from .config import PressConfig


def typst_str(s: str) -> str:
    """Escape a Python string for safe embedding inside Typst double-quoted strings."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def banner_tuple_line(cfg: PressConfig, state_token: str, mathline: str, quote: str) -> str:
    """The machine-readable banner-tuple string embedded on page 1 of every PDF.

    Format is stable and load-bearing: integrity tests (e.g. owl-semaphore's
    tests/test_banner_tuple.py) extract page-one text and match this exact
    string. Do not reorder or reformat fields. DOI fields whose config value
    is empty (e.g. a first release with no previous version) are omitted
    rather than rendered with an empty right-hand side.
    """
    parts = [
        f"STATE={state_token}",
        f"TRANSFORM={mathline}",
        f"QUOTE={quote}",
        f"VERSION={cfg.release_label}",
    ]
    if cfg.version_doi:
        parts.append(f"VERSION-DOI={cfg.version_doi}")
    if cfg.concept_doi:
        parts.append(f"CONCEPT-DOI={cfg.concept_doi}")
    if cfg.previous_version[1]:
        parts.append(f"PREVIOUS-VERSION-DOI={cfg.previous_version[1]}")
    return "BANNER-TUPLE :: " + " :: ".join(parts)


def _keywords_block(cfg: PressConfig, state_token: str) -> str:
    """Render the document keywords tuple.

    With a non-empty ``keywords_prefix`` this reproduces the legacy two-line
    byte layout exactly; otherwise it falls back to a single-line tuple.
    Every keyword is escaped for Typst string context.
    """
    kws = [typst_str(k) for k in cfg.doc_keywords(state_token)]
    n = len(cfg.keywords_prefix)
    if n and len(kws) > n:
        line1 = ", ".join(f'"{k}"' for k in kws[:n]) + ","
        line2 = ", ".join(f'"{k}"' for k in kws[n:])
        return f"{line1}\n             {line2}"
    return ", ".join(f'"{k}"' for k in kws)


def _prior_doi_line(cfg: PressConfig) -> str:
    return " #h(12pt) ".join(
        f"PRIOR-{label.upper()}-DOI {doi}" for label, doi in cfg.prior_versions
    )


#: Typst hard line break + continuation indent used inside text blocks.
_BREAK = " \\\n    "


def _title_doi_block(cfg: PressConfig) -> str:
    """The title-page provenance block; empty DOI-family fields drop their
    segment (and their line) instead of rendering dangling markers."""
    line1 = f"ORCID {cfg.orcid}"
    if cfg.version_doi:
        line1 += f" #h(12pt) VERSION-DOI {cfg.version_doi} ({cfg.release_label})"
    lines = [line1]
    line2_parts = []
    if cfg.concept_doi:
        line2_parts.append(f"CONCEPT-DOI {cfg.concept_doi}")
    if cfg.previous_version[1]:
        line2_parts.append(
            f"PREVIOUS-VERSION-DOI {cfg.previous_version[1]} ({cfg.previous_version[0]})"
        )
    if line2_parts:
        lines.append(" #h(12pt) ".join(line2_parts))
    if cfg.prior_versions:
        lines.append(_prior_doi_line(cfg))
    lines.append(
        f"SOURCE {cfg.repo_url} #h(12pt) VERSION {cfg.release_label} · LICENSE {cfg.license}"
    )
    return _BREAK.join(lines)


def _ledger_doi_line(cfg: PressConfig) -> str:
    parts = []
    if cfg.version_doi:
        parts.append(f"{cfg.release_label} citing DOI {cfg.version_doi}")
    if cfg.concept_doi:
        parts.append(f"Concept DOI {cfg.concept_doi}")
    if cfg.previous_version[1]:
        parts.append(f"{cfg.previous_version[0]} DOI {cfg.previous_version[1]}")
    parts += [f"{label} DOI {doi}" for label, doi in cfg.prior_versions]
    return " · ".join(parts)


def _ledger_footer_block(cfg: PressConfig) -> str:
    lines = [f"{cfg.brand} {cfg.release_label} · {cfg.repo_url}"]
    doi_line = _ledger_doi_line(cfg)
    if doi_line:
        lines.append(doi_line)
    lines.append(f"{cfg.copyright_line} · Licensed under {cfg.license}")
    return _BREAK.join(lines)


def build_typst_document(doc: dict, body_typst: str, cfg: PressConfig) -> str:
    badge_path = doc["badge"]
    contact_path = doc["contact_sheet"]
    color = doc["color_rgb"]
    contact_width = doc.get("contact_width", "85%")

    norm_badge, nonnorm_badge, crit_badge, meta_badge = cfg.ledger_badges

    state_token = doc["state_token"]
    label_long = doc["label"]
    mathline = doc["mathline"]
    quote = doc["quote"]
    standard_ref = doc["standard_ref"]
    title = doc["title"]
    subtitle = doc["subtitle_typst"]
    contact_caption = doc["contact_caption"]

    # Stable banner-tuple line — every PDF page-1 must contain this exact string
    # so the banner-tuple test can verify it.
    banner_tuple = banner_tuple_line(cfg, state_token, mathline, quote)

    footer_right = (f"DOI {cfg.version_doi} · {cfg.license}"
                    if cfg.version_doi else cfg.license)

    return f'''// {cfg.brand} PDF — generated by {cfg.generated_by} ({cfg.release_label})
#set document(
  title: "{typst_str(title)} ({cfg.release_label})",
  author: "{typst_str(cfg.author)}",
  keywords: ({_keywords_block(cfg, state_token)}),
)

#let header-color = {color}
#let owl-badge = "{typst_str(badge_path)}"
#let state-token = "{typst_str(state_token)}"

#set page(
  paper: "us-letter",
  margin: (top: 90pt, bottom: 72pt, left: 72pt, right: 72pt),
  header: context {{
    set text(8pt, fill: luma(110))
    grid(
      columns: (auto, 1fr, auto),
      align: (left + horizon, center + horizon, right + horizon),
      box(height: 24pt)[#image(owl-badge, height: 22pt)],
      [#text(weight: "bold", tracking: 2pt, fill: header-color)[#state-token] #h(8pt) #text(fill: luma(140))[{cfg.brand} · {cfg.release_label}]],
      [#text(fill: luma(140))[{cfg.repo_url}]],
    )
    v(2pt)
    line(length: 100%, stroke: 0.5pt + luma(200))
  }},
  footer: context {{
    set text(8pt, fill: luma(140))
    grid(
      columns: (1fr, 1fr, 1fr),
      align: (left, center, right),
      [{cfg.brand} · {cfg.release_label}],
      [#counter(page).display("1 of 1", both: true)],
      [{footer_right}],
    )
  }},
)

#set text(font: "New Computer Modern", size: 11pt)
#set par(justify: true, leading: 0.65em)

#let horizontalrule = line(length: 100%, stroke: 0.5pt + luma(200))

#show heading.where(level: 1): it => {{
  v(18pt)
  line(length: 100%, stroke: 1.5pt + header-color)
  v(6pt)
  set text(size: 16pt, weight: "bold", fill: header-color)
  it.body
  v(3pt)
  line(length: 100%, stroke: 0.75pt + header-color)
  v(10pt)
}}

#show heading.where(level: 2): it => {{
  v(10pt)
  set text(size: 13pt, weight: "bold")
  it.body
  v(6pt)
}}

#show heading.where(level: 3): it => {{
  v(8pt)
  set text(size: 11pt, weight: "bold")
  it.body
  v(4pt)
}}

#show raw.where(block: true): it => {{
  set text(size: 9pt)
  block(
    fill: luma(245),
    inset: 10pt,
    radius: 3pt,
    width: 100%,
    it,
  )
}}

#set table(
  stroke: 0.5pt + luma(180),
  inset: 6pt,
)

// =====================================================================
// TITLE PAGE  (banner-tuple line is on page 1 by construction)
// =====================================================================

#align(center)[
  #v(12pt)
  #image("{typst_str(badge_path)}", width: 140pt)
  #v(8pt)

  #text(size: 10pt, weight: "bold", fill: header-color, tracking: 3pt)[{label_long}]

  #v(4pt)
  #text(size: 9pt, fill: luma(80))[#raw("{typst_str(mathline)}")]

  #v(2pt)
  #text(size: 9.5pt, style: "italic", fill: luma(80))[{typst_str(quote)}]

  #text(size: 8.5pt, fill: luma(120))[{typst_str(standard_ref)}]

  #v(16pt)
  #text(size: 28pt, weight: "bold")[{typst_str(title)}]
  #v(4pt)
  #text(size: 12pt, fill: luma(80))[{subtitle}]
  #v(10pt)

  #text(size: 11pt, weight: "bold")[{cfg.author}] \\
  #text(size: 10pt, fill: luma(80))[{cfg.author_line}]

  #v(6pt)
  #text(size: 8.5pt, fill: luma(120))[
    {_title_doi_block(cfg)}
  ]
  #v(8pt)

  // Banner-tuple (machine-readable, required for tests/test_banner_tuple.py)
  #text(size: 6.5pt, fill: luma(160), font: "Courier", tracking: 0pt)[
    #raw("{typst_str(banner_tuple)}")
  ]
  #v(8pt)
]

#line(length: 100%, stroke: 1.5pt + header-color)

// =====================================================================
// CONTACT SHEET
// =====================================================================

#v(16pt)
#align(center)[
  #text(size: 9pt, weight: "bold", fill: luma(100), tracking: 1.5pt)[
    {typst_str(contact_caption.upper())}
  ]
  #v(8pt)
  #image("{typst_str(contact_path)}", width: {contact_width})
]
#v(12pt)

// =====================================================================
// BODY CONTENT
// =====================================================================

{body_typst}

// =====================================================================
// CLASSIFICATION LEDGER (BACK PAGE)
// =====================================================================

#pagebreak()

#v(1fr)

#line(length: 100%, stroke: 1.5pt + header-color)
#v(12pt)

#align(center)[
  #text(size: 10pt, weight: "bold", fill: luma(80), tracking: 2pt)[
    {cfg.ledger_title} ({cfg.release_label})
  ]
  #v(16pt)

  #grid(
    columns: (1fr, 1fr, 1fr, 1fr),
    gutter: 12pt,
    align(center, image("{typst_str(norm_badge)}", width: 80pt)),
    align(center, image("{typst_str(nonnorm_badge)}", width: 80pt)),
    align(center, image("{typst_str(crit_badge)}", width: 80pt)),
    align(center, image("{typst_str(meta_badge)}", width: 80pt)),
    align(center, text(size: 8pt, weight: "bold", tracking: 1.5pt)[NORMATIVE]),
    align(center, text(size: 8pt, weight: "bold", tracking: 1.5pt)[NON-NORMATIVE]),
    align(center, text(size: 8pt, weight: "bold", tracking: 1.5pt)[CRITICAL]),
    align(center, text(size: 8pt, weight: "bold", tracking: 1.5pt)[METACOGNITIVE]),
    align(center, text(size: 7.5pt, fill: luma(100))[T = I #h(4pt) det = +1]),
    align(center, text(size: 7.5pt, fill: luma(100))[T = #sym.sigma#sub[v] #h(4pt) det = -1]),
    align(center, text(size: 7.5pt, fill: luma(100))[T = C#sub[2] #h(4pt) det = +1]),
    align(center, text(size: 7.5pt, fill: luma(100))[T = #sym.sigma#sub[h] #h(4pt) det = -1]),
    align(center, text(size: 7.5pt, fill: luma(100))[(x, y) -> (x, y)]),
    align(center, text(size: 7.5pt, fill: luma(100))[(x, y) -> (-x, y)]),
    align(center, text(size: 7.5pt, fill: luma(100))[(x, y) -> (-x, -y)]),
    align(center, text(size: 7.5pt, fill: luma(100))[(x, y) -> (x, -y)]),
    align(center, text(size: 7.5pt, style: "italic", fill: luma(100))["This is the standard."]),
    align(center, text(size: 7.5pt, style: "italic", fill: luma(100))["This reflects the standard."]),
    align(center, text(size: 7.5pt, style: "italic", fill: luma(100))["This inverts the standard."]),
    align(center, text(size: 7.5pt, style: "italic", fill: luma(100))["The observer audits the frame."]),
    align(center, text(size: 7pt, fill: luma(140))[RFC 2119 MUST / SHALL]),
    align(center, text(size: 7pt, fill: luma(140))[Informative / Advisory (NOTE)]),
    align(center, text(size: 7pt, fill: luma(140))[RFC 2119 MUST NOT / SHALL NOT]),
    align(center, text(size: 7pt, fill: luma(140))[Epistemic / Framework (META)]),
  )

  #v(16pt)
  #text(size: 7.5pt, style: "italic", fill: luma(120))[
    Accessibility: color is not the only carrier. State identity is recoverable from color #h(2pt) + #h(2pt) orientation #h(2pt) + #h(2pt) textual label (WCAG 2.2 SC 1.4.1).
  ]

  #v(12pt)
  #line(length: 60%, stroke: 0.5pt + luma(200))
  #v(8pt)
  #text(size: 8pt, fill: luma(140))[
    {_ledger_footer_block(cfg)}
  ]
]

#v(1fr)
'''
