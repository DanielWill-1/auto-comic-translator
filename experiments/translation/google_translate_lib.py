import sys
from deep_translator import GoogleTranslator

def translate_payload(text: str, target_langs: list, source_lang: str = "auto") -> dict:
    """
    Translates input text into multiple target languages.
    Returns a dictionary mapping the language code to the translated string.
    """
    results = {}
    for lang in target_langs:
        try:
            # Under the hood: This triggers an HTTP POST request to Google's translation endpoints
            translated = GoogleTranslator(source=source_lang, target=lang).translate(text)
            results[lang] = translated
        except Exception as e:
            results[lang] = f"Error: {str(e)}"
    return results

if __name__ == "__main__":
    # Quick terminal test
    sample_text = "Hello world, welcome to machine learning."
    targets = ["es", "fr", "de"]
    
    print(f"Translating: '{sample_text}'")
    translations = translate_payload(sample_text, targets)
    
    for lang, output in translations.items():
        print(f"[{lang.upper()}]: {output}")