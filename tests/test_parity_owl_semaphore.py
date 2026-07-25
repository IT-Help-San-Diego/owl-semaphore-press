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

THE BASELINE IS PINNED TO A TAG, NOT THE WORKING TREE
-----------------------------------------------------
The parity claim is historical: "the design language extracted into this
package is byte-identical to the generator that produced the v3.0.0 release."
Its baseline is therefore the v3.0.0 generator specifically.

At owl-semaphore v3.0.1 the working-tree ``generate_pdfs.py`` became a thin
driver that *imports from this package* and no longer defines
``build_typst_document`` / ``preprocess_md`` at all. Reading the baseline from
the working tree is thus wrong in two ways at once: against a v3.0.1+ checkout
it errors with AttributeError (no legacy functions to compare against), and if
those names ever came back it would be comparing the package to itself — a
tautology that passes while proving nothing.

So the legacy module is extracted from the pinned ``LEGACY_REF`` git object
(``git show <ref>:generate_pdfs.py``) rather than read off disk. This keeps the
proof runnable and meaningful as owl-semaphore's main branch moves on. The
extracted baseline is immutable, so a PASS means what it says.

Set ``OWL_SEMAPHORE_LEGACY_REF`` to compare against a different release.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from owl_semaphore_press import PressConfig, build_typst_document  # noqa: E402
from owl_semaphore_press.markdown import preprocess_md  # noqa: E402

REPO_ENV = "OWL_SEMAPHORE_REPO"
LEGACY_REF_ENV = "OWL_SEMAPHORE_LEGACY_REF"
DEFAULT_REPO = os.path.join(os.path.dirname(__file__), "..", "..", "owl-semaphore")

#: The release whose generator defines the parity baseline. v3.0.0 is the last
#: release whose generate_pdfs.py carried the design language itself; v3.0.1
#: replaced it with a driver over this package.
LEGACY_REF = os.environ.get(LEGACY_REF_ENV, "v3.0.0")

#: Names the baseline must define for the comparison to be meaningful.
REQUIRED_LEGACY_ATTRS = ("DOCS", "build_typst_document", "preprocess_md")


def _find_repo() -> str | None:
    candidate = os.environ.get(REPO_ENV, DEFAULT_REPO)
    path = os.path.abspath(candidate)
    if os.path.isdir(os.path.join(path, ".git")):
        return path
    return None


def _legacy_source(repo: str, ref: str) -> str | None:
    """Return ``generate_pdfs.py`` as of ``ref``, or None if unavailable.

    Read from the git object store, never the working tree: the baseline must
    be the historical generator, and it must be immutable.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", repo, "show", f"{ref}:generate_pdfs.py"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout if proc.returncode == 0 and proc.stdout else None


def _load_legacy_from_source(source: str):
    """Exec the pinned legacy source as a module, from a temp file.

    The v3.0.0 generator is import-safe (constants + function defs; all work
    behind ``main()``), so executing it has no side effects.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "legacy_generate_pdfs.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write(source)
        spec = importlib.util.spec_from_file_location("legacy_generate_pdfs", path)
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
                f"no owl-semaphore git checkout found (set {REPO_ENV})"
            )
        source = _legacy_source(repo, LEGACY_REF)
        if source is None:
            raise unittest.SkipTest(
                f"cannot read generate_pdfs.py at ref {LEGACY_REF!r} from {repo} "
                f"(shallow clone or missing tag? set {LEGACY_REF_ENV})"
            )
        cls.repo = repo
        cls.legacy = _load_legacy_from_source(source)
        # Fail loudly rather than skip: a baseline missing these names means the
        # pin is wrong, and a silent skip would retire the parity proof unnoticed.
        missing = [a for a in REQUIRED_LEGACY_ATTRS
                   if not hasattr(cls.legacy, a)]
        if missing:
            raise AssertionError(
                f"legacy baseline at ref {LEGACY_REF!r} does not define {missing}. "
                "The parity baseline must be a release whose generate_pdfs.py "
                "still carries the design language (v3.0.0 or earlier); v3.0.1+ "
                "is a driver over this package and would compare it to itself."
            )
        cls.cfg = _config_from_legacy(cls.legacy)

    def test_baseline_is_pinned_not_working_tree(self):
        """The baseline must come from git history, not the working tree.

        Guards the tautology: if the working tree's generate_pdfs.py (a driver
        importing this package) were ever used as the baseline, parity would
        compare the package against itself and pass while proving nothing.
        """
        working = os.path.join(self.repo, "generate_pdfs.py")
        if os.path.isfile(working):
            with open(working, "r", encoding="utf-8") as f:
                current = f.read()
            pinned = _legacy_source(self.repo, LEGACY_REF)
            self.assertIsNotNone(pinned)
            if "owl_semaphore_press" in current:
                self.assertNotEqual(
                    current, pinned,
                    "baseline appears to be the package-importing driver; "
                    "parity would be self-referential")
        self.assertTrue(
            all(hasattr(self.legacy, a) for a in REQUIRED_LEGACY_ATTRS),
            "pinned baseline must define the legacy design-language functions")

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
