from transformers import MarianMTModel, MarianTokenizer
from pathlib import Path

# Derive the repository root from this script's location so the downloaded
# models land in <repo>/models regardless of the current working directory.
REPO_ROOT = Path(__file__).resolve().parent.parent
MODELS_ROOT = REPO_ROOT / "models"

MODELS = [
    {
        "name": "Japanese",
        "model": "Helsinki-NLP/opus-mt-ja-en",
        "text": "こんにちは。元気ですか？",
        "save_path": "marian-ja-en",
    },
    {
        "name": "Korean",
        "model": "Helsinki-NLP/opus-mt-ko-en",
        "text": "안녕하세요. 오늘 기분이 어떠세요?",
        "save_path": "marian-ko-en",
    },
    {
        "name": "Chinese",
        "model": "Helsinki-NLP/opus-mt-zh-en",
        "text": "你好，今天过得怎么样？",
        "save_path": "marian-zh-en",
    },
]

MODELS_ROOT.mkdir(parents=True, exist_ok=True)

for item in MODELS:
    print("=" * 60)
    print(f"Loading {item['name']} model...")

    tokenizer = MarianTokenizer.from_pretrained(item["model"])
    model = MarianMTModel.from_pretrained(item["model"])

    print("Model loaded!")

    inputs = tokenizer(
        item["text"],
        return_tensors="pt",
        padding=True,
    )

    translated = model.generate(**inputs)

    result = tokenizer.decode(
        translated[0],
        skip_special_tokens=True,
    )

    print("\nOriginal:")
    print(item["text"])

    print("\nTranslation:")
    print(result)

    save_dir = MODELS_ROOT / item["save_path"]
    print(f"\nSaving to {save_dir}...")

    model.save_pretrained(str(save_dir))
    tokenizer.save_pretrained(str(save_dir))

    print("Saved successfully!")

print("\n" + "=" * 60)
print("All MarianMT models downloaded, tested, and saved locally!")