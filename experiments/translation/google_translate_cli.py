import argparse
from deep_translator import GoogleTranslator
from deep_translator.exceptions import LanguageNotSupportedException

def main():
    parser = argparse.ArgumentParser(description="Translate text to multiple languages.")
    parser.add_argument("text", help="The text you want to translate enclosed in quotes.")
    parser.add_argument("-s", "--source", default="auto", help="Source language code (e.g., 'en'). Default is 'auto'.")
    parser.add_argument("-t", "--targets", nargs="+", required=True, help="List of target language codes (e.g., 'fr' 'es' 'ja').")
    
    args = parser.parse_args()

    print(f"\nOriginal [{args.source}]: {args.text}")
    print("-" * 40)

    for target in args.targets:
        try:
            translator = GoogleTranslator(source=args.source, target=target)
            translated_text = translator.translate(args.text)
            print(f"-> [{target.upper()}]: {translated_text}")
        except LanguageNotSupportedException:
            print(f"-> [{target.upper()}]: Error - Language code not supported.")
        except Exception as e:
            print(f"-> [{target.upper()}]: Error - {str(e)}")

if __name__ == "__main__":
    main()