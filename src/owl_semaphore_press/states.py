"""The codified Owl Semaphore design language: the four canonical states.

These constants are normative. They restate — and must never contradict —
OWL-SEMAPHORE-SYSTEM.md (the V4 algebra, state/operator tuples, colors, and
canonical quotes). Consumer repos build their own document specs from these
so that a FINDINGS PDF in a sibling repo carries exactly the same state
identity as the specification PDFs.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class State:
    token: str            # literal state token, e.g. "NORMATIVE"
    label: str            # letter-spaced display label
    color: str            # hex, canonical palette
    color_rgb: str        # Typst rgb() literal of the same color
    mathline: str         # "T = <op>    det = <d>    (x, y) -> ..."
    quote: str            # canonical quote, double-quoted
    standard_ref: str     # standards-register line


NORMATIVE = State(
    token="NORMATIVE",
    label="N O R M A T I V E",
    color="#d4a853",
    color_rgb="rgb(212, 168, 83)",
    mathline="T = I    det = +1    (x, y) -> (x, y)",
    quote='"This is the standard."',
    standard_ref="RFC 2119 MUST / SHALL",
)

NON_NORMATIVE = State(
    token="NON-NORMATIVE",
    label="N O N - N O R M A T I V E",
    color="#316964",
    color_rgb="rgb(49, 105, 100)",
    mathline="T = sigma_v    det = -1    (x, y) -> (-x, y)",
    quote='"This reflects the standard."',
    standard_ref="Informative / Advisory (NOTE)",
)

CRITICAL = State(
    token="CRITICAL",
    label="C R I T I C A L",
    color="#990f1e",
    color_rgb="rgb(153, 15, 30)",
    mathline="T = C2    det = +1    (x, y) -> (-x, -y)",
    quote='"This inverts the standard."',
    standard_ref="RFC 2119 MUST NOT / SHALL NOT",
)

METACOGNITIVE = State(
    token="METACOGNITIVE",
    label="M E T A C O G N I T I V E",
    color="#8C4191",
    color_rgb="rgb(140, 65, 145)",
    mathline="T = sigma_h    det = -1    (x, y) -> (x, -y)",
    quote='"The observer audits the frame."',
    standard_ref="Epistemic / Framework (META)",
)

#: Canonical state order (matches the classification ledger).
STATES: tuple[State, ...] = (NORMATIVE, NON_NORMATIVE, CRITICAL, METACOGNITIVE)

BY_TOKEN: dict[str, State] = {s.token: s for s in STATES}
