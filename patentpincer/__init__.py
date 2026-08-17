"""PatentPincer - an autonomous patentability analyst built on agent-core.

SerpApi (Google Patents + Scholar) is the load-bearing data backbone; agent-core
provides the multi-agent orchestration, the API-spend guardrails, the verdict
router, and durable run memory. Built for the DevNetwork [API + Cloud + AI]
Hackathon 2026 (SerpApi Best AI Use Case track).
"""

from .config import settings

__all__ = ["settings"]
__version__ = "0.1.0"
