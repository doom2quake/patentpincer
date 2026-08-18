"""Offline demo corpus - three NAMED cases, nothing else.

This module is not a search engine and does not pretend to be one. It holds a
small, hand-written corpus for exactly three demo inventions so the pipeline,
the element matrix, and the UI can be exercised with no SerpApi key and no
network. Anything outside those three cases returns *no fixture*, which the
tools surface as `status="fixture_unavailable"` rather than inventing results.

Two rules keep this honest:

  * Records returned from here are always tagged `mode="fixture"` /
    `status="fixture"`. They are never labelled `ok`, which is reserved for a
    successful live SerpApi response.
  * `before` (priority cutoff) and `assignee` filters are applied to fixture
    records exactly as SerpApi would apply them, so a query that should return
    nothing does return nothing.
"""

from __future__ import annotations

import re
from typing import Any

# Each case: `required` substrings that must ALL appear in the query for the
# case to match. This is deliberately strict - a fixture must not answer a
# question it does not know about.
CASES: dict[str, dict[str, Any]] = {
    "anomaly-remediation": {
        "invention": "a system and method for autonomous anomaly remediation in data pipelines",
        "required": ("anomaly", "pipeline"),
        "patents": [
            {
                "patent_id": "US-11234567-B2",
                "publication_number": "US11234567B2",
                "title": "System and method for autonomous anomaly remediation in data pipelines",
                "snippet": "An agent detects a metric anomaly, diagnoses a root cause, and routes a fix to a destination.",
                "assignee": "Acme Analytics Inc.",
                "priority_date": "2022-05-14",
                "patent_link": "https://patents.google.com/patent/US11234567B2",
                "abstract": (
                    "A pipeline supervisor that detects anomalies in pipeline metrics, diagnoses the "
                    "originating stage, and dispatches a remediation without operator involvement."
                ),
                "claims": [
                    "A system for autonomous anomaly remediation in data pipelines, comprising: a detector "
                    "that identifies a metric anomaly in a data pipeline; a diagnostic engine that determines "
                    "a root cause of the metric anomaly; and a router that dispatches a remediation action to "
                    "a destination selected from the group consisting of an alert channel and a ticket queue.",
                    "The system of claim 1, wherein the detector applies a seasonal baseline to the metric "
                    "before identifying the anomaly.",
                    "The system of claim 1, wherein the remediation action is applied automatically when a "
                    "confidence score exceeds a configured threshold.",
                ],
            },
            {
                "patent_id": "US-10987654-B1",
                "publication_number": "US10987654B1",
                "title": "Prior-art retrieval using structured search over patent corpora",
                "snippet": "A retrieval system queries a structured index to surface anticipatory references for a claim.",
                "assignee": "LexRetrieval LLC",
                "priority_date": "2021-11-02",
                "patent_link": "https://patents.google.com/patent/US10987654B1",
                "abstract": (
                    "Structured retrieval over a patent corpus that ranks candidate references by their "
                    "likelihood of anticipating an input claim."
                ),
                "claims": [
                    "A method of prior-art retrieval, comprising: receiving a claim; constructing a structured "
                    "query over a patent corpus; and ranking candidate references by an anticipation score.",
                    "The method of claim 1, further comprising widening recall by issuing a plurality of "
                    "paraphrased queries against the corpus.",
                ],
            },
            {
                "patent_id": "EP-3891234-A1",
                "publication_number": "EP3891234A1",
                "title": "Method for scoring novelty of an invention against a reference set",
                "snippet": "Claims are decomposed into elements and matched element-by-element against references.",
                "assignee": "Novelis Patent GmbH",
                "priority_date": "2020-03-19",
                "patent_link": "https://patents.google.com/patent/EP3891234A1",
                "abstract": (
                    "Novelty scoring that decomposes a claim into elements and matches each element against "
                    "a reference set to produce an anticipation judgement."
                ),
                "claims": [
                    "A method for scoring novelty, comprising: decomposing a claim into a plurality of "
                    "elements; matching each element against a reference set; and emitting a novelty score.",
                    "The method of claim 1, wherein an element matched by a single reference is marked as "
                    "anticipated.",
                ],
            },
        ],
        "papers": [
            {
                "title": "A Survey of Automated Prior-Art Search",
                "snippet": "Reviews retrieval methods for patentability analysis.",
                "publication_info": {"summary": "J. of IP Informatics, 2023"},
                "year": "2023",
                "link": "https://scholar.example/survey-prior-art",
            },
        ],
    },
    "sweat-hydration": {
        "invention": "a wearable that estimates hydration from sweat conductivity",
        "required": ("sweat", "hydration"),
        "patents": [
            {
                "patent_id": "US-10456789-A",
                "publication_number": "US10456789A",
                "title": "Wearable heart-rate optical sensor array",
                "snippet": "A wearable band carrying an optical sensor array for continuous heart-rate measurement.",
                "assignee": "VitaBand Corp.",
                "priority_date": "2019-07-30",
                "patent_link": "https://patents.google.com/patent/US10456789A",
                "abstract": "A wearable band with an optical sensor array for continuous cardiac monitoring.",
                "claims": [
                    "A wearable band comprising an optical sensor array positioned against a wrist and a "
                    "processor that derives a heart rate from the optical signal.",
                    "The wearable band of claim 1, further comprising an accelerometer used to reject motion "
                    "artefacts from the optical signal.",
                ],
            },
            {
                "patent_id": "WO-2021099887-A1",
                "publication_number": "WO2021099887A1",
                "title": "Electrolyte analysis from perspiration samples",
                "snippet": "Laboratory analysis of electrolyte concentration in a collected perspiration sample.",
                "assignee": "SweatLab SA",
                "priority_date": "2021-01-12",
                "patent_link": "https://patents.google.com/patent/WO2021099887A1",
                "abstract": (
                    "Benchtop determination of sodium and potassium concentration in a perspiration sample "
                    "collected from a subject."
                ),
                "claims": [
                    "A method of analysing electrolyte concentration, comprising: collecting a perspiration "
                    "sample from a subject; and determining a sodium concentration of the sample by ion "
                    "chromatography.",
                    "The method of claim 1, wherein the determined concentration is reported to a clinician.",
                ],
            },
        ],
        "papers": [
            {
                "title": "Non-invasive Hydration Assessment: A Review",
                "snippet": "Surveys bioimpedance, urine specific gravity, and salivary osmolality methods.",
                "publication_info": {"summary": "Sports Medicine Reviews, 2022"},
                "year": "2022",
                "link": "https://scholar.example/hydration-review",
            },
        ],
    },
    "turbine-inspection": {
        "invention": "a drone that inspects wind turbines and files a maintenance ticket",
        "required": ("turbine", "inspect"),
        "patents": [
            {
                "patent_id": "US-11009888-B2",
                "publication_number": "US11009888B2",
                "title": "UAV visual inspection of wind-turbine blades",
                "snippet": "An unmanned aerial vehicle captures imagery of turbine blades and flags surface defects.",
                "assignee": "SkyTurbine Ltd.",
                "priority_date": "2020-09-02",
                "patent_link": "https://patents.google.com/patent/US11009888B2",
                "abstract": (
                    "An unmanned aerial vehicle that performs an automated visual inspection of wind turbine "
                    "blades and classifies surface defects from the captured imagery."
                ),
                "claims": [
                    "An unmanned aerial vehicle configured to perform a visual inspection of wind turbine "
                    "blades, comprising a camera and a defect classifier that flags a surface defect from "
                    "captured imagery.",
                    "The unmanned aerial vehicle of claim 1, wherein the drone follows a predetermined flight "
                    "path around a turbine tower during the inspection.",
                ],
            },
            {
                "patent_id": "US-10777654-B1",
                "publication_number": "US10777654B1",
                "title": "Automated work-order generation from sensor anomalies",
                "snippet": "A maintenance work order is generated automatically when a sensor anomaly is detected.",
                "assignee": "FieldOps Systems",
                "priority_date": "2019-04-18",
                "patent_link": "https://patents.google.com/patent/US10777654B1",
                "abstract": (
                    "Generation of a maintenance work order in an asset-management system in response to a "
                    "detected sensor anomaly."
                ),
                "claims": [
                    "A method comprising: detecting a sensor anomaly on an industrial asset; and generating a "
                    "maintenance work order in an asset-management system in response to the detected anomaly.",
                    "The method of claim 1, wherein the work order is assigned a priority derived from the "
                    "severity of the sensor anomaly.",
                ],
            },
        ],
        "papers": [
            {
                "title": "Autonomous UAV Inspection of Renewable Assets",
                "snippet": "Reviews flight planning and defect detection for turbine and solar-farm inspection.",
                "publication_info": {"summary": "Renewable Systems Letters, 2021"},
                "year": "2021",
                "link": "https://scholar.example/uav-inspection",
            },
        ],
    },
}

CASE_NAMES = tuple(CASES)

#: An invention deliberately outside the corpus. `export-demo` records it too,
#: so the shipped demo contains a real SEARCH_UNAVAILABLE refusal rather than
#: only the three cases that happen to work.
OFF_CORPUS_DEMO = "a quantum teapot that brews tea at absolute zero"


def match_case(query: str) -> str | None:
    """Return the name of the demo case this query belongs to, or None.

    Strict on purpose: every `required` token of a case must appear in the query.
    An unrecognised query gets no fixture rather than someone else's patents.
    """
    q = (query or "").lower()
    for name, case in CASES.items():
        if all(tok in q for tok in case["required"]):
            return name
    return None


def demo_invention(case_name: str) -> str:
    return CASES[case_name]["invention"]


# --- filters (applied to fixtures exactly as SerpApi would apply them) --------

_BEFORE_RE = re.compile(r"^(?:(priority|filing|publication)\s*:\s*)?(\d{8})$")


def _cutoff(before: str) -> str | None:
    """Parse a SerpApi `before` value ("priority:20230101" or "20230101") to ISO."""
    m = _BEFORE_RE.match((before or "").strip())
    if not m:
        return None
    d = m.group(2)
    return f"{d[0:4]}-{d[4:6]}-{d[6:8]}"


def apply_filters(records: list[dict[str, Any]], before: str = "",
                  assignee: str = "") -> tuple[list[dict[str, Any]], str | None]:
    """Filter fixture patents by priority cutoff and assignee.

    Returns (records, error). An unparseable `before` is an error, not a silent
    pass-through: a cutoff the corpus cannot honour must not look honoured.
    """
    out = list(records)
    if before:
        cut = _cutoff(before)
        if cut is None:
            return [], f"unparseable before={before!r} (expected priority:YYYYMMDD)"
        out = [r for r in out if (r.get("priority_date") or "9999-99-99") < cut]
    if assignee:
        needle = assignee.lower().strip()
        out = [r for r in out if needle in (r.get("assignee") or "").lower()]
    return out, None


def patents_for(case_name: str) -> list[dict[str, Any]]:
    return [dict(p) for p in CASES[case_name]["patents"]]


def papers_for(case_name: str) -> list[dict[str, Any]]:
    return [dict(p) for p in CASES[case_name]["papers"]]


def details_for(patent_id: str) -> dict[str, Any] | None:
    """Look up a fixture patent's abstract + claims by id (id form is normalised)."""
    key = re.sub(r"[^a-z0-9]", "", (patent_id or "").lower())
    for case in CASES.values():
        for p in case["patents"]:
            for candidate in (p.get("patent_id"), p.get("publication_number")):
                if candidate and re.sub(r"[^a-z0-9]", "", candidate.lower()) == key:
                    return dict(p)
    return None
