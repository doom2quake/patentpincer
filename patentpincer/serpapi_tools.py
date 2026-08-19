"""SerpApi tools - the load-bearing data backbone (Google Patents + Scholar).

These are the ADK agent tools the Prior-Art searcher calls. Three engines:

  * `google_patents`         -> the candidate reference set
  * `google_scholar`         -> non-patent literature
  * `google_patents_details` -> the ACTUAL CLAIM TEXT of a shortlisted patent,
                                which is what an element-by-element comparison
                                needs. Titles and snippets are not claims.

Provenance is explicit on every return value, because a patentability call that
cannot tell evidence from a demo fixture is worse than no call at all:

    status = "ok"                  live SerpApi response
             "fixture"             offline demo corpus (three named cases only)
             "fixture_unavailable" offline and the query is not a demo case
             "suppressed"          the spend guardrail refused the call
             "error"               the call was attempted and failed

Only `ok` is live evidence. `fixture` is clearly marked and the pipeline refuses
to issue an actionable CLEAR from it (see `main.assess`).

Every call passes an ActionLimiter check first, so an autonomous loop can never
run away and burn SerpApi credits. Calls are grouped into a spend cycle by
run id, resolved in this order: explicit `run_id` argument, then the in-process
run context (a ContextVar, so concurrent assessments do not clobber each other),
then `PP_RUN_ID` from the environment, then "adhoc".

A run id may carry a `#suffix` (for example `run-abc#narrative`). The SUFFIX
selects the spend cycle; the part before it selects the ledger. That is how one
assessment gives the deterministic analyst and the optional LLM narrative one
budget each: neither can starve the other, the hourly cap still bounds the
total, and both show up in a single per-run call ledger.
"""

from __future__ import annotations

import contextvars
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from typing import Any

from agent_core import ActionLimiter, ActionPolicy, env_bool, env_int

from . import fixtures
from .config import settings

STATUS_OK = "ok"
STATUS_FIXTURE = "fixture"
STATUS_NO_FIXTURE = "fixture_unavailable"
STATUS_SUPPRESSED = "suppressed"
STATUS_ERROR = "error"

#: Statuses that carry usable references. Only STATUS_OK is live evidence.
USABLE_STATUSES = frozenset({STATUS_OK, STATUS_FIXTURE})
LIVE_STATUSES = frozenset({STATUS_OK})


def default_policy() -> ActionPolicy:
    """The SerpApi spend policy: one assessment's worth of calls per run.

    `ActionPolicy.from_env` defaults to 4 actions per cycle, which is fewer than
    one PatentPincer assessment needs (3 patent queries + 1 Scholar + 3 claim
    fetches). Under that default the claim fetches were silently suppressed and
    the element-by-element comparison ran against nothing, which is worse than
    refusing. So the per-cycle cap defaults to exactly `serpapi_calls_per_run`
    and the hourly cap to eight assessments. Both are still overridable with
    `PP_MAX_ACTIONS_PER_CYCLE` / `PP_MAX_ACTIONS_PER_HOUR`, and `PP_DRY_RUN`
    still suppresses everything.
    """
    per_run = settings.serpapi_calls_per_run
    return ActionPolicy(
        dry_run=env_bool("PP_DRY_RUN", False),
        max_actions_per_cycle=env_int("PP_MAX_ACTIONS_PER_CYCLE", per_run),
        max_actions_per_hour=env_int("PP_MAX_ACTIONS_PER_HOUR", per_run * 8),
    )


# Process-wide spend guardrail for SerpApi calls (rate/dry-run from PP_* env).
_limiter = ActionLimiter(default_policy())

# Request-local run id. A ContextVar (not a module global) so two assessments
# running concurrently in the same process each keep their own spend cycle.
_run_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("patentpincer_run_id", default="")

# Per-run ledger of every SerpApi call attempted, so the caller can prove what
# actually happened (live / fixture / suppressed / error) instead of guessing.
_ledger: dict[str, list[dict[str, Any]]] = {}
_ledger_lock = threading.Lock()


def bind_run(run_id: str) -> contextvars.Token:
    """Bind `run_id` to the current context. Returns a token for `unbind_run`."""
    return _run_ctx.set(run_id or "adhoc")


def unbind_run(token: contextvars.Token) -> None:
    _run_ctx.reset(token)


def current_run_id(explicit: str = "") -> str:
    """Resolve the run id for a tool call (explicit > context > env > adhoc)."""
    return explicit or _run_ctx.get() or os.getenv("PP_RUN_ID", "") or "adhoc"


def ledger_key(run_id: str) -> str:
    """The run a call is attributed to: everything before the `#cycle` suffix."""
    return (run_id or "adhoc").split("#", 1)[0]


def calls_for(run_id: str) -> list[dict[str, Any]]:
    """Every SerpApi call recorded under `run_id`, oldest first."""
    with _ledger_lock:
        return [dict(c) for c in _ledger.get(run_id, ())]


def reset_run(run_id: str) -> None:
    with _ledger_lock:
        _ledger.pop(run_id, None)


def _record(run_id: str, entry: dict[str, Any]) -> None:
    with _ledger_lock:
        _ledger.setdefault(run_id, []).append(entry)


def _serpapi(engine: str, extra: dict[str, str], run_id: str) -> dict[str, Any]:
    """Guarded SerpApi request. Returns the parsed JSON or a marked fixture.

    `run_id` is the spend-cycle key; the ledger entry is filed under
    `ledger_key(run_id)` so every cycle of one assessment lands in one ledger.
    """
    started = time.perf_counter()
    allowed, reason = _limiter.check(run_id, f"serpapi:{engine}")
    if not allowed:
        out = {"status": STATUS_SUPPRESSED, "mode": "suppressed", "reason": reason,
               "engine": engine, "organic_results": []}
    elif not settings.use_serpapi:
        out = _offline(engine, extra)
    else:
        params = {"engine": engine, "api_key": settings.serpapi_key, **extra}
        url = f"{settings.serpapi_endpoint}?{urllib.parse.urlencode(params)}"
        try:
            with urllib.request.urlopen(url, timeout=settings.timeout_s) as resp:  # noqa: S310 - trusted host
                body = json.loads(resp.read().decode())
            if isinstance(body.get("error"), str):
                # SerpApi reports quota/params failures with HTTP 200 + `error`.
                out = {"status": STATUS_ERROR, "mode": "live", "engine": engine,
                       "error": body["error"], "organic_results": []}
            else:
                # The response body is spread FIRST: provenance is ours to set,
                # and a remote payload that happens to carry a `status` or
                # `mode` key must never be able to relabel a call.
                out = {**body, "status": STATUS_OK, "mode": "live", "engine": engine}
        except Exception as exc:
            out = {"status": STATUS_ERROR, "mode": "live", "engine": engine,
                   "error": f"{exc.__class__.__name__}: {exc}", "organic_results": []}
    out["run_id"] = run_id
    _record(ledger_key(run_id), {
        "engine": engine, "query": extra.get("q") or extra.get("patent_id", ""),
        "cycle": run_id, "status": out["status"], "mode": out.get("mode", ""),
        "reason": out.get("reason") or out.get("error") or "",
        "ms": round((time.perf_counter() - started) * 1000, 1),
    })
    return out


# --- tools -------------------------------------------------------------------

def search_patents(query: str, before: str = "", assignee: str = "",
                   run_id: str = "") -> dict[str, Any]:
    """Search Google Patents for prior art matching an invention description.

    Args:
        query: The invention / claim language to search (keywords or a sentence).
        before: Optional priority-date cutoff, e.g. "priority:20230101" to find
            art published before a filing date.
        assignee: Optional assignee/company filter.
        run_id: Optional run identifier that groups this call into one SerpApi
            spend cycle. Pass it explicitly when calling over MCP; in-process
            callers can leave it empty and it is taken from the run context.

    Returns a dict with `status` (ok | fixture | fixture_unavailable |
    suppressed | error), `mode` (live | fixture | suppressed), and `patents`:
    each with patent_id, title, snippet, assignee, priority_date, and a URL.
    Only `status="ok"` is live evidence.
    """
    rid = current_run_id(run_id)
    extra = {"q": query, "num": str(settings.max_results)}
    if before:
        extra["before"] = before
    if assignee:
        extra["assignee"] = assignee
    raw = _serpapi("google_patents", extra, rid)
    results = raw.get("organic_results") or raw.get("results") or []
    return {
        "status": raw.get("status", STATUS_ERROR),
        "mode": raw.get("mode", ""),
        "run_id": rid,
        "query": query,
        "before": before,
        "assignee": assignee,
        "count": len(results[: settings.max_results]),
        "patents": [
            {
                "patent_id": r.get("patent_id") or r.get("publication_number"),
                "title": r.get("title"),
                "snippet": r.get("snippet"),
                "assignee": r.get("assignee"),
                "priority_date": r.get("priority_date") or r.get("filing_date"),
                "url": r.get("patent_link") or r.get("link"),
                "provenance": raw.get("mode", ""),
            }
            for r in results[: settings.max_results]
        ],
        "reason": raw.get("reason") or raw.get("error"),
    }


def search_scholar(query: str, run_id: str = "") -> dict[str, Any]:
    """Search Google Scholar for NON-patent prior art (papers, preprints).

    Non-patent literature can anticipate a claim just as a patent can. Use this
    alongside `search_patents` for a complete prior-art picture.

    Args:
        query: The invention / claim language to search.
        run_id: Optional run identifier (see `search_patents`).

    Returns a dict with `status`, `mode`, and `papers`: title, snippet,
    publication, year, url.
    """
    rid = current_run_id(run_id)
    raw = _serpapi("google_scholar", {"q": query, "num": str(settings.max_results)}, rid)
    results = raw.get("organic_results") or raw.get("results") or []
    return {
        "status": raw.get("status", STATUS_ERROR),
        "mode": raw.get("mode", ""),
        "run_id": rid,
        "query": query,
        "count": len(results[: settings.max_results]),
        "papers": [
            {
                "title": r.get("title"),
                "snippet": r.get("snippet"),
                "publication": (r.get("publication_info") or {}).get("summary"),
                "year": r.get("year"),
                "url": r.get("link"),
                "provenance": raw.get("mode", ""),
            }
            for r in results[: settings.max_results]
        ],
        "reason": raw.get("reason") or raw.get("error"),
    }


def fetch_patent_details(patent_id: str, run_id: str = "") -> dict[str, Any]:
    """Fetch the ABSTRACT and NUMBERED CLAIMS of one patent (Google Patents Details).

    An element-by-element novelty comparison must read claim language, not a
    search snippet. Call this for each shortlisted result from `search_patents`
    before judging novelty.

    Args:
        patent_id: The id from `search_patents`, e.g. "US-11234567-B2" or the
            SerpApi detail id "patent/US11234567B2/en".
        run_id: Optional run identifier (see `search_patents`).

    Returns a dict with `status`, `mode`, `title`, `abstract`, and `claims`:
    a list of {number, text} in claim order.
    """
    rid = current_run_id(run_id)
    raw = _serpapi("google_patents_details", {"patent_id": _detail_id(patent_id)}, rid)
    claims = _normalise_claims(raw.get("claims"))
    return {
        "status": raw.get("status", STATUS_ERROR),
        "mode": raw.get("mode", ""),
        "run_id": rid,
        "patent_id": patent_id,
        "title": raw.get("title"),
        "abstract": raw.get("abstract"),
        "claims": claims,
        "claim_count": len(claims),
        "url": raw.get("patent_link") or raw.get("link"),
        "reason": raw.get("reason") or raw.get("error"),
    }


def _detail_id(patent_id: str) -> str:
    """Normalise "US-11234567-B2" to SerpApi's detail id "patent/US11234567B2/en"."""
    pid = (patent_id or "").strip()
    if pid.startswith("patent/"):
        return pid
    return f"patent/{pid.replace('-', '')}/en"


def _normalise_claims(raw: Any) -> list[dict[str, Any]]:
    """SerpApi returns claims as a list of strings (sometimes dicts). Number them."""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for i, item in enumerate(raw, start=1):
        if isinstance(item, dict):
            text = str(item.get("text") or item.get("claim") or "").strip()
            number = item.get("number") or i
        else:
            text = str(item).strip()
            number = i
        if not text:
            continue
        # Some records prefix the claim number in the text; strip it so the
        # number we report is the one we assign.
        text = re.sub(r"^\s*\d+\s*[.)]\s*", "", text)
        out.append({"number": int(number), "text": text})
    return out


# --- offline demo corpus (three named cases; never labelled "ok") ------------

def _offline(engine: str, extra: dict[str, str]) -> dict[str, Any]:
    """Serve the offline demo corpus, or refuse when the query is not a demo case."""
    if engine == "google_patents_details":
        rec = fixtures.details_for(extra.get("patent_id", "").replace("patent/", "").replace("/en", ""))
        if rec is None:
            return {"status": STATUS_NO_FIXTURE, "mode": "fixture", "engine": engine,
                    "reason": f"no offline claim text for {extra.get('patent_id')!r}; "
                              "set PP_SERPAPI_KEY for live Google Patents Details",
                    "claims": []}
        return {"status": STATUS_FIXTURE, "mode": "fixture", "engine": engine,
                "title": rec["title"], "abstract": rec["abstract"],
                "claims": list(rec["claims"]), "patent_link": rec["patent_link"]}

    q = extra.get("q") or ""
    case = fixtures.match_case(q)
    if case is None:
        return {"status": STATUS_NO_FIXTURE, "mode": "fixture", "engine": engine,
                "reason": ("offline demo corpus covers only "
                           f"{', '.join(fixtures.CASE_NAMES)}; set PP_SERPAPI_KEY "
                           "to search anything else"),
                "organic_results": []}

    if engine == "google_patents":
        records, err = fixtures.apply_filters(
            fixtures.patents_for(case), before=extra.get("before", ""),
            assignee=extra.get("assignee", ""))
        if err:
            return {"status": STATUS_ERROR, "mode": "fixture", "engine": engine,
                    "error": err, "organic_results": []}
        return {"status": STATUS_FIXTURE, "mode": "fixture", "engine": engine,
                "organic_results": records}
    if engine == "google_scholar":
        return {"status": STATUS_FIXTURE, "mode": "fixture", "engine": engine,
                "organic_results": fixtures.papers_for(case)}
    return {"status": STATUS_NO_FIXTURE, "mode": "fixture", "engine": engine,
            "reason": f"no offline corpus for engine {engine!r}", "organic_results": []}
