# =========================
# config.py
# =========================

import os

# ====================================
# TELEGRAM
# ====================================

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")

# ====================================
# GEMINI API
# ====================================

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ====================================
# MONGODB
# ====================================

MONGO_URL = os.getenv("MONGO_URL")

# ====================================
# MODEL YANG TERSEDIA
# ====================================

AVAILABLE_MODELS = {

    # =====================
    # RECOMMENDED
    # =====================

    "Gemini 3.1 Flash Lite":
    "gemini-3.1-flash-lite-preview",

    "Gemini 2.5 Flash":
    "gemini-2.5-flash",

    "Gemini 2.5 Pro":
    "gemini-2.5-pro",

    "Gemini 2.0 Flash":
    "gemini-2.0-flash",

    # =====================
    # GEMMA
    # =====================

    "Gemma 4 31B":
    "gemma-4-31b-it",

    "Gemma 4 26B":
    "gemma-4-26b-a4b-it",

    "Gemma 3 27B":
    "gemma-3-27b-it"
}

# ====================================
# FALLBACK MODEL
# ====================================

FALLBACK_MODELS = [

    "gemini-2.5-flash",

    "gemini-2.0-flash"
]
