"""PatentPincer CLI - assess an invention's patentability end to end.

    patentpincer assess "a wearable that measures hydration from sweat"
    patentpincer assess "..." --no-llm      # deterministic analyst (no GCP needed)
    patentpincer assess "..." --json        # the full run record, including the
                                            # claim-element matrix and the SerpApi
                                            # call ledger
    patentpincer export-demo                # replay the demo cases and write the
                                            # real run records into ui/index.html

Flow: start a run -> gather prior art (SerpApi, guarded) -> fetch the CLAIM TEXT
of the shortlisted references -> compare the invention element by element ->
render a verdict -> route it -> persist the whole causal chain.

Fail-closed rules, enforced here and pinned by tests:

  * If no Google Patents search succeeded (suppressed by the spend guardrail,
    timed out, bad key, quota), the verdict is SEARCH_UNAVAILABLE. A search that
    did not happen is never a clearance.
  * If searches succeeded but returned zero references, or returned references
    whose claim text could not be retrieved, no element-by-element comparison
    happened. An empty comparison scores zero elements disclosed and would read
    as the strongest possible CLEAR, so it is refused instead.
  * If the references came from the offline demo corpus rather than live SerpApi,
    an otherwise-CLEAR result is downgraded to NEEDS_REVIEW. Fixture data can
    warn you off an idea; it cannot clear one.
  * If the LLM path returns a brief without a parseable VERDICT line, it is
    rejected and the deterministic analyst runs instead.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

from agent_core import StateStore, run_agent, signature_of

from . import fixtures, novelty, serpapi_tools
from .config import settings
from .router import build_router, parse_verdict
from .serpapi_tools import (
    LIVE_STATUSES,
    STATUS_OK,
    USABLE_STATUSES,
    fetch_patent_details,
    search_patents,
    search_scholar,
)

# One store per process, so recurrence detection can actually see prior runs
# instead of starting from an empty dict on every assessment.
_STORE: StateStore | None = None


def get_store() -> StateStore:
    global _STORE
    if _STORE is None:
        _STORE = StateStore.create(settings)
    return _STORE


def reset_store() -> None:
    """Drop the process store (tests, and the demo exporter, use this)."""
    global _STORE
    _STORE = None


class _Events:
    """Real event stream for a run: what happened, in order, with real timings."""

    def __init__(self) -> None:
        self._t0 = time.perf_counter()
        self.items: list[dict[str, Any]] = []

    def add(self, stage: str, level: str, message: str, **detail: Any) -> None:
        self.items.append({
            "at_ms": round((time.perf_counter() - self._t0) * 1000, 1),
            "stage": stage, "level": level, "message": message,
            "detail": detail or {},
        })


# --- the deterministic analyst -----------------------------------------------

def _query_variants(invention: str) -> list[str]:
    """2-3 phrasings of the invention, the way the searcher skill widens recall."""
    terms = [w for w in re.findall(r"[a-zA-Z][a-zA-Z0-9\-]*", invention.lower())
             if w not in novelty.STOPWORDS and len(w) > 3]
    out = [invention.strip()]
    if len(terms) >= 3:
        out.append(" ".join(terms[:6]))
    if len(terms) >= 5:
        out.append(" ".join(t for t in terms[:8] if t not in novelty.PREAMBLE))
    seen, uniq = set(), []
    for q in out:
        if q and q not in seen:
            seen.add(q)
            uniq.append(q)
    # Capped so one assessment never exceeds its SerpApi budget.
    return uniq[: settings.max_query_variants]


def gather_evidence(invention: str, events: _Events) -> dict[str, Any]:
    """Run the guarded SerpApi searches and pull claim text for the shortlist."""
    patents: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    statuses: list[str] = []

    for q in _query_variants(invention):
        res = search_patents(q)
        statuses.append(res["status"])
        level = {"ok": "pass", "fixture": "warn"}.get(res["status"], "stop")
        events.add("search", level,
                   f"search_patents q={q!r} -> {res['status']} ({res['count']} hits)",
                   engine="google_patents", status=res["status"], mode=res["mode"],
                   count=res["count"], reason=res.get("reason"))
        for p in res["patents"]:
            pid = p.get("patent_id")
            if pid and pid not in seen_ids:
                seen_ids.add(pid)
                patents.append(p)

    scholar = search_scholar(invention)
    events.add("search", {"ok": "pass", "fixture": "warn"}.get(scholar["status"], "stop"),
               f"search_scholar -> {scholar['status']} ({scholar['count']} papers)",
               engine="google_scholar", status=scholar["status"], mode=scholar["mode"],
               count=scholar["count"], reason=scholar.get("reason"))

    # Claim text for the shortlist. This is what an element-by-element
    # comparison reads; titles and snippets are not claims.
    for p in patents[: settings.max_detail_fetches]:
        det = fetch_patent_details(p["patent_id"])
        p["claims"] = det.get("claims") or []
        p["abstract"] = det.get("abstract")
        p["claims_status"] = det["status"]
        events.add("claims", "pass" if p["claims"] else "warn",
                   f"fetch_patent_details {p['patent_id']} -> {det['status']} "
                   f"({len(p['claims'])} claims)",
                   patent_id=p["patent_id"], status=det["status"],
                   claim_count=len(p["claims"]), reason=det.get("reason"))

    search_ok = any(s in USABLE_STATUSES for s in statuses)
    live = any(s in LIVE_STATUSES for s in statuses)
    # An element-by-element comparison reads claims. If not one shortlisted
    # reference gave up its claim text, the comparison has nothing to compare
    # against and any verdict it produces is an artefact of missing data.
    claims_ok = any(p.get("claims") for p in patents)
    return {
        "patents": patents,
        "papers": scholar["papers"],
        "patent_statuses": statuses,
        "search_ok": search_ok,
        "claims_ok": claims_ok,
        "provenance": "LIVE" if live else ("FIXTURE" if search_ok else "UNAVAILABLE"),
    }


def analyse(invention: str, evidence: dict[str, Any], events: _Events) -> dict[str, Any]:
    """Element-by-element comparison + verdict, with the fail-closed rules applied."""
    if not evidence["search_ok"]:
        reasons = ", ".join(sorted(set(evidence["patent_statuses"]))) or "no search attempted"
        events.add("verdict", "stop",
                   f"No Google Patents search succeeded ({reasons}); failing closed",
                   verdict=novelty.VERDICT_SEARCH_UNAVAILABLE)
        return {
            "verdict": novelty.VERDICT_SEARCH_UNAVAILABLE,
            "provenance": "UNAVAILABLE",
            "matrix": [],
            "judgement": {"rationale": f"prior-art search did not succeed ({reasons})"},
            "downgraded_from": None,
        }

    if not evidence["patents"]:
        # The searches ran and returned nothing. With an empty reference set the
        # matrix scores 0 of N elements disclosed, which reads as the strongest
        # possible CLEAR off the weakest possible evidence. Zero hits usually
        # means the query was too narrow, not that the art does not exist, so
        # the best this can honestly be is NEEDS_REVIEW.
        events.add("verdict", "warn",
                   "Searches succeeded but returned zero references; an empty "
                   "reference set cannot clear an invention",
                   verdict=novelty.VERDICT_NEEDS_REVIEW)
        return {
            "verdict": novelty.VERDICT_NEEDS_REVIEW,
            "provenance": evidence["provenance"],
            "matrix": [],
            "judgement": {"rationale": (
                "the prior-art searches returned zero references, so no element "
                "was compared against anything; a clearance cannot rest on an "
                "empty reference set")},
            "downgraded_from": None,
        }

    if not evidence.get("claims_ok"):
        # References were found but no claim text came back (fetch suppressed by
        # the spend guardrail, detail API error, or no offline claim text). An
        # empty matrix would score 0 elements disclosed and read as CLEAR, so it
        # fails closed instead.
        events.add("verdict", "stop",
                   f"{len(evidence['patents'])} references found but no claim text was "
                   "retrieved for any of them; the element comparison cannot run",
                   verdict=novelty.VERDICT_SEARCH_UNAVAILABLE)
        return {
            "verdict": novelty.VERDICT_SEARCH_UNAVAILABLE,
            "provenance": evidence["provenance"],
            "matrix": [],
            "judgement": {"rationale": (
                f"{len(evidence['patents'])} references were found but no claim text "
                "was retrieved, so no element-by-element comparison was performed")},
            "downgraded_from": None,
        }

    matrix = novelty.build_matrix(invention, evidence["patents"])
    judgement = novelty.judge(matrix)
    events.add("assess", "pass",
               f"Claim-element matrix: {judgement['disclosed']}/{judgement['elements']} "
               f"elements disclosed; closest {judgement['closest'] or 'none'}",
               elements=judgement["elements"], disclosed=judgement["disclosed"],
               best_single_coverage=judgement["best_single_coverage"])

    verdict = judgement["verdict"]
    downgraded_from = None
    if evidence["provenance"] == "FIXTURE" and verdict == novelty.VERDICT_CLEAR:
        downgraded_from = verdict
        verdict = novelty.VERDICT_NEEDS_REVIEW
        events.add("verdict", "warn",
                   "Offline demo corpus cannot clear an invention; CLEAR downgraded "
                   "to NEEDS_REVIEW",
                   downgraded_from=downgraded_from, verdict=verdict)

    level = {"HIGH_OVERLAP": "stop", "NEEDS_REVIEW": "warn"}.get(verdict, "pass")
    events.add("verdict", level, f"VERDICT: {verdict}", verdict=verdict,
               rationale=judgement["rationale"])
    return {"verdict": verdict, "provenance": evidence["provenance"], "matrix": matrix,
            "judgement": judgement, "downgraded_from": downgraded_from}


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _examined(evidence: dict[str, Any]) -> str:
    return (f"Prior art examined: {_plural(len(evidence['patents']), 'patent')}, "
            f"{_plural(len(evidence['papers']), 'paper')}.")


def render_brief(invention: str, evidence: dict[str, Any], analysis: dict[str, Any]) -> str:
    """The decision-ready brief. Line 1 is the machine-readable verdict contract."""
    verdict = analysis["verdict"]
    prov = analysis["provenance"]
    lines = [f"VERDICT: {verdict}", f"PROVENANCE: {prov}"]

    if prov == "FIXTURE":
        lines.append("  Evidence came from the offline demo corpus, not a live SerpApi "
                     "search. Set PP_SERPAPI_KEY for real prior art.")
    elif prov == "UNAVAILABLE":
        lines.append("  No prior-art search succeeded. This is a refusal, not a "
                     "clearance. Do not treat it as one.")
    if analysis["downgraded_from"]:
        lines.append(f"  Assessment on the demo corpus was {analysis['downgraded_from']}; "
                     "downgraded because no live search ran.")

    lines += ["", f"Invention: {invention.strip()}", ""]

    if verdict == novelty.VERDICT_SEARCH_UNAVAILABLE:
        lines.append(analysis["judgement"]["rationale"])
        lines.append("")
        lines.append("This is a refusal, not a clearance.")
        lines.append("")
        lines.append(_examined(evidence))
        if evidence["patents"]:
            lines.append("References found but not compared (no claim text): "
                         + ", ".join(p["patent_id"] for p in evidence["patents"]))
        return "\n".join(lines)

    lines.append("Claim-element matrix (element -> disclosing claim):")
    lines.append(novelty.render_matrix_text(analysis["matrix"]))
    lines.append("")
    lines.append(f"Assessment: {analysis['judgement']['rationale']}.")
    lines.append("")
    lines.append(_examined(evidence))
    cited = [p for p in evidence["patents"] if p.get("claims")]
    if cited:
        lines.append("Citations (claim text retrieved):")
        for i, p in enumerate(cited, start=1):
            lines.append(f"  [{i}] {p['patent_id']} - {p['title']} "
                         f"({p.get('assignee') or 'unknown assignee'}, "
                         f"priority {p.get('priority_date') or 'n/a'}) {p.get('url') or ''}")
    uncited = [p for p in evidence["patents"] if not p.get("claims")]
    if uncited:
        lines.append(f"Not compared (no claim text retrieved): "
                     f"{', '.join(p['patent_id'] for p in uncited)}")
    return "\n".join(lines)


# --- the run ------------------------------------------------------------------

async def assess(invention: str, use_llm: bool = True) -> dict[str, Any]:
    store = get_store()
    run_id = store.start_run(trigger={"invention": invention})
    token = serpapi_tools.bind_run(run_id)
    events = _Events()
    events.add("run", "info", f"Run {run_id} started", run_id=run_id,
               backend=store.backend_name)

    try:
        # The deterministic analyst runs FIRST and owns the run's own SerpApi
        # spend cycle. It produces the verdict, so it must never be the one
        # whose calls get suppressed because an LLM already spent the budget.
        evidence = gather_evidence(invention, events)
        analysis = analyse(invention, evidence, events)

        llm_brief = ""
        if use_llm:
            # The optional narrative gets its own spend cycle (`#narrative`), so
            # its tool calls are capped separately and still land in this run's
            # ledger. See serpapi_tools.ledger_key.
            ntoken = serpapi_tools.bind_run(f"{run_id}#narrative")
            try:
                from .agents import root_agent
                result = await run_agent(root_agent, f"Assess the patentability of: {invention}",
                                         app_name=settings.app_name, session_id=run_id)
                llm_brief = result.state.get("verdict_brief") or result.final_text or ""
                if parse_verdict(llm_brief) is None:
                    events.add("assess", "warn",
                               "LLM brief had no parseable VERDICT line; rejected",
                               chars=len(llm_brief))
                    llm_brief = ""
                else:
                    events.add("assess", "pass", "LLM analyst produced a parseable brief")
            except Exception as exc:
                print(f"[patentpincer] LLM path unavailable ({exc.__class__.__name__}); "
                      "using the deterministic analyst.", file=sys.stderr)
                events.add("assess", "warn",
                           f"LLM path unavailable ({exc.__class__.__name__})")
            finally:
                serpapi_tools.unbind_run(ntoken)

        brief = render_brief(invention, evidence, analysis)
        if llm_brief:
            # The LLM narrative is kept, but the machine-readable contract lines
            # come from the deterministic analyst over the same evidence.
            brief = f"{brief}\n\nAnalyst narrative:\n{llm_brief.strip()}"

        store.set_data(run_id, "verdict", analysis["verdict"])
        store.set_data(run_id, "provenance", analysis["provenance"])
        store.set_data(run_id, "verdict_brief", brief)
        store.set_data(run_id, "matrix", analysis["matrix"])
        store.set_data(run_id, "judgement", analysis["judgement"])
        store.set_data(run_id, "evidence", {"patents": evidence["patents"],
                                            "papers": evidence["papers"]})
        store.set_data(run_id, "serpapi_calls", serpapi_tools.calls_for(run_id))

        router = build_router(store_recorder=lambda n, o, d: store.record_guardrail(run_id, n, o, d))
        routing = router.route({
            "title": f"Patentability [{analysis['verdict']}]: {invention[:60]}",
            "summary": brief, "verdict": analysis["verdict"],
            "kind": "patentability", "run_id": run_id,
        })
        store.set_data(run_id, "routing", routing)
        events.add("route", "warn" if "alert" in routing["route"] else "pass",
                   f"Routed to domain {routing['domain']} via "
                   f"{', '.join(routing['route'])}",
                   domain=routing["domain"],
                   handlers=[(h["handler"], h["status"]) for h in routing["handlers"]])

        recurrence = store.detect_recurrence(
            run_id, signature_of("invention", invention.lower().strip()))
        if recurrence:
            events.add("state", "warn",
                       f"Recurrence: this invention was assessed "
                       f"{recurrence['count']} times in {recurrence['window_days']}d",
                       recurrence=recurrence)
        else:
            events.add("state", "info",
                       "Recurrence: first assessment of this invention")

        events.add("run", "pass", "Run complete")
        store.set_data(run_id, "events", events.items)
        store.set_status(run_id, "completed")
        return {
            "run_id": run_id, "brief": brief, "verdict": analysis["verdict"],
            "provenance": analysis["provenance"], "matrix": analysis["matrix"],
            "judgement": analysis["judgement"], "routing": routing,
            "patents": evidence["patents"], "papers": evidence["papers"],
            "serpapi_calls": serpapi_tools.calls_for(run_id),
            "events": events.items, "recurrence": recurrence,
            "state_backend": store.backend_name,
        }
    except Exception as exc:
        store.fail(run_id, f"{exc.__class__.__name__}: {exc}")
        raise
    finally:
        serpapi_tools.unbind_run(token)


# --- demo export (records REAL runs into the UI) ------------------------------

_UI_BEGIN = "/* RUNS:BEGIN - generated by `patentpincer export-demo`; do not edit by hand */"
_UI_END = "/* RUNS:END */"


def demo_cases() -> list[tuple[str, str]]:
    """(case name, invention) for every run the demo export records.

    The three corpus cases plus one invention the corpus deliberately does not
    cover, so the shipped demo shows the refusal path as well as the happy one.
    """
    cases = [(n, fixtures.demo_invention(n)) for n in fixtures.CASE_NAMES]
    cases.append(("off-corpus-refusal", fixtures.OFF_CORPUS_DEMO))
    return cases


def export_demo(ui_path: Path) -> dict[str, Any]:
    """Run the demo cases for real and inject the run records into the UI.

    The UI does not invent a trace. It replays what this function recorded: the
    real event stream with its real millisecond timings, the real SerpApi call
    ledger (offline statuses included), the real claim-element matrix with the
    excerpts that carried each match, the real routing decision, and the brief
    byte for byte as the CLI printed it.
    """
    runs = []
    for name, invention in demo_cases():
        out = asyncio.run(assess(invention, use_llm=False))
        runs.append({
            "case": name, "invention": invention, "verdict": out["verdict"],
            "provenance": out["provenance"], "judgement": out["judgement"],
            "matrix": out["matrix"], "events": out["events"],
            "serpapi_calls": out["serpapi_calls"], "routing": out["routing"],
            "brief": out["brief"],
            "patents": [{k: p.get(k) for k in
                         ("patent_id", "title", "assignee", "priority_date", "url")}
                        for p in out["patents"]],
            "papers": out["papers"],
        })
    payload = {"generated_by": "patentpincer export-demo",
               "mode": ("live SerpApi" if settings.use_serpapi else "offline demo corpus"),
               "runs": runs}
    blob = "var PP_RUNS = " + json.dumps(payload, indent=1) + ";"

    text = ui_path.read_text()
    start, end = text.find(_UI_BEGIN), text.find(_UI_END)
    if start < 0 or end < 0:
        raise SystemExit(f"{ui_path} has no RUNS:BEGIN/RUNS:END markers")
    ui_path.write_text(text[:start] + _UI_BEGIN + "\n" + blob + "\n" + text[end:])
    return payload


# --- CLI ----------------------------------------------------------------------

def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="patentpincer",
                                     description="Autonomous patentability analyst.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("assess", help="Assess an invention's patentability.")
    a.add_argument("invention", help="The invention / claim description.")
    a.add_argument("--no-llm", action="store_true",
                   help="Deterministic analyst only (no GCP).")
    a.add_argument("--json", action="store_true", help="Print the full run record as JSON.")
    e = sub.add_parser("export-demo",
                       help="Replay the demo cases and write the real runs into the UI.")
    e.add_argument("--ui", default=str(Path(__file__).resolve().parents[1] / "ui" / "index.html"))
    args = parser.parse_args(argv)

    if args.cmd == "export-demo":
        payload = export_demo(Path(args.ui))
        for r in payload["runs"]:
            print(f"{r['case']:>22}  {r['verdict']:<19} provenance={r['provenance']}  "
                  f"{len(r['events'])} events, {len(r['serpapi_calls'])} SerpApi calls")
        print(f"\nwrote {len(payload['runs'])} recorded runs into {args.ui}")
        return 0

    if args.cmd == "assess":
        out = asyncio.run(assess(args.invention, use_llm=not args.no_llm))
        if args.json:
            print(json.dumps({k: v for k, v in out.items() if k != "brief"}, indent=2,
                             default=str))
            return 0
        print("\n" + out["brief"])
        r = out["routing"]
        print(f"\n-- routed: domain={r['domain']} via {r['route']} "
              f"-> {[(h['handler'], h['status']) for h in r['handlers']]}")
        calls = out["serpapi_calls"]
        print(f"-- serpapi: {len(calls)} calls "
              f"[{', '.join(sorted({c['status'] for c in calls}))}]")
        print(f"-- run={out['run_id']} state={out['state_backend']}")
        return 0 if out["verdict"] != novelty.VERDICT_SEARCH_UNAVAILABLE else 2
    return 1


if __name__ == "__main__":
    raise SystemExit(cli())


# `search_patents` / `search_scholar` are re-exported for the skills module.
__all__ = ["assess", "cli", "export_demo", "gather_evidence", "analyse", "render_brief",
           "get_store", "reset_store", "search_patents", "search_scholar",
           "fetch_patent_details", "STATUS_OK"]
