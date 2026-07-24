"""Exception hierarchy: everything the pipeline raises derives from PressError."""

from __future__ import annotations


class PressError(RuntimeError):
    """Base class for all owl-semaphore-press errors."""


class RenderError(PressError):
    """Rendering pipeline failure (Typst compile, missing tooling, ...)."""


class PandocError(RenderError):
    """pandoc failed or is not installed."""
