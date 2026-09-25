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
- Chapter-wide translation

### Phase 4 — Advanced Features

- AI typesetting
- Community cache
- Improved layout reconstruction
- Faster inference

---

## 11. Risks & Limitations

- Stylized fonts may reduce OCR accuracy.
- OCR errors propagate into translations.
- Layout reconstruction is difficult.
- Translation quality varies by language.
- Browser extension compatibility issues.
- Legal considerations regarding copyrighted content.

---

## 12. Security & Privacy

- Local processing by default.
- No server-side storage.
- No image uploads required.
- User API keys stored locally.
- Cached data remains on user device.