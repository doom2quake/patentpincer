"""PatentPincer tests.

Every test here pins a rule the product depends on being true. They are grouped
by the thing they protect:

  1. provenance      - offline demo records are never labelled as live evidence
  2. claim text      - the element comparison reads numbered claims, not snippets
  3. fail-closed     - a search that did not happen is never a clearance
  4. the router      - the verdict is a parsed contract, not keyword-scanned prose
  5. spend + context - concurrent runs and MCP callers keep their own budgets
  6. lifecycle       - one process store, explicit completed/error status
  7. the UI          - the shipped page replays runs that really happened

The whole suite runs offline (see conftest). The live SerpApi branch is covered
with a fake `urlopen`, so the parsing, the error handling and the LIVE
provenance label are exercised without a funded key.
"""

import asyncio
import dataclasses
import io
import json
import os
import sys
from pathlib import Path

import pytest

from agent_core import ActionLimiter, ActionPolicy

from patentpincer import fixtures, main, novelty, serpapi_tools
from patentpincer.main import assess, get_store
from patentpincer.router import (
    DOMAIN_CLEAR,
    DOMAIN_HIGH_OVERLAP,
    DOMAIN_MALFORMED,
    DOMAIN_SEARCH_UNAVAILABLE,
    build_router,
    parse_verdict,
)

ANOMALY = "a system and method for autonomous anomaly remediation in data pipelines"
OFF_CORPUS = fixtures.OFF_CORPUS_DEMO
UI = Path(__file__).resolve().parents[1] / "ui" / "index.html"


# --- helpers: the live SerpApi branch, without a funded key ------------------

def use_live(monkeypatch, responses):
    """Point the tools at a fake SerpApi. `responses` maps engine -> body/exception."""
    live = dataclasses.replace(serpapi_tools.settings, serpapi_key="test-key", offline=False)
    monkeypatch.setattr(serpapi_tools, "settings", live)
    assert live.use_serpapi is True

    calls = []

    def fake_urlopen(url, timeout=None):
        engine = url.split("engine=", 1)[1].split("&", 1)[0]
        calls.append(url)
        body = responses[engine]
        if isinstance(body, Exception):
            raise body
        return io.BytesIO(json.dumps(body).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    return calls


# --- 1. provenance ------------------------------------------------------------

def test_offline_records_are_labelled_fixture_and_never_ok():
    r = serpapi_tools.search_patents(ANOMALY)
    assert r["status"] == serpapi_tools.STATUS_FIXTURE
    assert r["status"] != serpapi_tools.STATUS_OK
    assert r["mode"] == "fixture"
    assert r["count"] >= 1
    assert all(p["provenance"] == "fixture" for p in r["patents"])


def test_offline_refuses_a_query_outside_the_demo_corpus():
    r = serpapi_tools.search_patents(OFF_CORPUS)
    assert r["status"] == serpapi_tools.STATUS_NO_FIXTURE
    assert r["count"] == 0
    assert r["patents"] == []
    assert "PP_SERPAPI_KEY" in r["reason"]


def test_offline_scholar_refuses_an_unknown_query():
    # "prior art search" is not one of the three demo cases: no papers, no pretence.
    r = serpapi_tools.search_scholar("prior art search")
    assert r["status"] == serpapi_tools.STATUS_NO_FIXTURE
    assert r["papers"] == []


def test_offline_honours_the_priority_cutoff():
    every = serpapi_tools.search_patents(ANOMALY)
    assert every["count"] == 3
    # Every fixture record has a 2020+ priority date.
    cut = serpapi_tools.search_patents(ANOMALY, before="priority:20100101")
    assert cut["status"] == serpapi_tools.STATUS_FIXTURE
    assert cut["count"] == 0, "a 2010 cutoff must not return 2020-2022 records"


def test_offline_rejects_an_unparseable_cutoff_instead_of_ignoring_it():
    r = serpapi_tools.search_patents(ANOMALY, before="last tuesday")
    assert r["status"] == serpapi_tools.STATUS_ERROR
    assert r["count"] == 0
    assert "unparseable" in r["reason"]


def test_offline_honours_the_assignee_filter():
    hit = serpapi_tools.search_patents(ANOMALY, assignee="Acme")
    assert [p["patent_id"] for p in hit["patents"]] == ["US-11234567-B2"]
    miss = serpapi_tools.search_patents(ANOMALY, assignee="Nonexistent Holdings")
    assert miss["count"] == 0


def test_live_response_cannot_relabel_its_own_provenance(monkeypatch):
    # A remote payload carrying `status`/`mode` keys must not overwrite ours.
    use_live(monkeypatch, {"google_patents": {
        "status": "Success", "mode": "fixture",
        "organic_results": [{"patent_id": "US-1-A", "title": "t"}],
    }})
    r = serpapi_tools.search_patents(ANOMALY)
    assert r["status"] == serpapi_tools.STATUS_OK
    assert r["mode"] == "live"


# --- 2. claim text ------------------------------------------------------------

def test_fetch_patent_details_returns_numbered_claims():
    d = serpapi_tools.fetch_patent_details("US-11234567-B2")
    assert d["status"] == serpapi_tools.STATUS_FIXTURE
    assert [c["number"] for c in d["claims"]] == [1, 2, 3]
    assert "detector" in d["claims"][0]["text"]
    assert d["abstract"]


def test_fetch_patent_details_refuses_an_unknown_patent():
    d = serpapi_tools.fetch_patent_details("US-0000000-B9")
    assert d["status"] == serpapi_tools.STATUS_NO_FIXTURE
    assert d["claims"] == []


def test_matrix_cells_cite_a_claim_number_and_quote_the_claim():
    out = asyncio.run(assess(ANOMALY, use_llm=False))
    disclosed = [row for row in out["matrix"] if row["disclosed"]]
    assert disclosed, "the anomaly case must disclose at least one element"
    claim_text = " ".join(
        c["text"] for c in serpapi_tools.fetch_patent_details("US-11234567-B2")["claims"])
    for row in disclosed:
        best = row["best"]
        assert best["claim_number"] >= 1
        assert best["matched_terms"]
        # The excerpt is quoted from the claim, not paraphrased.
        assert best["excerpt"].strip(". ").lstrip(".") in claim_text or \
            best["excerpt"].strip(".").strip() in claim_text


def test_anomaly_case_is_high_overlap_with_a_named_closest_reference():
    out = asyncio.run(assess(ANOMALY, use_llm=False))
    assert out["verdict"] == novelty.VERDICT_HIGH_OVERLAP
    assert out["judgement"]["closest"] == "US-11234567-B2"
    assert out["routing"]["domain"] == DOMAIN_HIGH_OVERLAP
    assert out["routing"]["route"] == ["alert", "ticket"]


# --- 3. fail closed -----------------------------------------------------------

def test_dry_run_never_produces_a_clearance(monkeypatch):
    monkeypatch.setattr(serpapi_tools, "_limiter", ActionLimiter(ActionPolicy(
        dry_run=True, max_actions_per_cycle=9, max_actions_per_hour=9)))
    out = asyncio.run(assess(ANOMALY, use_llm=False))
    assert out["verdict"] == novelty.VERDICT_SEARCH_UNAVAILABLE
    assert out["provenance"] == "UNAVAILABLE"
    assert out["brief"].splitlines()[0] == "VERDICT: SEARCH_UNAVAILABLE"
    assert "This is a refusal, not a clearance." in out["brief"]
    assert {c["status"] for c in out["serpapi_calls"]} == {serpapi_tools.STATUS_SUPPRESSED}
    assert out["routing"]["domain"] == DOMAIN_SEARCH_UNAVAILABLE
    assert out["routing"]["route"] == ["alert", "ticket"]


def test_a_query_the_corpus_does_not_cover_is_refused_not_cleared():
    out = asyncio.run(assess(OFF_CORPUS, use_llm=False))
    assert out["verdict"] == novelty.VERDICT_SEARCH_UNAVAILABLE
    assert out["matrix"] == []


def test_api_timeout_fails_closed(monkeypatch):
    use_live(monkeypatch, {
        "google_patents": TimeoutError("timed out"),
        "google_scholar": TimeoutError("timed out"),
    })
    out = asyncio.run(assess(ANOMALY, use_llm=False))
    assert out["verdict"] == novelty.VERDICT_SEARCH_UNAVAILABLE
    assert all(c["status"] == serpapi_tools.STATUS_ERROR for c in out["serpapi_calls"])


def test_api_level_error_body_fails_closed(monkeypatch):
    # SerpApi reports quota / bad-key failures with HTTP 200 and an `error` field.
    use_live(monkeypatch, {
        "google_patents": {"error": "Invalid API key"},
        "google_scholar": {"error": "Invalid API key"},
    })
    out = asyncio.run(assess(ANOMALY, use_llm=False))
    assert out["verdict"] == novelty.VERDICT_SEARCH_UNAVAILABLE
    assert "Invalid API key" in out["serpapi_calls"][0]["reason"]


def test_zero_search_results_is_not_a_clearance(monkeypatch):
    use_live(monkeypatch, {"google_patents": {"organic_results": []},
                           "google_scholar": {"organic_results": []}})
    out = asyncio.run(assess(ANOMALY, use_llm=False))
    assert out["verdict"] != novelty.VERDICT_CLEAR
    assert out["verdict"] == novelty.VERDICT_NEEDS_REVIEW
    assert "empty reference set" in out["judgement"]["rationale"]


def test_references_without_claim_text_are_not_compared(monkeypatch):
    use_live(monkeypatch, {
        "google_patents": {"organic_results": [
            {"patent_id": "US-9999999-B2", "title": "Something adjacent",
             "snippet": "autonomous anomaly remediation in data pipelines"}]},
        "google_scholar": {"organic_results": []},
        # The details API answers, but with no claims (redacted / unavailable).
        "google_patents_details": {"title": "Something adjacent", "claims": []},
    })
    out = asyncio.run(assess(ANOMALY, use_llm=False))
    assert out["verdict"] == novelty.VERDICT_SEARCH_UNAVAILABLE
    assert "no claim text" in out["brief"]
    assert "US-9999999-B2" in out["brief"]


def test_a_fixture_run_can_warn_but_never_clear():
    # This invention scores CLEAR on the demo corpus; it must still not be issued
    # as one, because the corpus is not evidence.
    out = asyncio.run(assess(fixtures.demo_invention("sweat-hydration"), use_llm=False))
    assert out["provenance"] == "FIXTURE"
    assert out["verdict"] == novelty.VERDICT_NEEDS_REVIEW
    assert out["judgement"]["verdict"] == novelty.VERDICT_CLEAR
    downgrades = [e for e in out["events"] if e["detail"].get("downgraded_from")]
    assert downgrades and downgrades[0]["detail"]["downgraded_from"] == novelty.VERDICT_CLEAR
    assert "downgraded because no live search ran" in out["brief"]


def test_a_live_run_with_unrelated_art_can_clear(monkeypatch):
    # The downgrade is driven by provenance, not by a refusal to ever say CLEAR.
    use_live(monkeypatch, {
        "google_patents": {"organic_results": [
            {"patent_id": "US-1111111-B2", "title": "Bicycle chain tensioner",
             "assignee": "Velo AG", "priority_date": "2015-01-01"}]},
        "google_scholar": {"organic_results": []},
        "google_patents_details": {"title": "Bicycle chain tensioner", "claims": [
            "A bicycle chain tensioner comprising a spring-loaded arm engaging a chain."]},
    })
    out = asyncio.run(assess(ANOMALY, use_llm=False))
    assert out["provenance"] == "LIVE"
    assert out["verdict"] == novelty.VERDICT_CLEAR
    assert out["brief"].splitlines()[1] == "PROVENANCE: LIVE"


# --- 4. the router ------------------------------------------------------------

def test_a_clear_brief_that_mentions_high_overlap_is_still_clear():
    router = build_router()
    rec = router.route({"title": "Patentability report",
                        "summary": "VERDICT: CLEAR\nNo high overlap was found in the art."})
    assert rec["domain"] == DOMAIN_CLEAR
    assert [h["handler"] for h in rec["handlers"]] == ["ticket"]


def test_high_overlap_raises_an_alert_and_a_ticket():
    router = build_router()
    rec = router.route({"summary": "VERDICT: HIGH_OVERLAP\nClosest reference: US-1",
                        "title": "x"})
    assert rec["domain"] == DOMAIN_HIGH_OVERLAP
    assert rec["route"] == ["alert", "ticket"]


def test_a_malformed_verdict_is_never_guessed_at():
    router = build_router()
    rec = router.route({"summary": "I think this is CLEAR, probably.", "title": "x"})
    assert rec["domain"] == DOMAIN_MALFORMED
    assert [h["handler"] for h in rec["handlers"]] == ["ticket"]


@pytest.mark.parametrize("text,expected", [
    ("VERDICT: CLEAR", "CLEAR"),
    ("\n\n  VERDICT: NEEDS_REVIEW  \nrest", "NEEDS_REVIEW"),
    ("VERDICT: SEARCH_UNAVAILABLE\nno search ran", "SEARCH_UNAVAILABLE"),
    ("Summary\nVERDICT: CLEAR", None),          # not the first non-empty line
    ("VERDICT: CLEAR (probably)", None),        # trailing commentary
    ("VERDICT: MAYBE", None),                   # unknown token
    ("", None),
])
def test_parse_verdict_is_a_strict_contract(text, expected):
    assert parse_verdict(text) == expected


# --- 5. spend cycles and run context -----------------------------------------

def test_an_explicit_run_id_beats_the_ambient_context():
    # This is the MCP path: a separate process has no ambient context, so the
    # caller passes run_id and the call must be booked against it.
    token = serpapi_tools.bind_run("run-ambient")
    try:
        serpapi_tools.search_patents(ANOMALY, run_id="run-explicit")
    finally:
        serpapi_tools.unbind_run(token)
    assert serpapi_tools.calls_for("run-ambient") == []
    assert len(serpapi_tools.calls_for("run-explicit")) == 1


def test_concurrent_assessments_do_not_share_a_ledger_or_a_budget():
    async def both():
        return await asyncio.gather(
            assess(ANOMALY, use_llm=False),
            assess(fixtures.demo_invention("turbine-inspection"), use_llm=False),
        )

    a, b = asyncio.run(both())
    assert a["run_id"] != b["run_id"]
    assert a["serpapi_calls"] and b["serpapi_calls"]
    # Neither run was starved by the other's spend cycle.
    for out in (a, b):
        assert serpapi_tools.STATUS_SUPPRESSED not in {c["status"] for c in out["serpapi_calls"]}
    assert "anomaly" in a["brief"] and "turbine" in b["brief"]


def test_the_narrative_cycle_cannot_starve_the_analyst():
    cap = serpapi_tools.settings.serpapi_calls_per_run
    token = serpapi_tools.bind_run("run-z#narrative")
    try:
        for _ in range(cap):
            serpapi_tools.search_patents(ANOMALY)
        starved = serpapi_tools.search_patents(ANOMALY)
    finally:
        serpapi_tools.unbind_run(token)
    assert starved["status"] == serpapi_tools.STATUS_SUPPRESSED, "the cap must still bite"

    token = serpapi_tools.bind_run("run-z")
    try:
        analyst = serpapi_tools.search_patents(ANOMALY)
    finally:
        serpapi_tools.unbind_run(token)
    assert analyst["status"] == serpapi_tools.STATUS_FIXTURE
    # One assessment, one ledger: both cycles are attributed to the same run.
    ledger = serpapi_tools.calls_for("run-z")
    assert len(ledger) == cap + 2
    assert {c["cycle"] for c in ledger} == {"run-z", "run-z#narrative"}


def test_the_mcp_server_serves_the_tools_over_a_real_process_boundary():
    """Boot `python -m patentpincer.mcp_server` and call a tool over stdio.

    This is the claim that SerpApi capability is reusable by other agents, so it
    is exercised rather than asserted: the server really starts, really lists the
    three tools, and books the call against the `run_id` the client passed, which
    is the only way spend can be attributed across a process boundary.
    """
    mcp = pytest.importorskip("mcp", reason="MCP transport needs `pip install 'agent-core[mcp]'`")
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = dict(os.environ, PP_OFFLINE="true", PP_IN_MEMORY_STATE="true",
               PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    params = StdioServerParameters(command=sys.executable,
                                   args=["-m", "patentpincer.mcp_server"], env=env)

    async def call():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                result = await session.call_tool(
                    "search_patents", {"query": ANOMALY, "run_id": "run-mcp"})
                return [t.name for t in listed.tools], result.content[0].text

    names, payload = asyncio.run(call())
    assert set(names) == {"search_patents", "search_scholar", "fetch_patent_details"}
    assert "'run_id': 'run-mcp'" in payload
    assert "'status': 'fixture'" in payload, "provenance survives the MCP boundary"
    assert "US-11234567-B2" in payload
    del mcp


def test_the_spend_cap_is_exactly_one_assessment():
    out = asyncio.run(assess(ANOMALY, use_llm=False))
    cap = serpapi_tools.settings.serpapi_calls_per_run
    assert len(out["serpapi_calls"]) <= cap
    assert serpapi_tools.STATUS_SUPPRESSED not in {c["status"] for c in out["serpapi_calls"]}


# --- 6. run lifecycle ---------------------------------------------------------

def test_the_store_is_process_scoped_and_sees_the_earlier_run():
    first = asyncio.run(assess(ANOMALY, use_llm=False))
    second = asyncio.run(assess(ANOMALY, use_llm=False))
    assert first["recurrence"] is None
    assert second["recurrence"] is not None
    assert second["recurrence"]["count"] >= 1
    assert get_store().get(first["run_id"])["status"] == "completed"


def test_a_crashed_run_is_recorded_as_an_error(monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("serpapi exploded")

    monkeypatch.setattr(main, "gather_evidence", boom)
    with pytest.raises(RuntimeError):
        asyncio.run(assess(ANOMALY, use_llm=False))
    runs = get_store().list(5)
    assert runs and runs[0]["status"] == "error"
    assert "serpapi exploded" in runs[0]["error"]


# --- 7. the shipped UI --------------------------------------------------------

def _ui_runs():
    text = UI.read_text()
    start = text.index("var PP_RUNS = ") + len("var PP_RUNS = ")
    end = text.index("/* RUNS:END */")
    return json.loads(text[start:end].rstrip().rstrip(";"))


def test_the_ui_replays_runs_that_really_happened():
    payload = _ui_runs()
    recorded = {r["invention"]: r for r in payload["runs"]}
    assert set(recorded) == {inv for _, inv in main.demo_cases()}
    for invention, shown in recorded.items():
        fresh = asyncio.run(assess(invention, use_llm=False))
        assert shown["verdict"] == fresh["verdict"], invention
        assert shown["provenance"] == fresh["provenance"], invention
        assert len(shown["matrix"]) == len(fresh["matrix"]), invention
        assert shown["brief"] == fresh["brief"], invention


def test_the_ui_does_not_claim_live_data_it_never_had():
    payload = _ui_runs()
    assert payload["mode"] == "offline demo corpus"
    assert {r["provenance"] for r in payload["runs"]} <= {"FIXTURE", "UNAVAILABLE"}
    assert any(r["verdict"] == novelty.VERDICT_SEARCH_UNAVAILABLE for r in payload["runs"]), \
        "the shipped demo must include the refusal path, not only the happy one"
    assert all(r["verdict"] != novelty.VERDICT_CLEAR for r in payload["runs"])
