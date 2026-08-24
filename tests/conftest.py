"""Test environment: forced offline, forced in-memory state, isolated guardrail.

Two things are set before `patentpincer.config` is imported:

  * `PP_OFFLINE=true`  - even a developer with a real `PP_SERPAPI_KEY` exported
    must not have the suite spend their SerpApi credits or depend on a network.
    The tests that exercise the live code path install a fake `urlopen` and flip
    this setting explicitly, so the live branch is still covered.
  * `PP_IN_MEMORY_STATE=true` - no Firestore, no GCP credentials.
"""

import os

os.environ["PP_OFFLINE"] = "true"
os.environ["PP_IN_MEMORY_STATE"] = "true"
os.environ.pop("PP_DRY_RUN", None)
os.environ.pop("PP_RUN_ID", None)

import pytest  # noqa: E402

from agent_core import ActionLimiter, ActionPolicy  # noqa: E402

from patentpincer import main, serpapi_tools  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_process_state(monkeypatch):
    """Give every test its own limiter, ledger and run store.

    The limiter and the run store are deliberately process-global in production
    (that is what makes the spend cap and recurrence detection real), so the
    tests have to isolate them or they would leak into each other. The per-cycle
    cap keeps its production value; only the hourly cap is lifted, because one
    process running the whole suite is not one hour of one deployment.
    """
    monkeypatch.setattr(serpapi_tools, "_limiter", ActionLimiter(ActionPolicy(
        dry_run=False,
        max_actions_per_cycle=serpapi_tools.settings.serpapi_calls_per_run,
        max_actions_per_hour=100000,
    )))
    monkeypatch.setattr(serpapi_tools, "_ledger", {})
    main.reset_store()
    yield
    main.reset_store()
