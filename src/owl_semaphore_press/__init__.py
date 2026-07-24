"""owl-semaphore-press — the Owl Semaphore publication toolchain.

The codified design language (state colors, banner tuple, headers/footers,
title page, classification ledger) extracted from owl-semaphore's
generate_pdfs.py into a reusable package, so sibling repositories render
artifacts inside the same integrity regime. Plus Zenodo release automation
(reserve draft → embed DOI → upload → publish).
"""

__version__ = "0.1.0"

from .config import PressConfig                                    # noqa: F401
from .document import banner_tuple_line, build_typst_document, typst_str  # noqa: F401
from .markdown import md_to_typst, preprocess_md                    # noqa: F401
from .metadata import set_pdf_metadata                              # noqa: F401
from .pipeline import RenderError, render_pdf, render_typst_source  # noqa: F401
from .states import BY_TOKEN, CRITICAL, METACOGNITIVE, NON_NORMATIVE, NORMATIVE, STATES  # noqa: F401
from .zenodo import ZenodoClient, ZenodoError                       # noqa: F401
