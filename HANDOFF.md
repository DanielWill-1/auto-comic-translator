# Project handoff

Checkpoint: 2026-09-27

## Current state

- Phases 1, 2, and 2.5 are complete. Phase 3.1 (extension shell and backend
  connection) and Phase 3.2 (comic image discovery) are complete. See
  [`docs/ROADMAP.md`](docs/ROADMAP.md) for the phase plan.
- Phase 3.3 implements an explicit Alt+Click request for one outlined image
  and displays a temporary debug result. The backend OCR call now supports
  PaddleOCR 2.x and 3.x. The API round trip has been verified; the manual
  Chromium Alt+Click check is still pending.
- Phase 3.4 has not started.

## OCR compatibility fix

The available runtime is PaddlePaddle 3.3.1, PaddleOCR 3.7.0, and PaddleX
3.7.2. In this version, `PaddleOCR.ocr` accepts `**kwargs` and forwards to
`predict`; `PaddleOCR.predict` does not accept `cls`. The old
`reader.ocr(image, cls=True)` call therefore raised `TypeError`.

`backend/ocr.py` inspects the reader's API and uses `cls=True` only when the
legacy method explicitly supports it. Otherwise it uses the 3.x `predict`
API when available, without catching unrelated `TypeError` exceptions. The
result adapter handles the PaddleOCR 2.x nested list format and PaddleX 3.x
prediction fields (`rec_texts`, `rec_scores`, and polygon arrays).

## Verification already completed

- Direct CPU OCR on
  `datas/japanes/Screenshot 2026-06-29 122805.png` returned 15 regions.
  One returned region was `全部`, confidence `0.9967`, with polygon
  `[[331, 271], [351, 269], [354, 301], [334, 303]]` and language `ja`.
- A real Japanese image sent to `POST /translate` returned HTTP 200 and API
  v1 JSON with 7 regions and nonempty original and translated text.
- Focused compatibility coverage checks the legacy nested result format,
  PaddleX 3.x prediction fields, the no-`cls` call, and propagation of an
  unrelated `TypeError` raised inside OCR.
- `pytest`: 81 passed, 15 skipped, 13 warnings.
- `python -m compileall backend scripts`: passed.
- `git diff --check`: passed.
- No model downloads occurred. The Japanese OCR check also succeeded with
  outbound socket connections blocked.
- No extension files were changed as part of the OCR compatibility fix.

These checks verify the OCR invocation, response parsing, and HTTP contract.
They do not assess translation quality.

## Environment and known limits

- The checks used the machine's global Python 3.11 environment, with the
  Paddle versions listed above. Importing `torch` from the repository's
  `.venv` stalled in this environment, so the global Python executable was
  used for the verified OCR and server runs.
- Japanese local OCR assets are available. Korean assets needed for full
  warmup/auto-language coverage are missing from the local cache; use the
  explicit Japanese source language for the manual sample check.
- The backend was started without reload on `127.0.0.1:8000` for the manual
  browser check. If it is no longer running, start it from the repository
  root using the same Python environment that has the local models:

  ```powershell
  python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
  ```

## Next action

Load or reload the unpacked extension, open the local fixture at
`http://127.0.0.1:8080/dev/test-site/`, choose **Japanese** in the popup, and
Alt+Click the first Japanese sample. Confirm the Network panel shows
`POST /translate` with status 200 and the debug card shows original and
translated text. The full procedure is in
[`dev/test-site/README.md`](dev/test-site/README.md).

Once that manual check is recorded, update the Phase 3.3 status in
[`README.md`](README.md) and [`docs/ROADMAP.md`](docs/ROADMAP.md). Do not begin
Phase 3.4 until the Phase 3.3 check is complete.
