import json, requests, sys

with open("datas/japanes/Screenshot 2026-06-29 122805.png", "rb") as f:
    resp = requests.post(
        "http://localhost:8000/translate",
        files={"image": ("test.png", f, "image/png")},
        data={"source_language": "ja", "target_language": "en"},
        timeout=300,
    )

print("Status:", resp.status_code)
d = resp.json()

if "detail" in d:
    print("Error:", d["detail"])
else:
    print("Regions:", d["num_regions"])
    print("OCR:", d["ocr_time_ms"], "ms")
    print("Translate:", d["translation_time_ms"], "ms")
    print("Total:", d["total_time_ms"], "ms")
    for r in d["regions"]:
        print(f"  {r['original_text']} -> {r['translated_text']}")
    print("PASS" if d["num_regions"] > 0 else "FAIL")
