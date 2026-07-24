"""Press configuration — the release/provenance identity of a publication.

``PressConfig`` carries everything that is *about the publishing repository
and release* rather than about an individual document: version stamp, author,
DOI family, license, branding strings. A consumer repo (owl-semaphore,
calibration-scope, ...) builds one ``PressConfig`` per release and reuses it
for every document it renders.

Every field that ``build_typst_document`` interpolates lives here, so the
rendered artifact's provenance is fully determined by (config, spec, body,
press version) — nothing is hidden inside the template.
"""

from __future__ import annotations

from dataclasses import dataclass, field


#: The four canonical 540px transparent composite badges, in canonical state
#: order (NORMATIVE, NON-NORMATIVE, CRITICAL, METACOGNITIVE). Paths are
#: relative to the consumer repository root that is passed to the compiler.
DEFAULT_LEDGER_BADGES: tuple[str, str, str, str] = (
    "assets/releases/540/NORM-composite-transparent-540.png",
    "assets/releases/540/NONNORM-composite-transparent-540.png",
    "assets/releases/540/CRIT-composite-transparent-540.png",
    "assets/releases/540/META-composite-transparent-540.png",
)


@dataclass
class PressConfig:
    """Release-level identity interpolated into every rendered document."""

    # Version + attribution
    release_label: str                      # e.g. "v3.0.0"
    author: str
    orcid: str
    repo_url: str                           # e.g. "github.com/IT-Help-San-Diego/owl-semaphore"
    license: str = "CC-BY-4.0"
    author_line: str = "Independent DNS Security Researcher"
    copyright_line: str = "(c) 2024-2026 IT Help San Diego Inc."

    # DOI family. ``previous_version`` and ``prior_versions`` are
    # (label, doi) pairs, e.g. ("v2.0.2", "10.5281/zenodo.20433053").
    version_doi: str = ""
    concept_doi: str = ""
    previous_version: tuple[str, str] = ("", "")
    prior_versions: tuple[tuple[str, str], ...] = ()

    # Branding
    brand: str = "Owl Semaphore"
    ledger_title: str = "OWL SEMAPHORE SYSTEM — CLASSIFICATION LEDGER"
    generated_by: str = ""                  # provenance stamp; see __post_init__

    # Document keywords: ``keywords_prefix`` renders on the first keywords
    # line, then the document's state token, then ``keywords_suffix``.
    keywords_prefix: tuple[str, ...] = (
        "Owl Semaphore", "Klein four-group", "V4", "epistemic notation",
    )
    keywords_suffix: tuple[str, ...] = ("DNS Tool", "accessibility", "metacognition")

    # Classification-ledger badge images (canonical state order).
    ledger_badges: tuple[str, str, str, str] = field(default=DEFAULT_LEDGER_BADGES)

    def __post_init__(self) -> None:
        if not self.generated_by:
            # Record the renderer identity + version in every artifact, the
            # same way a paper reports its instrument model. Consumers that
            # need a different stamp (e.g. the owl-semaphore parity test
            # reproducing the legacy generator) set generated_by explicitly.
            from . import __version__

            self.generated_by = f"owl-semaphore-press {__version__}"

    def doc_keywords(self, state_token: str) -> list[str]:
        """Full keyword list for a document, as embedded in PDF metadata."""
        return [*self.keywords_prefix, state_token, *self.keywords_suffix]
