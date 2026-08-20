"""Element-by-element novelty comparison - the actual computation.

This is the part a patent attorney does by hand and the part most "AI patent
search" demos skip: take the invention apart into its claim ELEMENTS, take each
cited reference's NUMBERED CLAIMS, and decide, per element, whether some claim
of some reference discloses it.

Nothing here is a language model and nothing here is random. Given the same
invention and the same claim text it produces the same matrix every time, which
is what makes the output checkable: every cell names the reference, the claim
number, the matched terms, and the excerpt the match came from.

The comparison itself is deliberately simple and stated plainly rather than
dressed up: light suffix stemming, stopword removal, and term containment of the
element in the claim. It is a first-pass screen, not a legal opinion. What makes
it useful is that it is transparent, so a reviewer can see exactly which words
carried a match and overrule it.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

# --- tokenisation ------------------------------------------------------------

STOPWORDS = frozenset("""
a an the and or of for to in on at by with from into onto via as is are be being
been that which who whom whose this these those it its their there where when
such said comprising comprises comprise including includes include wherein
thereof therein having has have had also least one plus per any all each other
another same between during upon than then so but if not no nor
""".split())

#: Claim-preamble nouns. A segment made only of these is boilerplate, not a
#: technical limitation, so it is dropped ("a system and method for ..." adds
#: nothing to a novelty comparison).
PREAMBLE = frozenset({"system", "method", "apparatus", "device", "process",
                      "means", "assembly", "arrangement", "product"})

#: Boundaries a claim limitation tends to break on.
_SPLIT = re.compile(
    r"(?:[;,]|\band\b|\bor\b|\bwherein\b|\bthat\b|\bwhich\b|\bthen\b|"
    r"\bfor\b|\busing\b|\bwith\b|\bfrom\b|\bvia\b|\bin\b|\bby\b|\bbased on\b)",
    re.IGNORECASE,
)

_SUFFIXES = (("ations", "at"), ("ation", "at"), ("ions", ""), ("ion", ""),
             ("ing", ""), ("edly", ""), ("ers", ""), ("er", ""),
             ("ed", ""), ("es", ""), ("s", ""))


def stem(word: str) -> str:
    """Light suffix stemmer. Not Porter; just enough to match claim vocabulary.

    "estimates"/"estimating"/"estimate" -> "estimat";
    "remediation"/"remediating"         -> "remediat";
    "inspection"/"inspects"             -> "inspect".
    """
    w = word.lower()
    for suffix, replacement in _SUFFIXES:
        if w.endswith(suffix) and len(w) - len(suffix) >= 4:
            w = w[: -len(suffix)] + replacement
            break
    if len(w) > 4 and w.endswith("e"):
        w = w[:-1]
    return w


def content_terms(text: str) -> list[str]:
    """Stemmed, de-duplicated content words of `text`, in order."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in re.findall(r"[a-zA-Z][a-zA-Z0-9\-]*", text or ""):
        low = raw.lower()
        if low in STOPWORDS or len(low) < 3:
            continue
        s = stem(low)
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


# --- claim-element decomposition ---------------------------------------------

def split_elements(invention: str) -> list[str]:
    """Break an invention sentence into its claim elements (limitations).

    Splits on the boundaries claim language uses, then drops segments that carry
    no technical content (pure stopwords) or only claim-preamble nouns.
    """
    text = (invention or "").strip().rstrip(".")
    segments = [s.strip(" .,;-") for s in _SPLIT.split(text)]
    elements: list[str] = []
    for seg in segments:
        if not seg:
            continue
        terms = content_terms(seg)
        if not terms:
            continue
        if all(t in PREAMBLE for t in terms):
            continue
        if seg.lower() in {e.lower() for e in elements}:
            continue
        elements.append(seg)
    if not elements and text:
        elements = [text]
    return elements


# --- element vs claim comparison ---------------------------------------------

#: An element counts as disclosed when this fraction of its content terms
#: appear in a single claim of a single reference.
DISCLOSURE_THRESHOLD = 0.6


def score_element(element: str, claim_text: str) -> tuple[float, list[str]]:
    """Containment of `element`'s content terms in `claim_text`. Returns (score, matched)."""
    terms = content_terms(element)
    if not terms:
        return 0.0, []
    claim_terms = set(content_terms(claim_text))
    matched = [t for t in terms if t in claim_terms]
    return len(matched) / len(terms), matched


def _excerpt(claim_text: str, matched: Iterable[str], width: int = 180) -> str:
    """A short window of the claim around the first matched term."""
    matched = list(matched)
    if not matched:
        return claim_text[:width].strip()
    for m in matched:
        hit = re.search(re.escape(m), claim_text, re.IGNORECASE)
        if hit:
            start = max(0, hit.start() - width // 3)
            end = min(len(claim_text), start + width)
            prefix = "..." if start > 0 else ""
            suffix = "..." if end < len(claim_text) else ""
            return f"{prefix}{claim_text[start:end].strip()}{suffix}"
    return claim_text[:width].strip()


def build_matrix(invention: str, references: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The claim-element matrix: one row per element, best match across all claims.

    `references` are dicts with `patent_id`, optional `title`, `url`, and
    `claims` = [{number, text}, ...]. References with no claim text contribute
    nothing, which is the honest outcome: you cannot compare against claims you
    did not retrieve.
    """
    rows: list[dict[str, Any]] = []
    for element in split_elements(invention):
        best: dict[str, Any] | None = None
        for ref in references:
            for claim in ref.get("claims") or []:
                score, matched = score_element(element, claim.get("text", ""))
                if best is None or score > best["score"]:
                    best = {
                        "patent_id": ref.get("patent_id"),
                        "title": ref.get("title"),
                        "url": ref.get("url"),
                        "claim_number": claim.get("number"),
                        "score": round(score, 3),
                        "matched_terms": matched,
                        "excerpt": _excerpt(claim.get("text", ""), matched),
                    }
        if best is None:
            rows.append({"element": element, "terms": content_terms(element),
                         "disclosed": False, "score": 0.0, "best": None})
            continue
        rows.append({
            "element": element,
            "terms": content_terms(element),
            "disclosed": best["score"] >= DISCLOSURE_THRESHOLD,
            "score": best["score"],
            "best": best,
        })
    return rows


# --- verdict -----------------------------------------------------------------

VERDICT_CLEAR = "CLEAR"
VERDICT_NEEDS_REVIEW = "NEEDS_REVIEW"
VERDICT_HIGH_OVERLAP = "HIGH_OVERLAP"
VERDICT_SEARCH_UNAVAILABLE = "SEARCH_UNAVAILABLE"

#: A single reference disclosing this fraction of the elements anticipates.
ANTICIPATION_THRESHOLD = 0.8


def judge(matrix: list[dict[str, Any]]) -> dict[str, Any]:
    """Turn the matrix into a verdict, with the arithmetic that produced it.

    * one reference discloses >= 80% of the elements  -> HIGH_OVERLAP (anticipated)
    * the references jointly disclose >= 40%          -> NEEDS_REVIEW (combination risk)
    * otherwise                                       -> CLEAR
    """
    total = len(matrix)
    if total == 0:
        return {"verdict": VERDICT_NEEDS_REVIEW, "elements": 0, "disclosed": 0,
                "combined_coverage": 0.0, "best_single_coverage": 0.0,
                "closest": None, "rationale": "no claim elements could be extracted"}

    per_ref: dict[str, int] = {}
    disclosed = 0
    for row in matrix:
        if not row["disclosed"]:
            continue
        disclosed += 1
        pid = (row["best"] or {}).get("patent_id") or "?"
        per_ref[pid] = per_ref.get(pid, 0) + 1

    combined = disclosed / total
    closest_id, closest_hits = (max(per_ref.items(), key=lambda kv: kv[1])
                                if per_ref else (None, 0))
    best_single = closest_hits / total

    if best_single >= ANTICIPATION_THRESHOLD:
        verdict = VERDICT_HIGH_OVERLAP
        rationale = (f"{closest_id} alone discloses {closest_hits} of {total} claim elements "
                     f"({best_single:.0%}); a single reference at this coverage anticipates")
    elif combined >= 0.4:
        verdict = VERDICT_NEEDS_REVIEW
        rationale = (f"{disclosed} of {total} claim elements are disclosed across the "
                     f"references ({combined:.0%}); no single reference reaches "
                     f"{ANTICIPATION_THRESHOLD:.0%}, so the combination is the risk")
    else:
        verdict = VERDICT_CLEAR
        rationale = (f"only {disclosed} of {total} claim elements are disclosed "
                     f"({combined:.0%}); the undisclosed elements carry the novelty")

    return {"verdict": verdict, "elements": total, "disclosed": disclosed,
            "combined_coverage": round(combined, 3),
            "best_single_coverage": round(best_single, 3),
            "closest": closest_id, "rationale": rationale}


def render_matrix_text(matrix: list[dict[str, Any]]) -> str:
    """The matrix as plain text for the brief / CLI."""
    if not matrix:
        return "  (no claim elements extracted)"
    lines = []
    for i, row in enumerate(matrix, start=1):
        mark = "DISCLOSED" if row["disclosed"] else "not disclosed"
        best = row["best"]
        head = f"  {i}. [{mark}] {row['element']}"
        if best and best["score"] > 0:
            head += (f"\n       {best['patent_id']} claim {best['claim_number']} "
                     f"({best['score']:.0%} of terms: {', '.join(best['matched_terms']) or 'none'})")
            head += f"\n       \"{best['excerpt']}\""
        else:
            head += "\n       no claim text matched"
        lines.append(head)
    return "\n".join(lines)
