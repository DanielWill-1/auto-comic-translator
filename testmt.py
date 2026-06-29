from transformers import MarianMTModel, MarianTokenizer
import os

MODELS = [
    {
        "name": "Japanese",
        "model": "Helsinki-NLP/opus-mt-ja-en",
        "text": "こんにちは。元気ですか？",
        "save_path": "./models/marian-ja-en",
    },
    {
        "name": "Korean",
        "model": "Helsinki-NLP/opus-mt-ko-en",
        "text": "안녕하세요. 오늘 기분이 어떠세요?",
        "save_path": "./models/marian-ko-en",
    },
    {
        "name": "Chinese",
        "model": "Helsinki-NLP/opus-mt-zh-en",
        "text": "你好，今天过得怎么样？",
        "save_path": "./models/marian-zh-en",
    },
]

os.makedirs("./models", exist_ok=True)

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

    print(f"\nSaving to {item['save_path']}...")

    model.save_pretrained(item["save_path"])
    tokenizer.save_pretrained(item["save_path"])

    print("Saved successfully!")

print("\n" + "=" * 60)
print("All MarianMT models downloaded, tested, and saved locally!")