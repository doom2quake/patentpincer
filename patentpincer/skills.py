"""PatentPincer skills - the patentability workflow as named capabilities.

Assembled into an ADK supervisor in `agents.py`. The mapping capability -> agent
lives in one place (agent-core's `Skill`). The workflow mirrors how a patent
attorney actually works: search prior art, decompose the claim and compare it
element-by-element, then render a patentability verdict with citations.
"""

from __future__ import annotations

from agent_core import Skill

from .config import settings
from .serpapi_tools import fetch_patent_details, search_patents, search_scholar

# --- 1) search prior art (SerpApi = the load-bearing data backbone) -----------

SEARCH_PRIOR_ART = Skill(
    name="search-prior-art",
    summary=(
        "Finds prior art for an invention using SerpApi's Google Patents and "
        "Scholar engines, then pulls the claim text of the shortlist. Use first, "
        "to gather the reference set."
    ),
    model=settings.model_fast,
    instruction=(
        "You are PatentPincer's Prior-Art Searcher. Given an invention "
        "description, extract the core technical concepts and search for "
        "anticipatory references. Call `search_patents` with focused queries "
        "(vary the phrasing across 2-3 calls to widen recall), and call "
        "`search_scholar` once for non-patent literature. If a likely filing or "
        "priority date is mentioned, pass `before` to `search_patents` so you "
        "only surface art that predates it. Then call `fetch_patent_details` for "
        "the three closest patents so the analyst has their NUMBERED CLAIMS, not "
        "just snippets. Report every reference with its `status` and `mode`: a "
        "result with mode='fixture' is offline demo data, not evidence, and you "
        "must say so. If a search returns status 'suppressed', 'error', or "
        "'fixture_unavailable', report that plainly rather than continuing as if "
        "you had results. Do NOT judge novelty here - just assemble the evidence."
    ),
    tools=[search_patents, search_scholar, fetch_patent_details],
    output_key="prior_art",
)

# --- 2) assess novelty (element-by-element, the analyst) ----------------------

ASSESS_NOVELTY = Skill(
    name="assess-novelty",
    summary=(
        "Decomposes the claim into elements and compares each against the prior "
        "art to judge novelty and obviousness. Use after prior art is gathered."
    ),
    model=settings.model_deep,
    instruction=(
        "You are PatentPincer's Novelty Analyst. Read the invention and the "
        "prior_art from session state. Decompose the invention into its "
        "independent claim ELEMENTS (the distinct technical features). For each "
        "element, cite the specific REFERENCE AND CLAIM NUMBER that discloses it, "
        "quoting the claim language, or state that it appears novel. Only claim "
        "text you were actually given counts; if a reference has no claims in "
        "prior_art, say the claims were not retrieved rather than reasoning from "
        "its title. Then assess: (a) NOVELTY - is every element anticipated by a "
        "single reference? (b) OBVIOUSNESS - is the combination an obvious mix of "
        "references a skilled person would make? Conclude with the single closest "
        "reference and the strongest distinguishing element. Be precise and cite; "
        "an examiner or attorney will rely on this. Do not overstate - if the "
        "closest art is a near-hit, say so."
    ),
    tools=[],
    output_key="novelty_assessment",
)

# --- 3) render the verdict + brief (decision-ready) ---------------------------

RENDER_VERDICT = Skill(
    name="render-verdict",
    summary=(
        "Produces the decision-ready patentability brief and a routing-friendly "
        "verdict. Use last, once novelty has been assessed."
    ),
    model=settings.model_fast,
    instruction=(
        "You are PatentPincer's Brief Writer. From the novelty_assessment in "
        "session state, produce a concise patentability brief for a founder or "
        "attorney:\n"
        "  1. VERDICT - one of: CLEAR (novel, worth filing), NEEDS_REVIEW "
        "(narrow the claims first), HIGH_OVERLAP (likely anticipated), or "
        "SEARCH_UNAVAILABLE (no prior-art search succeeded).\n"
        "  2. The single closest reference and why it does or does not anticipate.\n"
        "  3. A recommended next step (file / narrow claims to element X / redesign).\n"
        "  4. The citation list.\n"
        "Your FIRST line must be exactly 'VERDICT: <TOKEN>' with nothing else on "
        "it, because the router parses that line and rejects the brief if it is "
        "malformed. If the searcher reported suppressed, failed, or fixture-only "
        "results, the verdict is SEARCH_UNAVAILABLE and never CLEAR: a search that "
        "did not happen is not a clearance. Keep it under 250 words, "
        "decision-ready, no hedging beyond what the evidence warrants."
    ),
    tools=[],
    output_key="verdict_brief",
)

CATALOGUE = [SEARCH_PRIOR_ART, ASSESS_NOVELTY, RENDER_VERDICT]
