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
