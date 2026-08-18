"""PatentPincer configuration - extends agent-core's BaseSettings.

SerpApi (Google Patents engine) is the load-bearing data backbone; everything
else is the agent layer. No secrets in code: the SerpApi key comes from the env
(`PP_SERPAPI_KEY`) or Secret Manager. When no key is present, the tools run in
OFFLINE fixture mode so the whole pipeline is runnable and demoable without one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agent_core import BaseSettings, env_bool, env_int, env_str


@dataclass(frozen=True)
class PatentPincerSettings(BaseSettings):
    env_prefix: str = "PP"
    app_name: str = "patentpincer"

    # PatentPincer keeps run state in-memory by default, so the CLI works on any
    # machine, including one with a live GCP project and credentials. It does not
    # need durable cloud state to assess an invention. Opt into Firestore (which
    # gives cross-invocation recurrence memory) with PP_IN_MEMORY_STATE=0.
    use_in_memory_state: bool = field(default_factory=lambda: env_bool("PP_IN_MEMORY_STATE", True))

    # SerpApi - the sponsor's load-bearing API. Empty key -> offline demo corpus.
    serpapi_key: str = field(default_factory=lambda: env_str("PP_SERPAPI_KEY"))
    serpapi_endpoint: str = field(default_factory=lambda: env_str("PP_SERPAPI_ENDPOINT", "https://serpapi.com/search"))
    # Force offline even if a key is set (deterministic demo / tests).
    offline: bool = field(default_factory=lambda: env_bool("PP_OFFLINE", False))
    # Cap on how many patents to pull per search (SerpApi spend discipline).
    max_results: int = 10
    # How many phrasings of the invention are searched (recall vs spend).
    max_query_variants: int = field(default_factory=lambda: env_int("PP_MAX_QUERY_VARIANTS", 3))
    # How many shortlisted patents get their full claim text fetched.
    max_detail_fetches: int = field(default_factory=lambda: env_int("PP_MAX_DETAIL_FETCHES", 3))
    # HTTP timeout for a SerpApi call, in seconds.
    timeout_s: int = field(default_factory=lambda: env_int("PP_TIMEOUT_S", 20))

    @property
    def use_serpapi(self) -> bool:
        return bool(self.serpapi_key) and not self.offline

    @property
    def serpapi_calls_per_run(self) -> int:
        """Exactly the SerpApi calls one assessment is allowed to make.

        N patent queries + 1 Scholar query + M claim-text fetches. The spend
        guardrail is sized to this and no larger, so the cap is a real bound on
        a runaway loop. It is deliberately not smaller either: a budget that
        starves the claim fetch silently degrades the novelty analysis, and a
        degraded analysis that still prints a verdict is the exact failure this
        project refuses to ship.
        """
        return self.max_query_variants + 1 + self.max_detail_fetches


settings = PatentPincerSettings()
