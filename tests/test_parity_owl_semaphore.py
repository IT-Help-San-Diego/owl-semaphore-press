"""Fidelity proof: the press package reproduces owl-semaphore's legacy
generate_pdfs.py output BYTE-IDENTICALLY.

Loads the legacy module from a local owl-semaphore checkout (env var
OWL_SEMAPHORE_REPO, default ``../owl-semaphore``), builds a PressConfig from
its release constants, and compares:

  - build_typst_document() output for every entry in legacy DOCS
    (template parity — the design language itself), and
  - preprocess_md() output for every source markdown file present.

Skips (not fails) when no owl-semaphore checkout is available, so the press
repo's own CI stays green in isolation.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from owl_semaphore_press import PressConfig, build_typst_document  # noqa: E402
from owl_semaphore_press.markdown import preprocess_md  # noqa: E402

REPO_ENV = "OWL_SEMAPHORE_REPO"
DEFAULT_REPO = os.path.join(os.path.dirname(__file__), "..", "..", "owl-semaphore")


def _find_repo() -> str | None:
    candidate = os.environ.get(REPO_ENV, DEFAULT_REPO)
    path = os.path.abspath(candidate)
    if os.path.isfile(os.path.join(path, "generate_pdfs.py")):
        return path
    return None


def _load_legacy(repo: str):
    spec = importlib.util.spec_from_file_location(
        "legacy_generate_pdfs", os.path.join(repo, "generate_pdfs.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _config_from_legacy(legacy) -> PressConfig:
    return PressConfig(
        release_label=legacy.RELEASE_LABEL,
        author=legacy.AUTHOR,
        orcid=legacy.ORCID,
        repo_url=legacy.REPO_URL,
        license=legacy.LICENSE,
        version_doi=legacy.VERSION_DOI,
        concept_doi=legacy.CONCEPT_DOI,
        previous_version=("v2.0.2", legacy.PREVIOUS_VERSION_DOI),
        prior_versions=(
            ("v2.0.1", legacy.PRIOR_V201_DOI),
            ("v2.0.0", legacy.PRIOR_V200_DOI),
            ("v1.2.0", legacy.PRIOR_V120_DOI),
        ),
        generated_by="generate_pdfs.py",
    )


class ParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        repo = _find_repo()
        if repo is None:
            raise unittest.SkipTest(
                f"no owl-semaphore checkout found (set {REPO_ENV})"
            )
        cls.repo = repo
        cls.legacy = _load_legacy(repo)
        cls.cfg = _config_from_legacy(cls.legacy)

    def test_template_parity_all_documents(self):
        body = "BODY-PLACEHOLDER\n"
        for doc in self.legacy.DOCS:
            with self.subTest(doc=doc["md"]):
                expected = self.legacy.build_typst_document(doc, body)
                spec = dict(doc)
                if doc["md"] == "OWL-SEMAPHORE-SYSTEM.md":
                    spec["contact_width"] = "90%"
                actual = build_typst_document(spec, body, self.cfg)
                self.assertEqual(
                    expected, actual,
                    f"Typst template output diverges for {doc['md']}",
                )

    def test_template_parity_with_realistic_body(self):
        body = (
            "= Heading\n\nSome *body* with #raw(\"code\") and $x -> y$.\n\n"
            "#table(columns: 2)[a][b]\n"
        )
        doc = self.legacy.DOCS[0]
        spec = dict(doc, contact_width="90%")
        self.assertEqual(
            self.legacy.build_typst_document(doc, body),
            build_typst_document(spec, body, self.cfg),
        )

    def test_shipped_specs_match_legacy_docs(self):
        """owl_documents.OWL_SEMAPHORE_DOCS must equal legacy DOCS, plus the
        contact_width key that replaces the legacy filename special-case."""
        from owl_semaphore_press.owl_documents import OWL_SEMAPHORE_DOCS

        self.assertEqual(len(OWL_SEMAPHORE_DOCS), len(self.legacy.DOCS))
        for shipped, legacy in zip(OWL_SEMAPHORE_DOCS, self.legacy.DOCS):
            with self.subTest(md=legacy["md"]):
                extras = dict(shipped)
                width = extras.pop("contact_width", "85%")
                self.assertEqual(extras, legacy)
                expected_width = ("90%" if legacy["md"] == "OWL-SEMAPHORE-SYSTEM.md"
                                  else "85%")
                self.assertEqual(width, expected_width)

    def test_shipped_specs_render_byte_identical(self):
        from owl_semaphore_press.owl_documents import OWL_SEMAPHORE_DOCS

        body = "BODY-PLACEHOLDER\n"
        for shipped, legacy in zip(OWL_SEMAPHORE_DOCS, self.legacy.DOCS):
            with self.subTest(md=legacy["md"]):
                self.assertEqual(
                    self.legacy.build_typst_document(legacy, body),
                    build_typst_document(shipped, body, self.cfg),
                )

    def test_preprocess_parity_all_sources(self):
        for doc in self.legacy.DOCS:
            md_path = os.path.join(self.repo, doc["md"])
            if not os.path.isfile(md_path):
                continue
            with self.subTest(md=doc["md"]):
                self.assertEqual(
                    self.legacy.preprocess_md(md_path),
                    preprocess_md(md_path),
                    f"preprocess_md diverges for {doc['md']}",
                )


if __name__ == "__main__":
    unittest.main()
