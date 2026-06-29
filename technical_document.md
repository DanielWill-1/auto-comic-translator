# Auto Comic Translator - Technical Document

## 1. Project Overview

Auto Comic Translator is a browser-extension-based system for translating webcomic, manga, and manhwa pages into English while users read online. The system detects comic images on a web page, extracts text through OCR, translates that text, and renders the English result back over the original comic panels.

The project is designed around a local-first model. By default, OCR, translation, image processing, and caching should run on the user's machine so the tool can remain free to use and avoid sending comic images to external services. Optional API integrations can be added for users who want higher translation quality and are willing to provide their own API keys.

## 2. Goals

The primary goal is to let users read raw chapters from official sources without waiting for translated releases. The extension should preserve the reading flow by translating content automatically as the user scrolls.

Core goals:

- Detect comic images automatically from web pages.
- Extract Korean, Japanese, and Chinese text from panels.
- Translate extracted text into English.
- Render translated text directly on top of the comic image or panel area.
- Cache repeated translations to improve speed.
- Support fully free local processing by default.
- Allow optional external translation APIs for improved output quality.

Target performance for the final product is near real-time translation, ideally around 1 to 3 seconds per panel depending on the user's hardware and selected OCR/translation model.

## 3. System Architecture

Auto Comic Translator is split into two major parts: a browser extension and a local processing backend.

The browser extension is responsible for page integration. It scans the DOM, detects likely comic images, sends image data to the local backend, and displays the translated result back in the browser. The backend performs the heavier work: OCR, translation, image processing, caching, and optional text rendering.

High-level flow:

```text
Web Page
  ->
Browser Extension
  ->
Image Detection
  ->
Local Backend API
  ->
OCR Engine
  ->
Translation Engine
  ->
Rendering / Overlay Engine
  ->
Translated Comic View
```

The repository can expose multiple backend entrypoints. The full production-oriented backend should be handled by `backend/main.py`, while `api.py` can provide a lightweight local testing wrapper and `api_refined.py` can provide a more advanced ASGI-compatible API with caching, batching, and optional API key support.

## 4. Browser Extension Design

The extension runs inside Chrome and monitors web pages for comic content. It should avoid processing every image on the page blindly. Instead, it should use basic heuristics to identify likely comic panels or long-strip images.

Possible detection signals:

- Large image dimensions.
- Vertical aspect ratio typical of manhwa chapters.
- Image location inside reader containers.
- Lazy-loaded image attributes such as `data-src`.
- Repeated image patterns on chapter pages.
- User-triggered scan from the extension popup.

Once an image is detected, the extension sends it to the local backend. The response can contain translated text blocks, bounding boxes, or a fully rendered translated image. For flexibility, the extension should support overlay rendering in the browser as the preferred approach, while image replacement can remain an optional mode.

Extension responsibilities:

- DOM scanning and image discovery.
- Local backend health checks.
- Sending image URLs or image blobs for processing.
- Drawing translation overlays.
- Managing user settings.
- Storing lightweight cache metadata in IndexedDB.

## 5. Backend Pipeline

The backend is a Python FastAPI service that receives image processing requests from the extension. It coordinates OCR, translation, rendering, and caching.

Pipeline steps:

1. Receive image input from the extension.
2. Normalize the image using Pillow or OpenCV.
3. Run OCR using PaddleOCR or EasyOCR.
4. Group detected text into readable blocks.
5. Detect source language when needed.
6. Translate text into English.
7. Return translated text and layout data.
8. Optionally render translated text onto the image.
9. Store results in cache for repeated reads.

The backend should expose simple endpoints for health checks, single-image processing, batch processing, and settings validation. The refined API can add support for request hashing, cache hits, and API-backed translation providers.

Example endpoint structure:

```text
GET  /health
POST /translate-image
POST /translate-batch
GET  /cache/status
POST /settings/validate
```

## 6. OCR Strategy

OCR quality is one of the most important technical risks. Comic text is often stylized, vertical, curved, outlined, or placed on noisy backgrounds. The first implementation should use reliable OCR libraries and improve input preprocessing before attempting custom OCR logic.

Recommended OCR options:

- PaddleOCR for strong multilingual OCR support.
- EasyOCR for easier setup and broad language coverage.

Supported source languages should initially focus on:

- Korean to English.
- Japanese to English.
- Chinese to English.

Preprocessing may include grayscale conversion, contrast enhancement, denoising, thresholding, panel cropping, and optional speech bubble detection. OCR results should include text, confidence scores, and bounding boxes so the rendering layer can place translations near the original text.

## 7. Translation Strategy

The default translation mode should be local-first. This keeps the project free, private, and usable without developer-side API costs.

Local model candidates:

- MarianMT for lightweight language-pair translation.
- NLLB-200 distilled models for multilingual translation.
- M2M100 for broader multilingual support.

Local translation advantages:

- No monthly developer cost.
- Better privacy.
- Offline-capable after model download.
- No required user accounts or API keys.

Local translation limitations:

- Larger downloads.
- Slower inference on low-end hardware.
- Lower quality than some paid APIs for slang or context-heavy dialogue.

Optional API mode can support providers such as DeepL, Google Translate, or OpenAI-compatible APIs. In this mode, users provide and store their own API keys locally. The backend should never include project-owned production keys.

## 8. Rendering and Overlay

The final user experience depends heavily on how translations are displayed. The initial version can render translated text as browser overlays positioned on top of the original image. This is easier to iterate on than permanently modifying the image.

Overlay rendering should use OCR bounding boxes to place translated text close to the original speech bubble or text area. The extension can create absolutely positioned text layers above the image. Styling should prioritize readability with clear font color, optional outline, and background handling when needed.

Rendering modes:

- Text overlay mode: fastest to implement and easiest to edit.
- Image replacement mode: backend returns a modified image with text rendered into it.
- Hybrid mode: overlay by default, image rendering for export or static pages.

Future versions can improve this with bubble detection, automatic font sizing, background cleanup, and AI-assisted typesetting.

## 9. Caching and Performance

Caching is required for a smooth reading experience. Many users revisit chapters, reload pages, or scroll back and forth. Processing the same image repeatedly would waste time.

Cache keys can be generated from:

- Image URL.
- Image content hash.
- Source language.
- Target language.
- OCR engine version.
- Translation provider and model.

Possible cache layers:

- Browser IndexedDB for extension-side metadata.
- SQLite for backend-side persistent results.
- In-memory cache for active chapter sessions.

Performance improvements should include batch processing, progressive translation while scrolling, request deduplication, lazy processing of visible images, and skipping images that are too small to contain meaningful comic text.

## 10. Security and Privacy

The system should be private by default. Comic images and extracted text should remain on the user's device unless the user explicitly enables an external API provider.

Security principles:

- Run local processing by default.
- Do not upload images to project-owned servers.
- Store user API keys locally only.
- Avoid logging full image contents or sensitive API values.
- Let users clear cache from the extension settings.
- Restrict extension permissions to the minimum required.

If API mode is enabled, the UI should clearly indicate that text or image-derived content may be sent to the selected provider.

## 11. Development Roadmap

Phase 1 should validate the OCR and translation pipeline through a simple CLI or local web UI. The user can upload a JPG or PNG, run OCR, translate the result, and view the English output.

Phase 2 should improve comic-specific processing. This includes better preprocessing, multi-panel support, speech bubble detection, and backend caching.

Phase 3 should introduce the Chrome extension. The extension should detect images, communicate with the backend, and render translations as overlays on real chapter pages.

Phase 4 should focus on advanced reading quality. This includes better typesetting, chapter-wide caching, improved layout reconstruction, faster inference, and optional API-backed translation quality improvements.

## 12. Risks and Limitations

The largest risks are OCR accuracy, translation quality, and text placement. Stylized fonts and complex panel art can reduce OCR confidence. Translation models may misunderstand slang, names, honorifics, or context across panels. Rendering translated English into small speech bubbles can also be difficult because English text may be longer than the source text.

Other risks include browser compatibility, slow performance on low-end machines, large local model downloads, and legal considerations around processing copyrighted content. The project should position itself as a user-side accessibility and translation tool and avoid hosting or redistributing comic content.

## 13. Recommended MVP

The recommended MVP is a local FastAPI backend plus a simple Chrome extension overlay.

MVP scope:

- Detect large comic images on a page.
- Send visible images to the backend.
- Run PaddleOCR or EasyOCR.
- Translate with MarianMT or NLLB-200 distilled.
- Return translated text and bounding boxes.
- Render browser text overlays.
- Cache processed image results locally.

This MVP proves the full reading loop while keeping implementation complexity manageable. More advanced features like automatic bubble cleanup, perfect image replacement, and AI typesetting can be added after the basic pipeline is stable.
