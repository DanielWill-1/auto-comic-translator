# Image translation test site

This local-only fake comic reader exercises Phase 3.2 image detection and the
Phase 3.3 explicit translation request. It references existing samples under
`datas/` and includes small icon, avatar, banner, and hidden-image cases.
Orange outlines mark development candidates. The result card is temporary
debugging UI, not a translation overlay.

From the repository root, start the backend and test page in separate
terminals. Use the project environment for the backend:

```powershell
.\.venv\Scripts\python.exe -m backend.main
```

```powershell
python -m http.server 8080 --bind 127.0.0.1
```

Load the unpacked `extension/` directory in Chromium and open
<http://127.0.0.1:8080/dev/test-site/>. Use this exact IP address: the
content script is matched only to `http://127.0.0.1:8080/*`, so
`http://localhost:8080/` is not included.

For the real Japanese sample check:

1. In the extension popup, enable **Translator** and select **Japanese** as
   the source language. The sample is Japanese so this avoids unrelated OCR
   reader assets.
2. Confirm the comic samples have orange candidate outlines.
3. Alt+Click the first Japanese sample once. Only that image is submitted.
4. Wait for the debug card. It shows detected text, translation status,
   dimensions, and the backend request ID. The browser Network panel should
   show `POST /translate` with HTTP 200 and API version `1`.
5. Confirm the page did not reload. Alt+Click the same sample again after the
   first request finishes; the card should report a cache hit when available.
6. Use the card's close button to remove the development result. Turning off
   **Translator** removes candidate marks and any remaining debug cards.

The first real inference can take many seconds; the extension allows 60
seconds. Do not download models during this test. If the backend reports
missing local OCR assets, stop and address the environment setup separately.

The content script fetches image bytes from the selected image source. A small
extension service worker posts those bytes to the fixed local backend because
Chrome keeps content-script requests under the page's CORS origin. External
sites may block image fetching or require narrow host permissions; this
fixture uses same-origin files. The request body contains no page text or page
URL.
