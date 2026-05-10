import os
from google import genai
import logging

log = logging.getLogger(__name__)

client_ai = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# ----------------------------------------------------------------------
# generate – menyesuaikan dengan model yang dipilih
# ----------------------------------------------------------------------
async def generate(prompt: str, model_name: str):
    try:
        model = genai.GenerativeModel(model_name)
        resp = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.7,
                top_p=0.95,
                max_output_tokens=2048,
            ),
        )
        return resp.text.strip(), model_name
    except Exception as e:
        log.exception("Generate error")
        # fallback ke model default (gemini‑2.5‑flash)
        fallback = genai.GenerativeModel("gemini-2.5-flash")
        resp = fallback.generate_content(prompt)
        return resp.text.strip(), "fallback(gemini-2.5-flash)"
