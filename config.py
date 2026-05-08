import os

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MONGO_URL = os.getenv("MONGO_URL")

MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemma-4-31b-it"
]
