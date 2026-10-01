# AutoComic Translator - Product Architecture

## 1. Overview

**AutoComic Translator** is a system designed to automatically translate webcomic, manga, and manhwa content from Korean, Japanese, and Chinese into English.

The long-term vision is a browser extension that performs translation seamlessly while users read chapters online.

---

## 2. Problem Statement

### Current Challenges

- Official English releases often lag behind native-language releases.
- Community translations can take days or weeks.
- Existing OCR tools require manual screenshotting and copying text.
- Translation workflows interrupt reading flow.

### User Need

Read raw comic chapters immediately in understandable English without manually extracting or translating text.

---

## 3. Product Vision

### Final Product

A browser extension that:

- Detects comic images automatically
- Extracts text using OCR
- Translates text into English
- Displays translated text directly on the page
- Operates in near real-time while scrolling

Target latency:

- 1–3 seconds per panel

---

## 4. Proof of Concept (MVP)

Before building the extension, a lightweight prototype will validate OCR and translation quality.

### PoC Workflow

```text
User Uploads JPG/PNG
            ↓
       OCR Engine
            ↓
      Extracted Text
            ↓
   Translation Engine
            ↓
   English Translation
            ↓
Display Results Below Image
```

### PoC Interface Options

#### Option A — CLI

```bash
python translate.py panel.jpg
```

Output:

```text
Original:
"안녕하세요"

Translated:
"Hello"
```

#### Option B — Web UI

```text
Upload Image
      ↓
OCR
      ↓
Translation
      ↓
Show translated text beneath image
```

The PoC focuses only on translation accuracy and speed.

No browser automation is included at this stage.

---

## 5. Core Features

### OCR

- Korean support
- Japanese support
- Chinese support
- Stylized comic text detection

### Translation

- Local translation models
- Optional API-based translation
- Multi-language support

### Performance

- Fast inference
- Local caching
- Progressive processing

---

## 6. System Architecture

### PoC Architecture

```text
Frontend (CLI / Web UI)
            ↓
      Image Upload
            ↓
       OCR Engine
      (EasyOCR /
      PaddleOCR)
            ↓
      Text Output
            ↓
 Translation Engine
            ↓
 English Output
            ↓
      User Display
```

### Final Browser Extension Architecture

```text
Browser Extension
        ↓
DOM Scanner
        ↓
Image Detection
        ↓
OCR Pipeline
        ↓
Translation Engine
        ↓
Rendering Engine
        ↓
Overlay / Replacement
```

---

## 7. Technical Stack

| Layer | Technology |
|---------|-----------|
| Frontend (PoC) | Streamlit / Gradio |
| Browser Extension | JavaScript / React |
| Backend | Python FastAPI |
| OCR | PaddleOCR / EasyOCR |
| Translation | NLLB / MarianMT / APIs |
| Image Processing | OpenCV, Pillow |
| Cache | IndexedDB / SQLite |

---

## 8. Translation Strategy

### Local-First

Default mode uses locally hosted translation models.

Examples:

- NLLB-200
- MarianMT
- M2M100

Advantages:

- Free
- No API cost
- Offline capable
- Better privacy

Disadvantages:

- Larger model downloads
- Slower on low-end devices

### API Mode

Optional support for:

- DeepL
- Google Translate
- OpenAI

Users provide their own API keys.

No developer-side API expenses.

---

## 9. Cost Model

### Developer Cost

Target:

```text
$0/month
```

Using:

- Local OCR
- Local translation models
- Client-side processing

### User Cost

Default:

- Free

Optional:

- User-provided API keys

---

## 10. Development Roadmap

### Phase 1 — Translation PoC

- Image upload
- OCR extraction
- Translation
- Text display

### Phase 2 — Smart Comic Processing

- Speech bubble detection
- Better OCR preprocessing
- Multi-panel support
- Translation caching

### Phase 3 — Browser Extension

- DOM image detection
- Automatic processing
- Overlay rendering
- Lazy per-image translation queue and reading-order translation feed (chapter-level state is planned for Phase 4)

### Phase 4 — Advanced Reading Quality (planned)

- Smart typesetting: adaptive font size, wrapping, alignment, and bounds handling
- Speech-bubble / text-area detection to recover the usable area around a region
- Panel detection and reading-order reconstruction, language-aware
- Chapter/session state layered over the existing local cache
- Advanced performance work, benchmarked before adoption
- Context-aware local translation using limited nearby dialogue
- Native-looking rendering that masks source text in simple cases

### Phase 5 — Productization and General Release (planned)

- Production packaging and backend lifecycle management
- Model manager with explicit, user-triggered local model installation
- First-run setup with no developer terminal
- Production extension UX and browser distribution
- Versioned updates, security/privacy audit, compatibility testing, release docs

Milestone detail, completion definitions, and transition rules live in
[`ROADMAP.md`](ROADMAP.md). Phase 4 and Phase 5 are planned only; no
implementation method is fixed by this document.

---

## 11. Future Architecture Direction

The Phase 3 architecture is the current, implemented shape. Phase 4 and Phase 5
change how much the system understands and how it is delivered, not what the
local-first constraint allows. The conceptual evolution is:

```text
Phase 3 (implemented)

Browser page
  → discovery
  → local API
  → OCR
  → translation
  → overlay / feed


Phase 4 (planned)

Browser page
  → chapter/session model
  → image / layout analysis
  → OCR
  → reading-order reconstruction
  → context-aware translation
  → smart typesetting / source-text cleanup


Phase 5 (planned)

Installed application
  ├── backend lifecycle manager
  ├── local models (managed installation)
  ├── cache
  └── browser extension
```

No technology choices are locked in here. The packaging mechanism, the
background/companion process shape, and any runtime or quantization change are
Phase 4/5 decisions that must be evaluated and benchmarked first; milestone
detail is in [`ROADMAP.md`](ROADMAP.md).

---

## 12. Risks & Limitations

- Stylized fonts may reduce OCR accuracy.
- OCR errors propagate into translations.
- Layout reconstruction is difficult.
- Translation quality varies by language.
- Browser extension compatibility issues.
- Legal considerations regarding copyrighted content.

---

## 13. Security & Privacy

- Local processing by default.
- No server-side storage.
- No image uploads required.
- Optional provider API keys, if any are ever added, stay local and are never
  required.
- Cached data remains on user device.