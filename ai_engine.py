# --------------------------------------------------------------
# ai_engine.py
# --------------------------------------------------------------
import json
import logging
import google.generativeai as genai   # paket deprecated, tetap berfungsi
from config import GEMINI_API_KEY

log = logging.getLogger(__name__)

genai.configure(api_key=GEMINI_API_KEY)

# ------------------------------------------------------------------
# Daftar model yang didukung oleh paket google‑generativeai (v1beta)
# ------------------------------------------------------------------
SUPPORTED_GEMINI = {
    "gemini-2.5-flash",
    "gemini-3.1-flash-preview",
     # tambahkan yang lain bila ada
}

# ------------------------------------------------------------------
# Generate – wrapper dengan fallback sederhana
# ------------------------------------------------------------------
async def generate(prompt: str, model_name: str):
    """
    Returns (text, model_used)
    """
    # 1️⃣  Pastikan model ada di list SUPPORTED_GEMINI, kalau tidak – fallback
    primary = model_name if model_name in SUPPORTED_GEMINI else "gemini-2.5-flash"
    try:
        model = genai.GenerativeModel(primary)
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                temperature=0.9,
                top_p=0.95,
                max_output_tokens=8192,
                candidate_count=1,
            ),
        )
        return response.text, primary
    except Exception as e:
        log.exception(f"Generate gagal dengan {primary}")
        # fallback ke model default
        fallback = "gemini-2.5-flash"
        if fallback != primary:
            try:
                model = genai.GenerativeModel(fallback)
                response = model.generate_content(
                    prompt,
                    generation_config=genai.GenerationConfig(
                        temperature=0.9,
                        top_p=0.95,
                        max_output_tokens=8192,
                        candidate_count=1,
                    ),
                )
                return response.text, fallback
            except Exception as e2:
                log.exception("Fallback juga gagal")
        raise e   # jika kedua‑duanya gagal, lempar ke handler
