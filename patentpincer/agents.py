"""PatentPincer agent graph - a supervisor over the three patentability skills.

Assembled with agent-core's `build_supervisor`, so the whole capability -> agent
mapping is one call. The Prior-Art searcher can optionally source its SerpApi
tools over MCP (PP_MCP_TOOLS=true); otherwise it uses in-process functions.
"""

from __future__ import annotations

from agent_core import agent_from_skill, build_supervisor
from agent_core.mcp import mcp_toolset

from .skills import ASSESS_NOVELTY, RENDER_VERDICT, SEARCH_PRIOR_ART

# Optional: serve the SerpApi tools over MCP (off by default).
_mcp = mcp_toolset("patentpincer.mcp_server",
                   tool_filter=["search_patents", "search_scholar", "fetch_patent_details"],
                   env_flag="PP_MCP_TOOLS")
_searcher = agent_from_skill(
    SEARCH_PRIOR_ART,
    tools=([_mcp] if _mcp is not None else list(SEARCH_PRIOR_ART.tools)),
)

root_agent = build_supervisor(
    name="patentpincer_supervisor",
    description=(
        "PatentPincer - an autonomous patentability analyst. Searches prior art, "
        "assesses novelty element-by-element, and renders a decision-ready verdict."
    ),
    instruction=(
        "You are PatentPincer, an autonomous patentability analyst. Given an "
        "invention description, run the workflow by delegating IN ORDER:\n"
        "  1. Transfer to `search_prior_art_agent` to gather patent + scholar references.\n"
        "  2. Transfer to `assess_novelty_agent` to compare the claim elements "
        "against that prior art.\n"
        "  3. Transfer to `render_verdict_agent` to produce the verdict + brief.\n"
        "Keep the user informed at each step. Your final message is the "
        "patentability brief, beginning with the VERDICT line."
    ),
    skills=[SEARCH_PRIOR_ART, ASSESS_NOVELTY, RENDER_VERDICT],
    sub_agents=[_searcher, agent_from_skill(ASSESS_NOVELTY), agent_from_skill(RENDER_VERDICT)],
)
