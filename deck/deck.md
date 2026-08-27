---
marp: true
theme: default
paginate: true
backgroundColor: #0E1C2B
color: #E8F0F6
style: |
  section {
    font-family: -apple-system, system-ui, sans-serif;
    background: #0E1C2B; color: #E8F0F6;
    padding: 60px 72px; font-size: 25px; line-height: 1.55;
    justify-content: flex-start;
  }
  h1 { color: #E8F0F6; font-size: 52px; letter-spacing: -0.02em; margin: 0 0 .3em; }
  h2 { color: #5FB0D9; font-size: 36px; letter-spacing: -0.01em;
       margin: 0 0 .5em; padding-bottom: .2em; border-bottom: 1px solid #1e3a55; }
  h3 { color: #cfe0ec; font-size: 27px; font-weight: 600; margin: 0 0 .4em; }
  p, li { font-size: 25px; }
  ul, ol { line-height: 1.6; margin-top: .2em; }
  strong { color: #5FB0D9; }
  em { color: #3FBF7F; font-style: normal; }
  code { background: #0a141e; color: #5FB0D9; padding: 2px 7px; border-radius: 5px; font-size: .9em; }
  a { color: #5FB0D9; }
  .muted { color: #8AA3B5; }
  .red { color: #E5595B; }
  .amber { color: #E0A63C; }
  .green { color: #3FBF7F; }
  section::after { color: #4a6272; font-size: 16px; }
  section.lead { text-align: center; align-items: center; justify-content: center; }
  section.lead h1 { font-size: 82px; }
  section.lead h3 { color: #cfe0ec; font-weight: 500; }
---

<!-- _class: lead -->
# PatentPincer

### Describe an invention. Get a cited patentability verdict in a minute.

<span class="muted">doom2quake · DevNetwork [API + Cloud + AI] 2026 · SerpApi</span>

---

## The problem

A prior-art search is the **first** thing a founder needs and the **last** thing
they can afford.

An attorney charges four figures and takes a week to say whether your idea is
already patented.

Most founders skip it and find out the expensive way, **after** they have built.

---

## The idea

Describe the invention in one sentence:

```bash
patentpincer assess "a wearable that estimates
  hydration from sweat conductivity"
```

Get back a decision: **file it, narrow it, or walk away**, with the closest
reference and why.

---

## How it works

Four steps, the way an attorney actually works:

1. **Search prior art.** SerpApi Google Patents (widened recall) + Scholar for
   non-patent literature.
2. **Fetch the claims.** SerpApi Patents *Details* returns the numbered claims.
   A snippet is not a claim.
3. **Compare element by element.** Every cell names the reference, the claim
   number, the matched terms and the excerpt.
4. **Render a verdict.** One line the router can act on.

<span class="muted">SerpApi is the evidence. The agent is the analyst.</span>

---

## The demo

1. Filing text in → SerpApi surfaces prior art with **overlap bars**.
2. The analyst compares your claim against numbered claims, element by element.
3. A verdict stamp lands:
   <span class="green">CLEAR</span> ·
   <span class="amber">NEEDS_REVIEW</span> ·
   <span class="red">HIGH_OVERLAP</span> ·
   <span class="red">SEARCH_UNAVAILABLE</span> → routed (loud alert on a likely
   collision *or* on a failed search).

---

## It refuses rather than guesses

| What happened | What you get |
| --- | --- |
| No search succeeded | `SEARCH_UNAVAILABLE` + alert |
| Zero references returned | `NEEDS_REVIEW` |
| No claim text retrieved | `SEARCH_UNAVAILABLE` |
| Offline corpus, not live SerpApi | a computed `CLEAR` is downgraded |

<span class="muted">A search that did not happen is never a clearance.</span>

---

## Proven

**38** tests (`pytest`), no network, no API key:

- Offline records are labelled `fixture`, never `ok`; unknown queries are refused.
- Dry-run, timeout, error body, zero results and missing claims **fail closed**.
- A `CLEAR` brief containing "high overlap" still routes as a clearance.
- Concurrent runs keep separate ledgers and **spend budgets**.
- The MCP server boots for real and serves the three SerpApi tools.
- The shipped UI replays runs that reproduce exactly.

<span class="muted">No funded key on this build: recorded runs are FIXTURE and the
demo says so. The live path is covered with faked SerpApi responses.</span>

---

<!-- _class: lead -->
## PatentPincer

<span class="muted">github.com/doom2quake/patentpincer</span>
