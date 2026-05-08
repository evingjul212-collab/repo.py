# =========================
# ai_engine.py
# =========================

import asyncio

from google import genai

from config import (
    GEMINI_API_KEY,
    FALLBACK_MODELS
)

# =========================
# GEMINI CLIENT
# =========================

client = genai.Client(
    api_key=GEMINI_API_KEY
)

# =========================
# GENERATE AI
# =========================

async def generate(prompt, selected_model):

    # =================================
    # PRIORITAS MODEL USER
    # =================================

    models_to_try = [
        selected_model
    ] + FALLBACK_MODELS

    # hapus duplicate
    models_to_try = list(dict.fromkeys(models_to_try))

    # =================================
    # LOOP MODEL
    # =================================

    for model in models_to_try:

        try:

            print(f"TRY MODEL: {model}")

            response = client.models.generate_content(
                model=model,
                contents=prompt
            )

            if response and response.text:

                text = response.text.strip()

                if text:

                    return text, model

        except Exception as e:

            print(f"MODEL ERROR {model}: {e}")

            await asyncio.sleep(1)

    # =================================
    # SEMUA GAGAL
    # =================================

    return (
        "⚠️ Semua model sedang sibuk atau error.",
        "fallback"
    )
