# PatentPincer demo video script (target 2:00, hard cap 3:00)

Record `ui/index.html` (self-contained, runs offline). Human voice, calm. Screen directions in
[brackets]. The offline corpus is deterministic, so you can read the numbers aloud.

---

**[0:00 - 0:14]  Hook**
[Screen: ui/index.html open, the invention box and presets visible.]

"A prior-art search is the first thing a founder needs and the last thing they can afford. A patent
attorney charges four figures and takes a week to tell you whether your idea is already patented. Most
people skip it, and find out the expensive way, after they have built."

**[0:14 - 0:26]  What it is**
[Screen: point at the input.]

"So we built PatentPincer. You describe your invention in one sentence, and it does that first prior-art
pass in about a minute."

**[0:26 - 0:48]  Run it**
[Screen: pick a preset or type "a wearable that estimates hydration from sweat conductivity", click "Assess patentability".]

"I describe a wearable that estimates hydration from sweat conductivity, and click assess. PatentPincer
searches Google Patents through SerpApi, with a few phrasings to widen recall, and adds a Scholar query
for non-patent literature."

**[0:48 - 1:12]  The analysis (the hero)**
[Screen: the element-by-element comparison fills in.]

"Here is the part that matters. It does not just list similar patents. It pulls the actual claim text of
the closest references and compares your invention element by element. Optical heart-rate sensor, worn
on the wrist, both already disclosed. Hydration from sweat conductivity, not found in the prior art. So
it can tell you exactly which parts are novel and which are not."

**[1:12 - 1:32]  The verdict**
[Screen: the verdict and citations appear.]

"Then it hands back a decision-ready verdict, file it, narrow it, or walk away, with citations you can
open and read yourself. Every claim it makes is backed by a source; it never just asserts."

**[1:32 - 2:00]  Why it holds up**
[Screen: point at the sources; mention the repo.]

"SerpApi's Google Patents and Scholar engines are the load-bearing backbone; the agent layer is the
analyst on top, behind a spend guardrail so a search can never run away. It runs offline on a fixture
corpus with no key, so anyone can try it, and it is covered by a real test suite. PatentPincer turns a
week and four figures into a minute. Thanks for watching."

---

Recording tips: open ui/index.html directly; use a preset for a clean run. Take your time on the
element-by-element comparison, that is the strongest beat. Keep it under three minutes.
