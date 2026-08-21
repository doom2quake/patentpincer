"""Patentability-verdict router - agent-core's Router with a strict verdict parser.

Reuses agent-core's `Router` + `Notifier`-backed handlers, but NOT its keyword
classifier. Keyword-scanning a brief is unsafe here: a brief that reads
"VERDICT: CLEAR / no high overlap was found" contains the phrase "high overlap"
and a keyword classifier routes it as a collision. The verdict is a contract,
not prose, so it is parsed as one:

    ^VERDICT:\\s*(CLEAR|NEEDS_REVIEW|HIGH_OVERLAP|SEARCH_UNAVAILABLE)$

taken from the FIRST non-empty line. Anything else is `malformed` and is routed
for human review rather than guessed at.

  * HIGH_OVERLAP       -> alert (warn the founder loudly: do not file as-is) + ticket
  * NEEDS_REVIEW       -> ticket (a work item: narrow the claims)
  * CLEAR              -> ticket (a work item: proceed to drafting/filing)
  * SEARCH_UNAVAILABLE -> alert + ticket (the search failed; this is NOT a clearance)
  * malformed          -> ticket (a human reads the brief)
"""

from __future__ import annotations

import re
from typing import Any

from agent_core import (
    ActionLimiter,
    ActionPolicy,
    AlertHandler,
    Notifier,
    Route,
    Router,
    TicketHandler,
)

from .config import settings

DOMAIN_HIGH_OVERLAP = "high_overlap"
DOMAIN_NEEDS_REVIEW = "needs_review"
DOMAIN_CLEAR = "clear"
DOMAIN_SEARCH_UNAVAILABLE = "search_unavailable"
DOMAIN_MALFORMED = "malformed"

#: verdict token -> routing domain. The only accepted tokens.
VERDICT_DOMAINS = {
    "CLEAR": DOMAIN_CLEAR,
    "NEEDS_REVIEW": DOMAIN_NEEDS_REVIEW,
    "HIGH_OVERLAP": DOMAIN_HIGH_OVERLAP,
    "SEARCH_UNAVAILABLE": DOMAIN_SEARCH_UNAVAILABLE,
}

_VERDICT_LINE = re.compile(
    r"^VERDICT:\s*(CLEAR|NEEDS_REVIEW|HIGH_OVERLAP|SEARCH_UNAVAILABLE)\s*$")

_ROUTING = {
    DOMAIN_HIGH_OVERLAP: Route(("alert", "ticket")),
    DOMAIN_NEEDS_REVIEW: Route(("ticket",)),
    DOMAIN_CLEAR: Route(("ticket",)),
    DOMAIN_SEARCH_UNAVAILABLE: Route(("alert", "ticket")),
    DOMAIN_MALFORMED: Route(("ticket",)),
}


def parse_verdict(text: str) -> str | None:
    """Return the verdict token from the first non-empty line, or None.

    Strict: the line must be exactly `VERDICT: <TOKEN>`. Commentary elsewhere in
    the brief is ignored, and a missing or malformed line returns None so the
    caller can refuse rather than guess.
    """
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        m = _VERDICT_LINE.match(stripped)
        return m.group(1) if m else None
    return None


class VerdictClassifier:
    """Deterministic classifier over the authoritative VERDICT line.

    Duck-types agent-core's `KeywordClassifier` (`.classify(incident) -> domain`)
    so it drops straight into `Router`, but it never reads free prose.
    """

    default = DOMAIN_MALFORMED

    def classify(self, incident: dict[str, Any]) -> str:
        explicit = incident.get("verdict")
        if isinstance(explicit, str) and explicit.strip().upper() in VERDICT_DOMAINS:
            return VERDICT_DOMAINS[explicit.strip().upper()]
        token = parse_verdict(str(incident.get("summary") or ""))
        if token is None:
            return DOMAIN_MALFORMED
        return VERDICT_DOMAINS[token]


def build_router(store_recorder=None) -> Router:
    """Wire a patentability Router on a guarded Notifier (stub sinks without creds)."""
    limiter = ActionLimiter(ActionPolicy.from_env("PP"))
    notifier = Notifier(settings, limiter, recorder=store_recorder, source_label="patentpincer")
    handlers = [
        AlertHandler(notifier, domains=(DOMAIN_HIGH_OVERLAP, DOMAIN_SEARCH_UNAVAILABLE),
                     channel="#patents"),
        TicketHandler(notifier, priority="P2"),
    ]
    return Router(handlers, classifier=VerdictClassifier(), routing=_ROUTING, env_prefix="PP")
