from transformers import AutoTokenizer
from transformers import AutoModelForSeq2SeqLM

MODEL = "facebook/nllb-200-distilled-600M"

tokenizer = AutoTokenizer.from_pretrained(MODEL)
model = AutoModelForSeq2SeqLM.from_pretrained(MODEL)

tokenizer.src_lang = "jpn_Jpan"

inputs = tokenizer(
    "こんにちは",
    return_tensors="pt"
)

translated = model.generate(
    **inputs,
    forced_bos_token_id=tokenizer.convert_tokens_to_ids("eng_Latn")
)

print(tokenizer.batch_decode(translated, skip_special_tokens=True))