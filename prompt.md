We are blocked in Phase 3.3 by a real PaddleOCR compatibility issue.

Current environment:

Global Python:
C:\Users\danie\AppData\Local\Programs\Python\Python311\python.exe

Installed and importable:
paddle 3.3.1
paddleocr 3.7.0
paddlex 3.7.2
torch 2.5.1+cu121

The project .venv currently hangs while importing torch on Windows, so
for now the working runtime is global Python.

Backend startup currently succeeds with global Python, but warmup reports:

"Pipeline warmup incomplete: Cannot verify that PaddleOCR model downloads are disabled."

This blocks real OCR initialization.

DO NOT downgrade or reinstall packages yet.

DO NOT modify the extension.

DO NOT begin Phase 3.4.

The task is to diagnose and fix ONLY the local PaddleOCR model-download
protection check so the backend can safely initialize OCR using already
present local assets.

============================================================
GOAL
============================================================

Make the backend correctly verify that PaddleOCR/PaddleX will NOT
download models at request time, for the actually installed versions:

paddleocr 3.7.0
paddlex 3.7.2

Then allow warmup to proceed if local OCR assets are already available.

No network download must occur.

============================================================
FIRST — INSPECT
============================================================

Inspect:

backend/ocr.py
backend/main.py
backend/config.py

Search for:

PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK
model download checks
environment-variable guards
PaddleOCR constructor logic
PaddleX model-source logic

Also inspect current PaddleOCR/PaddleX installed APIs from the actual
runtime.

Use small introspection commands where useful, for example:

python -c "import paddleocr, inspect; ..."
python -c "import paddlex, inspect; ..."

Do not guess API behavior from older versions.

============================================================
IMPORTANT
============================================================

The project previously hardened OCR so missing local assets do NOT cause
automatic downloads.

Preserve that guarantee.

Do NOT fix startup by simply deleting the safety check.

Do NOT set a flag blindly unless the installed library actually honors
it.

We need a version-correct verification mechanism.

============================================================
WHAT TO DETERMINE
============================================================

Find out:

1. Whether PaddleOCR 3.7.0 still uses
   PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK

2. Whether PaddleX 3.7.2 uses a different environment variable or model
   source configuration mechanism

3. Whether local model directories can be supplied explicitly to avoid
   remote model resolution entirely

4. Whether PaddleOCR constructor arguments changed in 3.x

5. Whether the backend's current verification logic was written for an
   older PaddleOCR/PaddleX release

============================================================
LOCAL-ONLY REQUIREMENT
============================================================

The final OCR initialization must behave like this:

local OCR assets exist
    -> initialize from local files

local OCR assets missing
    -> fail clearly

local OCR assets missing
    -> DO NOT download anything

No silent network fallback.

============================================================
PREFERRED FIX
============================================================

Prefer explicit local model paths over heuristic environment checking if
PaddleOCR 3.7.0 supports that reliably.

If explicit local paths are enough to guarantee no download, document
and use that.

If PaddleX still requires a disable-download/source-check environment
variable, set and verify the correct one before importing/initializing.

Avoid brittle introspection if the installed package exposes a cleaner
supported mechanism.

============================================================
VERSION COMPATIBILITY
============================================================

The fix should ideally support the currently installed versions first.

Do not generalize across every historical PaddleOCR version unless it is
simple.

If needed, detect behavior/version explicitly.

But avoid a giant compatibility matrix.

============================================================
DO NOT TOUCH
============================================================

Do not modify:

extension/
docs unrelated to this issue
cache logic
translation logic
API contract
Phase 3 behavior

Unless a minimal docs note is needed after the fix.

============================================================
TEST
============================================================

After the fix, run:

python -m backend.main

Expected:
- no "Cannot verify that PaddleOCR model downloads are disabled"
- warmup attempts real local OCR initialization
- if a local OCR asset is missing, error names that missing asset instead
  of attempting download

Also run a direct import/initialization check.

Then run:

pytest

python -m compileall backend scripts

git diff --check

============================================================
NETWORK SAFETY CHECK
============================================================

Do not download anything during testing.

If practical, temporarily disable network access or otherwise verify no
remote fetch occurs.

At minimum inspect logs carefully for:
- model downloads
- huggingface fetches
- Paddle model source fetches
- remote URLs

============================================================
FINAL REPORT
============================================================

Return:

### Root cause
Exactly why the old verification failed with PaddleOCR 3.7.0 /
PaddleX 3.7.2.

### Fix
Exact file(s) changed and how local-only behavior is now enforced.

### Local asset behavior
What happens when assets exist vs are missing.

### Validation
Exact commands/results.

### Downloads
Explicitly confirm whether anything was downloaded.

### Backend startup
Show whether warmup now succeeds or what specific local asset remains
missing.

Do NOT continue Phase 3.3 automatically.