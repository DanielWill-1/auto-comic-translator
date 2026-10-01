# Auto Comic Translator — Phase 4 + Phase 5 Planning

We are doing a DOCUMENTATION-ONLY planning pass.

# IMPORTANT: DO NOT IMPLEMENT PHASE 4

Do NOT write Phase 4 production code.

Do NOT create Phase 4 modules.

Do NOT modify backend or extension behavior.

Do NOT add dependencies.

Do NOT change APIs.

Do NOT run model experiments.

Do NOT implement speech-bubble detection.

Do NOT implement new OCR logic.

Do NOT implement inpainting.

Do NOT implement new translation models.

Do NOT begin Phase 5 implementation.

The task is ONLY to update project documentation so the future development direction is clearly defined.

---

# CURRENT PROJECT STRUCTURE

The project currently progresses roughly as:

```text
Phase 1
Core OCR + translation prototype

Phase 2
Comic processing / pipeline

Phase 2.5
Backend hardening

Phase 3
Chromium extension

3.1 Extension shell + backend connection
3.2 Comic image discovery
3.3 First image → backend integration
3.4 Lazy translation queue
3.5 Overlay renderer
3.6 Translation feed
3.7 Reliability / performance / browser polish
```

Phase 3 should remain focused on delivering a stable extension MVP.

Phase 4 should represent:

```text
ADVANCED READING QUALITY
```

Phase 5 should represent:

```text
PRODUCT COMPLETE / READY FOR GENERAL USERS
```

---

# PRIMARY GOAL

Update the documentation so the project has a clear roadmap through:

```text
Phase 3 → stable extension MVP

Phase 4 → advanced manga/manhwa reading quality

Phase 5 → finished distributable product that normal users can install and use
```

Do not implement any of these future milestones.

---

# FILES TO REVIEW

Inspect the repository first.

At minimum review:

```text
README.md
docs/ROADMAP.md
docs/HANDOFF.md
docs/technical_document.md
docs/architecture.md
docs/API.md
docs/PERFORMANCE.md
dev/test-site/README.md
```

Use the actual existing filenames/casing.

Do not create duplicate documentation if an appropriate document already exists.

Only modify documents that genuinely need Phase 4 / Phase 5 planning information.

---

# PART A — DEFINE PHASE 4

Add a clearly documented:

# Phase 4 — Advanced Reading Quality

The purpose of Phase 4 is NOT simply "add more features."

Its purpose is to improve:

```text
how well translated comics are understood
how naturally translations are placed
how smoothly chapters are processed
how close the result feels to a proper translated manga/manhwa reader
```

Phase 4 should build on the stable Phase 3 pipeline:

```text
discover image
→ lazy queue
→ OCR
→ translate
→ result
→ overlay
→ feed
```

and improve the QUALITY of that experience.

---

# PHASE 4 MILESTONES

Document the following milestones.

Do not implement them.

---

# 4.1 — Smart Typesetting

Goal:

Improve the current basic translated-text overlay so English text is placed more naturally and readably.

Current Phase 3 concept:

```text
OCR bbox
→ translated text box
```

Phase 4.1 should evolve toward:

```text
OCR region
→ available text area
→ appropriate font size
→ wrapping
→ alignment
→ collision/bounds handling
→ readable translation
```

Potential future work:

- adaptive font sizing;
- line wrapping;
- text centering;
- vertical alignment;
- padding;
- minimum/maximum font sizes;
- expansion when English is longer than source text;
- keeping translated text inside the image;
- avoiding region overlap;
- handling narrow bubbles;
- handling long translations;
- better contrast/readability;
- configurable overlay styling.

Explicitly note:

Phase 4.1 is still DOM/browser rendering.

It should NOT require image inpainting yet.

---

# 4.2 — Speech Bubble / Text Area Detection

Goal:

Move beyond using only OCR text bounding boxes.

Desired future pipeline:

```text
OCR region
    ↓
identify surrounding speech bubble / text area
    ↓
use larger available area
    ↓
typeset translation inside that area
```

Potential techniques to investigate:

```text
thresholding
contour detection
connected components
white-region detection
shape analysis
classical OpenCV/Pillow processing
```

Machine-learning-based detection may be evaluated later if classical methods are insufficient.

Do not mandate a heavyweight ML detector at this planning stage.

Document that this milestone should first attempt the simplest reliable approach.

Expected benefit:

English translations often require more space than Japanese/Korean/Chinese source text.

Bubble-aware rendering gives the renderer more usable area.

---

# 4.3 — Panel Detection and Reading-Order Reconstruction

Goal:

Improve how text regions are organized and understood on full comic pages.

Future processing hierarchy may become:

```text
page
→ panels
→ speech bubbles / text areas
→ OCR regions
→ reading order
```

Document possible language/layout considerations.

For Japanese manga:

```text
right → left
top → bottom
```

may matter.

For webtoon/manhwa layouts:

```text
primarily vertical progression
```

may dominate.

Potential future work:

- panel detection;
- bubble grouping;
- text-region grouping;
- reading-order heuristics;
- layout graphs;
- language-aware ordering;
- using reconstructed order in both overlay and translation feed.

Do NOT define a complex algorithm as final yet.

This milestone is exploratory until tested against real pages.

---

# 4.4 — Chapter / Session Architecture

Goal:

Move from isolated image processing toward chapter-level state.

Current architecture is mostly:

```text
image
→ translation
```

Future architecture should understand:

```text
chapter/session

├── image 1
├── image 2
├── image 3
├── ...
└── image N
```

Document potential chapter-level state such as:

- ordered images;
- processed/unprocessed state;
- translation results;
- source/target languages;
- image hashes;
- cache identities;
- progress;
- failures;
- session lifecycle;
- revisit/reload behavior.

Benefits:

```text
better chapter navigation
better progress persistence
less repeated work
better cache reuse
better context handling
cleaner large-chapter behavior
```

This milestone should build on, not replace, the existing backend SQLite cache and extension session state.

---

# 4.5 — Advanced Performance Optimization

Phase 3.7 should remove obvious inefficiencies.

Phase 4.5 should address deeper inference/runtime optimization.

Document investigation areas such as:

```text
OCR preprocessing optimization
batch translation
translation batching across OCR regions
persistent warm models
CPU/GPU execution options
model quantization
ONNX/runtime optimization
parallel preprocessing
more efficient Auto language mode
image preprocessing reuse
chapter-level scheduling
```

Important:

Do not commit the project to ONNX, quantization, GPU inference, or another runtime yet.

These are evaluation areas.

Any optimization must be benchmarked before adoption.

Performance documentation should continue comparing:

```text
cold request
warm request
cache hit
Auto
explicit language
```

Preserve the project's local-first nature.

---

# 4.6 — Context-Aware Local Translation

Goal:

Improve dialogue translation quality using limited nearby context.

Current translation is largely region/group based.

Future experiments may consider:

```text
previous bubble
current bubble
next bubble
```

or:

```text
previous N regions
→ current translation
```

Potential improvements:

- pronoun resolution;
- fragmented dialogue;
- names;
- repeated terms;
- honorifics;
- punctuation;
- slang;
- sentence continuation across bubbles;
- consistent character terminology.

Important constraints:

```text
local-first
no mandatory cloud API
no project-owned paid API
```

Do not promise specific model changes yet.

Potential local approaches may be investigated in Phase 4.6.

This milestone is about translation QUALITY and context, not about rewriting the rest of the pipeline.

---

# 4.7 — Native-Looking Comic Rendering / Text Cleanup

Goal:

Move beyond simply drawing English on top of source text.

Future pipeline could become:

```text
detect text/bubble
↓
remove or mask original text
↓
reconstruct background
↓
render translated text
```

Start with simple cases.

Example:

```text
plain white speech bubble
→ clear source text area
→ draw English cleanly
```

Only later investigate complex backgrounds.

Possible future techniques:

```text
solid-color cleanup
local background estimation
classical inpainting
optional ML-based inpainting
```

Do NOT make generative/AI inpainting a requirement.

Do NOT implement any of it now.

Document it as the final major Phase 4 visual-quality milestone.

---

# PART B — PHASE 4 ORDER

Document the intended dependency/order clearly:

```text
4.1 Smart Typesetting
        ↓
4.2 Bubble / Text Area Detection
        ↓
4.3 Panel + Reading Order
        ↓
4.4 Chapter / Session Architecture
        ↓
4.5 Advanced Performance
        ↓
4.6 Context-Aware Translation
        ↓
4.7 Native-Looking Rendering
```

However, explain that:

```text
4.4 / 4.5
```

may partially overlap earlier milestones if required by real performance findings.

Do not imply every milestone is completely independent.

---

# PART C — DEFINE WHAT "PHASE 4 COMPLETE" MEANS

Add a concrete Phase 4 completion definition.

Phase 4 should be considered complete when the extension can reliably provide an advanced reading experience where:

```text
comic images are detected
↓
translations occur progressively
↓
text regions are grouped/order-aware
↓
translations use useful surrounding layout
↓
English is typeset intelligently
↓
chapter state is preserved/reused
↓
performance is acceptable on realistic chapters
↓
local translation can use limited dialogue context
↓
source text can be cleanly replaced or visually suppressed in supported cases
```

This does NOT mean the product is ready for arbitrary users yet.

That is Phase 5.

---

# PART D — DEFINE PHASE 5

Add:

# Phase 5 — Productization and General Release

Phase 5 means:

```text
THE PRODUCT IS FUNCTIONALLY DONE
AND A NORMAL USER CAN INSTALL AND USE IT
```

This phase is not primarily about adding new research features.

It is about taking the mature Phase 4 system and making it safe, installable, understandable, maintainable, and releasable.

---

# PHASE 5 OBJECTIVE

By the end of Phase 5, a non-developer should NOT need to:

```text
clone the Git repository
install Python manually
run uvicorn manually
run python -m http.server
edit source files
know where Paddle models live
use DevTools
understand OCR model internals
```

The product should behave like a real application.

---

# PROPOSED PHASE 5 MILESTONES

Document a future structure roughly like this.

Do NOT implement it now.

---

# 5.1 — Production Packaging

Goal:

Package the local backend and required runtime cleanly.

Investigate later:

```text
Windows installer
self-contained Python runtime or packaged executable
backend executable
dependency packaging
versioned application directory
uninstall support
```

Normal users should not manually configure Python environments.

---

# 5.2 — Backend Lifecycle Management

The user should not manually run:

```powershell
python.exe -m uvicorn backend.main:app
```

Future product behavior should manage:

```text
start backend
stop backend
restart backend
detect crash
check health
```

Potential architecture:

```text
desktop/background companion app
        ↓
local backend
        ↓
browser extension
```

Do not choose the final packaging architecture yet.

Document it as an implementation decision for Phase 5.

---

# 5.3 — Model Setup / Model Manager

Users need a safe way to obtain required local OCR/translation models.

Future UI should explain:

```text
Japanese installed
Chinese installed
Korean missing
Traditional Chinese missing
```

and allow explicit user-triggered setup.

Important:

Runtime translation requests must still NOT silently download models.

Instead:

```text
user explicitly selects Install Korean support
        ↓
download/install assets
        ↓
validate files
        ↓
mark Korean ready
```

Possible future capabilities:

- model inventory;
- disk-space estimate;
- download progress;
- checksum/integrity verification;
- repair/reinstall;
- remove unused models.

---

# 5.4 — First-Run Setup

Design a future first-run experience.

Example:

```text
Welcome
↓
Choose languages
↓
Install local models
↓
Verify backend
↓
Install/connect browser extension
↓
Test translation
↓
Ready
```

No developer terminal required.

---

# 5.5 — Production Extension UX

Phase 3 extension UI is development/MVP quality.

Phase 5 should finalize:

- popup;
- settings;
- errors;
- accessibility;
- status;
- onboarding;
- feed;
- overlays;
- language controls;
- model-readiness information.

Remove or hide development/debug UI from normal users.

Keep optional developer diagnostics behind a deliberate debug mode if useful.

---

# 5.6 — Browser Distribution

Prepare extension for normal installation/distribution.

Potential future targets:

```text
Chrome Web Store
Chromium-compatible browsers
manual signed/unpacked fallback for development
```

Review:

- Manifest permissions;
- CSP;
- packaging;
- icons/assets;
- privacy disclosure;
- versioning;
- extension update strategy.

---

# 5.7 — Installer / Application Updates

Define product update behavior.

Consider:

```text
backend version
extension version
model version
cache schema version
```

Plan compatibility rules.

Avoid updates silently corrupting caches or mismatching API contracts.

---

# 5.8 — Security / Privacy Release Audit

Before general release perform a formal audit of:

```text
loopback backend exposure
CORS
request limits
extension permissions
model downloads
cache contents
logs
API keys if optional providers ever exist
dependency vulnerabilities
filesystem permissions
update integrity
```

The product should remain local-first by default.

---

# 5.9 — Compatibility Testing

Test on realistic sites and environments.

Possible matrix:

```text
Windows 10
Windows 11

Chrome
Edge
other Chromium browsers where feasible

Japanese manga
Chinese manhua
Korean manhwa
webtoon long-strip layouts
traditional page layouts
dynamic readers
lazy-loaded sites
```

Do not claim support before testing.

---

# 5.10 — Release Documentation

Before Phase 5 completion provide:

```text
installation guide
first-run guide
troubleshooting
model storage information
privacy explanation
supported languages
known limitations
performance expectations
uninstall instructions
developer documentation
```

---

# PART E — DEFINE WHAT "PHASE 5 COMPLETE" MEANS

This definition is important.

Document clearly that Phase 5 completion means:

```text
A NORMAL USER CAN USE AUTO COMIC TRANSLATOR
WITHOUT DEVELOPMENT KNOWLEDGE.
```

Success criteria should include:

```text
download/install application
↓
guided model setup
↓
install extension
↓
backend starts automatically
↓
open comic page
↓
extension detects comic
↓
translation works
↓
overlay/feed works
↓
cache works
↓
clear errors when something is unavailable
↓
application can be updated/uninstalled normally
```

No terminal required for ordinary operation.

No manually running Python commands.

No manually locating model directories.

No repository checkout required.

---

# PART F — PROJECT ROADMAP STRUCTURE

Update `docs/ROADMAP.md` so the high-level project now reads approximately:

```text
Phase 1 — Core OCR + Translation
[x]

Phase 2 — Comic Processing
[x]

Phase 2.5 — Backend Hardening
[x]

Phase 3 — Chromium Extension
3.1 ...
3.2 ...
...
3.7 ...

Phase 4 — Advanced Reading Quality
4.1 Smart Typesetting
4.2 Speech Bubble / Text Area Detection
4.3 Panel + Reading Order Reconstruction
4.4 Chapter / Session Architecture
4.5 Advanced Performance Optimization
4.6 Context-Aware Local Translation
4.7 Native-Looking Rendering

Phase 5 — Productization and General Release
5.1 Production Packaging
5.2 Backend Lifecycle
5.3 Model Manager
5.4 First-Run Setup
5.5 Production Extension UX
5.6 Browser Distribution
5.7 Updates
5.8 Security / Privacy Audit
5.9 Compatibility Testing
5.10 Release Documentation
```

All future milestones must remain:

```text
[ ] planned
```

Do NOT mark Phase 4 or Phase 5 in progress.

---

# PART G — README UPDATE

Update README so someone arriving at the repository can understand the project trajectory.

Keep it concise.

README should explain:

```text
Phase 3
builds the functional browser-extension MVP

Phase 4
focuses on advanced reading quality

Phase 5
turns the mature project into a distributable product for normal users
```

Do not dump the entire detailed roadmap into README.

Link to:

```text
docs/ROADMAP.md
```

for milestone details.

---

# PART H — TECHNICAL DOCUMENT UPDATE

Update the technical document's roadmap section.

Its old Phase 4 description is too broad.

Replace/expand it so it matches the detailed Phase 4 plan.

Add Phase 5 as the final productization phase.

Keep architecture discussions separate from speculative implementation details.

Do not write future choices as if they have already been implemented.

Use language such as:

```text
planned
candidate
may
evaluate
investigate
```

where the implementation method is not settled.

---

# PART I — HANDOFF UPDATE

Update:

```text
docs/HANDOFF.md
```

with the new high-level future roadmap.

Do not turn the handoff into a giant roadmap duplicate.

Include a short section like:

```text
Future phases

Phase 4:
Advanced reading quality.

Phase 5:
Production packaging and general-user release.
```

Then link to `ROADMAP.md`.

---

# PART J — ARCHITECTURE DOCUMENT

Review:

```text
docs/architecture.md
```

If it currently presents the Phase 3 architecture as the final architecture, add a short "future architecture direction" section.

Possible conceptual evolution:

```text
Phase 3

Browser page
→ discovery
→ local API
→ OCR
→ translation
→ overlay/feed


Phase 4

Browser page
→ chapter/session model
→ image/layout analysis
→ OCR
→ reading-order reconstruction
→ context-aware translation
→ smart typesetting / cleanup


Phase 5

Installed application
├── backend lifecycle manager
├── local models
├── cache
└── browser extension
```

Do not lock in technologies that have not been selected.

---

# PART K — KEEP SCOPE REALISTIC

Explicitly document what Phase 4 is NOT.

Phase 4 is not:

```text
cloud hosting
comic distribution
content hosting
account system
social platform
DRM bypass
automated scraping service
commercial translation API dependency
```

The project remains a user-side comic translation tool.

---

# PART L — LOCAL-FIRST PRINCIPLE

Preserve the existing project principle:

```text
local OCR
local translation
local cache
local image processing
```

No paid/cloud provider should become mandatory in Phase 4 or Phase 5.

Optional external providers may remain a possible future extension only if explicitly configured by a user.

They are NOT part of the Phase 4 core plan.

---

# PART M — PHASE TRANSITION RULES

Document the intended gates.

## Phase 3 → Phase 4

Do not begin Phase 4 implementation until:

```text
3.7 reliability work finished
overlay ownership stable
lazy queue stable
feed stable
real Chromium verification complete
major Phase 3 regression tests passing
```

## Phase 4 → Phase 5

Do not begin product packaging until the advanced reader itself is stable.

Phase 4 completion should establish the product's feature/reading-quality foundation.

Phase 5 should then package and release it.

---

# PART N — NO IMPLEMENTATION IN THIS TASK

This is critical.

After documentation edits:

STOP.

Do NOT implement:

```text
4.1
4.2
4.3
4.4
4.5
4.6
4.7
5.x
```

Do not create placeholders/modules just because they appear in the roadmap.

Do not add TODO source files.

Do not add dependencies.

Do not add tests for nonexistent Phase 4 behavior.

This is a planning-only task.

---

# PART O — DOCUMENT QUALITY

Ensure milestone descriptions answer:

```text
What problem does this milestone solve?

What broad capabilities are planned?

What explicitly remains out of scope?

What milestone should follow it?
```

Avoid vague descriptions such as:

```text
Improve AI
Make translation better
Optimize everything
```

Use concrete technical goals without prematurely fixing implementation choices.

---

# PART P — CONSISTENCY CHECK

After editing documentation, search the repository documentation for old roadmap descriptions that contradict the new plan.

Examples:

```text
"Phase 4 is final"
"Phase 4 is deployment"
"Phase 4 optional APIs"
"Phase 5 ..."
```

Reconcile documentation where needed.

Do not alter historical test records.

Do not rewrite completed Phase 1–3 milestone history unnecessarily.

---

# PART Q — FINAL VALIDATION

Because this is documentation only:

Do NOT run expensive inference.

Do NOT start backend.

Do NOT load OCR models.

Run lightweight checks only.

At minimum:

```powershell
git diff --check
```

If the repository has a markdown link checker or documentation checker already available, run it.

Do not add a new documentation tool dependency solely for this task.

---

# EXPECTED FINAL REPORT

When done, report:

## 1. Documentation inspected

List the relevant files reviewed.

## 2. Phase 4 plan

Summarize the final documented milestones:

```text
4.1 Smart Typesetting
4.2 Bubble/Text Area Detection
4.3 Panel + Reading Order
4.4 Chapter/Session Architecture
4.5 Advanced Performance
4.6 Context-Aware Translation
4.7 Native-Looking Rendering
```

## 3. Phase 5 plan

Summarize the final productization milestones.

## 4. Files changed

List each changed documentation file and why.

## 5. Consistency changes

Mention any old wording corrected to match the new roadmap.

## 6. Validation

Report:

```text
git diff --check
```

and any existing documentation checks actually run.

## 7. Confirm no code changes

Explicitly confirm:

```text
No Phase 4 implementation was started.
No Phase 5 implementation was started.
No runtime/dependency/backend/extension behavior was changed.
```

## 8. Final roadmap

End with:

```text
Phase 3 — Functional extension MVP
Phase 4 — Advanced Reading Quality
Phase 5 — Productization and General Release
```

with Phase 4 and Phase 5 remaining planned only.

---

# FINAL PRODUCT VISION

The roadmap should communicate this clearly:

```text
PHASE 3
"It works as a browser extension."

        ↓

PHASE 4
"It reads and looks like a genuinely good comic translation experience."

        ↓

PHASE 5
"Anyone can install it and use it without being a developer."
```

Do not implement any future phase during this task.