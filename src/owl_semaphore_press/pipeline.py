"""End-to-end rendering: markdown source → Typst → compiled, stamped PDF."""

from __future__ import annotations

import os

from .config import PressConfig
from .document import build_typst_document
from .markdown import md_to_typst, preprocess_md
from .metadata import set_pdf_metadata


class RenderError(RuntimeError):
    pass


def render_typst_source(doc: dict, repo_root: str, cfg: PressConfig) -> str:
    """Produce the full Typst source for a document (no compilation)."""
    md_path = os.path.join(repo_root, doc["md"])
    md_text = preprocess_md(md_path)
    body_typst = md_to_typst(md_text)
    return build_typst_document(doc, body_typst, cfg)


def render_pdf(doc: dict, repo_root: str, cfg: PressConfig, keep_typ: bool = False) -> str:
    """Render one document to PDF inside ``repo_root``. Returns the PDF path.

    Requires the ``typst`` Python package (``pip install owl-semaphore-press[render]``).
    Asset paths inside the document spec are resolved relative to ``repo_root``.
    """
    try:
        import typst  # type: ignore
    except ImportError as exc:
        raise RenderError(
            "the 'typst' Python package is not installed "
            "(pip install owl-semaphore-press[render])"
        ) from exc

    typst_source = render_typst_source(doc, repo_root, cfg)

    pdf_path = os.path.join(repo_root, doc["pdf"])
    typ_path = os.path.join(repo_root, doc["pdf"].replace(".pdf", ".typ"))
    with open(typ_path, "w") as f:
        f.write(typst_source)

    try:
        compiler = typst.Compiler(input=typ_path, root=repo_root)
        compiler.compile(output=pdf_path)
    except Exception as exc:
        raise RenderError(f"typst compile failed for {doc['pdf']}: {exc}") from exc
    finally:
        if not keep_typ:
            try:
                os.remove(typ_path)
            except OSError:
                pass

    set_pdf_metadata(pdf_path, doc, cfg)
    return pdf_path
