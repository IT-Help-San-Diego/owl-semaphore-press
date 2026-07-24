"""Markdown → Typst body conversion (pandoc), as used by the owl pipeline."""

from __future__ import annotations

import re
import subprocess

from .errors import PandocError


#: Title-block prefixes stripped by default (the owl-semaphore documents
#: render their titles via the template, not the markdown source).
DEFAULT_TITLE_PREFIXES: tuple[str, ...] = (
    "# OWL SEMAPHORE",
    "## OWL ",
    "### Version",
    "## Version",
)


def preprocess_md(md_path: str, title_prefixes: tuple[str, ...] = DEFAULT_TITLE_PREFIXES) -> str:
    with open(md_path, "r", encoding="utf-8") as f:
        text = f.read()

    lines = text.splitlines()

    # Strip a leading image line
    if lines and lines[0].startswith("!["):
        lines = lines[1:]

    text = "\n".join(lines).strip()
    # Convert \(...\) inline math to $...$
    text = re.sub(r"\\\((.+?)\\\)", r"$\1$", text)

    # Drop the top-of-document title block lines that the template renders.
    new_lines = []
    skipped = 0
    for line in text.split("\n"):
        if skipped < 3 and any(line.startswith(p) for p in title_prefixes):
            skipped += 1
            continue
        new_lines.append(line)
    text = "\n".join(new_lines).strip()
    text = re.sub(r"^---\s*\n", "", text)
    return text


def md_to_typst(md_text: str) -> str:
    try:
        result = subprocess.run(
            ["pandoc", "-f", "markdown", "-t", "typst", "--wrap=none"],
            input=md_text,
            capture_output=True,
            encoding="utf-8",
        )
    except FileNotFoundError as exc:
        raise PandocError("pandoc not found on PATH — install pandoc") from exc
    if result.returncode != 0:
        raise PandocError(f"pandoc error: {result.stderr}")
    body = result.stdout
    # Pandoc emits heading id labels like ``<my-section-id>`` after each heading.
    # Typst's label parser rejects characters that aren't valid label chars
    # (dots, unicode digits like ₄). This pipeline doesn't use the labels,
    # so strip them entirely.
    body = re.sub(r"\s*<[^>\n]*>\s*$", "", body, flags=re.MULTILINE)
    return body
