# --------------------------------------------------------------
# ai_engine.py
# --------------------------------------------------------------
import os
import json
import logging
import asyncio
from typing import Tuple, Dict, Any

import google.generativeai as genai
import httpx

# ------------------------------------------------------------------
# 0️⃣ Environment
# ------------------------------------------------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise RuntimeError("⚠️  GEMINI_API_KEY belum di‑set di environment!")

genai.configure(api_key=GEMINI_API_KEY)

# ------------------------------------------------------------------
# 1️⃣ Model‑Map (hanya yang berfungsi)
# ------------------------------------------------------------------
MODEL_MAP: Dict[str, Dict[str, Any]] = {
    # ---------------------- Gemini ----------------------
    "gemini-2.5-flash": {
        "provider": "gemini",
        "model_id": "gemini-1.5-flash",          # ID yang di‑expose di AI‑Studio
        "fallback": "gemini-2.5-flash",
    },
    "gemini-3.1-flash-preview": {
        "provider": "gemini",
        "model_id": "gemini-1.5-pro",            # versi preview yang masih tersedia
        "fallback": "gemini-2.5-flash",
    },
    # ---------------------- Gemma -----------------------
    "gemma-4-31b-it": {
        "provider": "gemma",
        "model_id": "gemma-4-31b-it",
        "fallback": "gemma-4-31b-it",
    },
}

# Daftar fallback urutan – dipakai bila model utama mengembalikan error
DEFAULT_FALLBACKS = [
    "gemini-2.5-flash",
    "gemma-4-31b-it",
]

# ------------------------------------------------------------------
# 2️⃣ Helper untuk Gemini (sinkron, dijalankan lewat thread)
# ------------------------------------------------------------------
def _call_gemini(model_id: str, prompt: str) -> str:
    """Generate content dengan Google Gemini."""
    try:
        model = genai.GenerativeModel(model_id)
        resp = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.9,
                top_p=0.95,
                max_output_tokens=8192,
            ),
        )
        return resp.text.strip()
    except Exception as exc:
        # Log error termasuk kode status bila tersedia
        logging.error("[Gemini] %s – %s", model_id, exc)
        raise

# ------------------------------------------------------------------
# 3️⃣ Helper untuk Gemma (OpenAI‑compatible endpoint)
# ------------------------------------------------------------------
def _call_gemma(model_id: str, prompt: str) -> str:
    """
    Memanggil model Gemma lewat Google Generative Language API
    (OpenAI‑compatible).  Endpoint default = https://generativelanguage.googleapis.com/v1beta/models
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent"
    params = {"key": GEMINI_API_KEY}
    payload = {
        "prompt": {"text": prompt},
        "temperature": 0.9,
        "candidateCount": 1,
        "topP": 0.95,
        "maxOutputTokens": 8192,
    }

    try:
        r = httpx.post(url, params=params, json=payload, timeout=30.0)
        r.raise_for_status()
        data = r.json()
        if not data.get("candidates"):
            raise RuntimeError("Tidak ada candidate pada response Gemma")
        return data["candidates"][0]["output"].strip()
    except httpx.HTTPStatusError as hs:
        # 4xx atau 5xx – catat kode dan pesan
        logging.error(
            "[Gemma] %s – HTTP %s – %s",
            model_id,
            hs.response.status_code,
            hs.response.text,
        )
        raise
    except Exception as exc:
        logging.error("[Gemma] %s – %s", model_id, exc)
        raise

# ------------------------------------------------------------------
# 4️⃣ Core async wrapper (generate)
# ------------------------------------------------------------------
async def generate(prompt: str, model_name: str) -> Tuple[str, str]:
    """
    Public API dipanggil bot:
        ai_text, model_used = await generate(prompt, selected_model)

    Parameters
    ----------
    prompt : str
        Prompt lengkap (system‑prompt + story history).
    model_name : str
        Nama model yang dipilih pengguna (harus ada di MODEL_MAP).

    Returns
    -------
    Tuple[str, str] – (generated text, model‑identifier yang dipakai)
    """
    key = model_name.strip().lower()
    # bersihkan kalau ada prefix seperti "models/gemini-2.5-flash"
    if "/" in key:
        key = key.split("/")[-1]

    cfg = MODEL_MAP.get(key)
    if not cfg:
        # Model tidak dikenal – fallback ke default pertama
        logging.warning("Model tidak terdaftar: %s – memakai fallback default", key)
        key = DEFAULT_FALLBACKS[0]
        cfg = MODEL_MAP[key]

    async def _run(provider: str, model_id: str) -> str:
        if provider == "gemini":
            return await asyncio.to_thread(_call_gemini, model_id, prompt)
        else:   # gemma
            return await asyncio.to_thread(_call_gemma, model_id, prompt)

    # --------------------------------------------------------------
    # 4.1  Panggil model utama
    # --------------------------------------------------------------
    try:
        txt = await _run(cfg["provider"], cfg["model_id"])
        return txt, key
    except Exception as primary_err:
        logging.error(
            "Generate gagal dengan %s (%s). Error: %s",
            key,
            cfg["provider"],
            primary_err,
        )

    # --------------------------------------------------------------
    # 4.2  Coba fallback yang sudah didefinisikan di config
    # --------------------------------------------------------------
    fallback_key = cfg.get("fallback")
    if fallback_key and fallback_key != key:
        fb_cfg = MODEL_MAP.get(fallback_key)
        if fb_cfg:
            try:
                txt = await _run(fb_cfg["provider"], fb_cfg["model_id"])
                return txt, f"{fallback_key} (fallback)"
            except Exception as fb_err:
                logging.error(
                    "Fallback %s gagal. Error: %s", fallback_key, fb_err
                )

    # --------------------------------------------------------------
    # 4.3  Jika fallback masih gagal, coba urutan DEFAULT_FALLBACKS
    # --------------------------------------------------------------
    for fb_key in DEFAULT_FALLBACKS:
        if fb_key == key:
            continue
        fb_cfg = MODEL_MAP.get(fb_key)
        if not fb_cfg:
            continue
        try:
            txt = await _run(fb_cfg["provider"], fb_cfg["model_id"])
            return txt, f"{fb_key} (fallback)"
        except Exception as fb_err:
            logging.warning("Fallback %s gagal lagi: %s", fb_key, fb_err)

    # --------------------------------------------------------------
    # 4.4  Semua percobaan gagal → lempar error untuk ditangani bot
    # --------------------------------------------------------------
    raise RuntimeError(
        f"Semua percobaan AI gagal (primary: {primary_err})"
    )

# ------------------------------------------------------------------
# 5️⃣ Debug/demo (jalankan `python ai_engine.py` untuk tes)
# ------------------------------------------------------------------
if __name__ == "__main__":
    async def _demo():
        demo_prompt = "Buat intro 2 kalimat tentang seorang petualang bernama Danu yang sedang berada di hutan Amazon."
        for model in ["gemini-2.5-flash", "gemini-3.1-flash-preview", "gemma-4-31b-it"]:
            try:
                out, used = await generate(demo_prompt, model)
                print(f"\n=== {used} ===\n{out[:200]}...\n")
            except Exception as e:
                print(f"❌ {model} error → {e}")

    asyncio.run(_demo())
