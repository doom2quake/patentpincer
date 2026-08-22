"""Serve PatentPincer's SerpApi tools over MCP (stdio).

Run standalone: `python -m patentpincer.mcp_server`. The agent consumes these
via agent-core's `mcp_toolset` when `PP_MCP_TOOLS=true`, so the load-bearing
SerpApi capability can be served out-of-process and reused by other agents.
Requires the `mcp` extra: `pip install 'agent-core[mcp]'`.

Spend accounting across the process boundary: the server is a separate process,
so it cannot see the caller's in-process run context. Each tool therefore takes
an explicit `run_id` argument, and the caller must pass it for calls to be
grouped into that run's SerpApi spend cycle. If it is omitted, the server falls
back to `PP_RUN_ID` from its environment and then to the shared "adhoc" bucket,
which still caps spend but does not attribute it to a run. This is stated in
the README rather than papered over.
"""

from __future__ import annotations

from agent_core.mcp import serve_stdio

from .serpapi_tools import fetch_patent_details, search_patents, search_scholar

if __name__ == "__main__":
    serve_stdio([search_patents, search_scholar, fetch_patent_details],
                name="patentpincer-serpapi")
