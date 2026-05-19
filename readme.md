# Auto Comic Translator

Auto Comic Translator is a browser extension that automatically translates webcomic/manhwa pages into English in near real-time.

It is designed to allow users to read raw chapters directly from official sources without waiting for translations.

---

## 🚀 Features

* Automatic image detection from web pages
* OCR-based text extraction
* Multi-language → English translation
* Overlay translated text on comic panels
* Local-first (completely free to use)
* Optional API support for better translations
* Caching for faster repeated reads

---

## 🧠 How It Works

1. Extension detects comic images on the page
2. Images are sent to a processing pipeline
3. OCR extracts text from the image
4. Text is translated to English
5. Translated text is rendered back onto the image
6. Image is replaced dynamically in the browser

---

## ⚙️ Tech Stack

* Frontend: JavaScript (Chrome Extension)
* Backend: Python (FastAPI)
* OCR: EasyOCR / PaddleOCR
* Translation: Local models or APIs
* Image Processing: OpenCV / PIL

---

## 💸 Cost Model

* Default: Fully free (local processing)
* Optional: Users can add their own API keys for better translation quality

---

## 📦 Installation (WIP)

### Extension

1. Clone the repo
2. Open Chrome Extensions
3. Enable Developer Mode
4. Load `/extension` folder

### Backend

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

### About file

See `_about.txt` for project background and notes. That file contains the original project motivation, scope, and attribution details used when this repository was created.

### Backend API files

This repo includes two API modules at the repository root that provide HTTP endpoints and helper runners:

- `api.py`: a lightweight, easy-to-run API wrapper for the OCR → translate → render pipeline. Use this for quick local testing or as a simple script-backed HTTP service (run with `python api.py`).
- `api_refined.py`: a refined ASGI-compatible implementation (improved caching, batching, and optional external API key support). Run it with Gunicorn/uvicorn: `uvicorn api_refined:app --reload`.

Refer to the source in `api.py` and `api_refined.py` for exact endpoints and payload formats. The backend FastAPI app in `backend/main.py` remains the primary production entrypoint when running the full pipeline.

### Run examples

Quick local runs:

```bash
# simple script mode
python api.py

# ASGI refined mode
uvicorn api_refined:app --reload

# full backend (recommended for extension + processing)
uvicorn backend.main:app --reload
```

---

## ⚠️ Limitations

* Translation may not be perfect
* Text placement may be rough
* OCR accuracy depends on font/style

---

## 🌍 Roadmap

* Multi-language support (JP, CN, KR → EN)
* Improved text placement
* Better UI controls
* Performance optimizations

---

## 🤝 Contributing

This project is open source and contributions are welcome.

---

## 📜 License

MIT License
