"""PDF metadata embedding (docinfo + XMP) via pikepdf, if available."""

from __future__ import annotations

import sys

from .config import PressConfig


def set_pdf_metadata(pdf_path: str, doc: dict, cfg: PressConfig) -> bool:
    """Embed Title/Author/Subject/Keywords/Creator/Producer into the PDF.

    Returns True if metadata was written, False if pikepdf is unavailable.
    Never raises for a metadata failure — the PDF itself is already valid.
    """
    try:
        import pikepdf  # type: ignore
    except Exception:
        return False

    keywords = ", ".join([*cfg.doc_keywords(doc["state_token"]), cfg.release_label])
    subject = doc["pdf_subject"]
    title = f'{doc["title"]} ({cfg.release_label})'
    creator = f"{cfg.generated_by} ({cfg.release_label})"

    try:
        with pikepdf.open(pdf_path, allow_overwriting_input=True) as pdf:
            with pdf.open_metadata(set_pikepdf_as_editor=False) as meta:
                meta["dc:title"] = title
                meta["dc:creator"] = [cfg.author]
                meta["dc:description"] = subject
                meta["pdf:Keywords"] = keywords
                meta["dc:subject"] = keywords.split(", ")
                meta["xmp:CreatorTool"] = creator
            pdf.docinfo["/Title"] = title
            pdf.docinfo["/Author"] = cfg.author
            pdf.docinfo["/Subject"] = subject
            pdf.docinfo["/Keywords"] = keywords
            pdf.docinfo["/Creator"] = creator
            pdf.docinfo["/Producer"] = "typst (via python-typst) + pikepdf"
            pdf.save()
        return True
    except Exception as exc:  # pragma: no cover
        print(f"  ! pikepdf metadata embed failed for {pdf_path}: {exc}", file=sys.stderr)
        return False
