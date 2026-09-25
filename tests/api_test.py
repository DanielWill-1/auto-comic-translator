import requests

BASE_URL = "http://127.0.0.1:8000"
TIMEOUT = (5, 300)  # explicit connect and inference/read timeouts

health = requests.get(f"{BASE_URL}/health", timeout=(5, 30))
assert health.status_code == 200
health_body = health.json()
assert health_body["api_version"] == "1"
print("Health:", health_body)

readiness = requests.get(f"{BASE_URL}/ready", timeout=(5, 30))
assert readiness.status_code in (200, 503)
assert isinstance(readiness.json().get("ocr_ready"), bool)
assert isinstance(readiness.json().get("translation_ready"), bool)

with open("datas/japanes/Screenshot 2026-06-29 122805.png", "rb") as f:
    resp = requests.post(
        f"{BASE_URL}/translate",
        files={"image": ("test.png", f, "image/png")},
        data={"source_language": "ja", "target_language": "en"},
        timeout=TIMEOUT,
    )

print("Status:", resp.status_code)
d = resp.json()

if "error" in d:
    print("Error:", d["error"])
else:
    print("Regions:", d["num_regions"])
    print("OCR:", d["ocr_time_ms"], "ms")
    print("Translate:", d["translation_time_ms"], "ms")
    print("Total:", d["total_time_ms"], "ms")
    for r in d["regions"]:
        print(f"  {r['original_text']} -> {r['translated_text']}")
    print("PASS" if d["num_regions"] > 0 else "FAIL")

# Validation errors use the same envelope on the translation route.
with open("datas/japanes/Screenshot 2026-06-29 122805.png", "rb") as f:
    bad_language = requests.post(
        f"{BASE_URL}/translate",
        files={"image": ("test.png", f, "image/png")},
        data={"source_language": "unsupported", "target_language": "en"},
        timeout=(5, 30),
    )
assert bad_language.status_code == 400
assert bad_language.json()["error"]["code"] == "UNSUPPORTED_SOURCE_LANGUAGE"
