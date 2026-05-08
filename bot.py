import os
import asyncio

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters
)

from motor.motor_asyncio import AsyncIOMotorClient
from google import genai 


# =================================================================
# [1] CONFIG & DATABASE
# =================================================================

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")

client_ai = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)

# MODEL PRIORITAS
MODELS = [

    "gemma-4-31b-it",
    "gemini-2.5-flash",
    "gemini-3.1-flash"
]

# MONGODB
client_db = AsyncIOMotorClient(os.getenv("MONGO_URL"))

db = client_db.game_db
users = db.user_states


# =================================================================
# [2] HANDLER: START
# =================================================================

async def start(update: Update, context):

    user_id = update.effective_user.id

    # reset state
    await users.update_one(
        {"_id": user_id},
        {
            "$set": {
                "state": "CHOOSING_GENRE"
            }
        },
        upsert=True
    )

    keyboard = [
        [
            InlineKeyboardButton(
                "Roman Komedi 😂",
                callback_data="genre_romcom"
            )
        ],
        [
            InlineKeyboardButton(
                "Roman Petualangan 🗺️",
                callback_data="genre_adventure"
            )
        ],
        [
            InlineKeyboardButton(
                "Dewasa 🔥",
                callback_data="genre_mature"
            )
        ]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "Selamat datang di AI Story Generator ✍️\n\nPilih tema cerita:",
        reply_markup=reply_markup
    )


# =================================================================
# [3] PILIH GENRE
# =================================================================

async def select_genre(update: Update, context):

    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id

    genre = query.data.split("_")[1]

    prompts = {
        "romcom": (
            "Gaya bahasa romantis komedi ringan, natural, lucu."
        ),

        "adventure": (
            "Gaya bahasa petualangan dramatis dengan unsur romansa."
        ),

        "mature": (
            "Gaya bahasa emosional dan dramatis untuk cerita dewasa."
        )
    }

    await users.update_one(
        {"_id": user_id},
        {
            "$set": {

                "state": "STORY_ONGOING",

                "current_story": {
                    "genre": genre,
                    "sys_prompt": prompts[genre],
                    "summary": "Cerita baru dimulai.",
                    "turn_count": 0
                }
            }
        }
    )

    await query.edit_message_text(
        f"Genre {genre.upper()} dipilih.\n\nKetik premis awal cerita."
    )


# =================================================================
# [4] GENERATE AI DENGAN RETRY
# =================================================================

async def generate_story(master_prompt):

    ai_text = None
    used_model = None

    while not ai_text:

        for model_name in MODELS:

            try:

                print(f"Generate pakai: {model_name}")

                response = client_ai.models.generate_content(
                    model=model_name,
                    contents=master_prompt
                )

                if response and response.text:

                    ai_text = response.text.strip()

                    if ai_text:

                        used_model = model_name

                        print(f"Berhasil dengan {model_name}")

                        return ai_text, used_model

            except Exception as e:

                print(f"Error {model_name}: {e}")

        # semua model gagal
        print("Semua model gagal. Retry 5 detik...")
        await asyncio.sleep(5)


# =================================================================
# [5] CHAT ENGINE
# =================================================================

async def chat_engine(update: Update, context):

    user_id = update.effective_user.id

    user_msg = update.message.text

    # ambil data user
    data = await users.find_one({"_id": user_id})

    if not data:
        return

    if data.get("state") != "STORY_ONGOING":
        return

    story = data["current_story"]

    turn_count = story.get("turn_count", 0) + 1

    # prompt utama
    master_prompt = (
    "Kamu adalah penulis cerita fiksi interaktif.\n"
    "ATURAN WAJIB:\n"
    "- Jangan pernah keluar dari sudut pandang karakter\n"
    "- Tidak boleh mengetahui masa depan\n"
    "- Tidak boleh membaca pikiran NPC\n"
    "- Tidak boleh meta / menyebut 'AI' atau 'model'\n"
    "- Tidak boleh tahu informasi yang belum muncul di cerita\n"
    "- Semua informasi harus berdasarkan adegan saat ini\n"
    "- Tidak boleh bersifat paranormal omniscient\n\n"
    
    f"Genre:\n{story['sys_prompt']}\n\n"
    f"Ringkasan:\n{story['summary']}\n\n"
    f"User:\n{user_msg}\n\n"
    "Lanjutkan cerita secara natural lebih banyak dialog sebanyak 80 % dari narasi."
    )

    # generate AI
    ai_text, used_model = await generate_story(master_prompt)

    # update summary
    current_summary = (
        f"{story['summary']}\n"
        f"User: {user_msg}\n"
        f"AI: {ai_text}"
    )

    # ringkas tiap 5 turn
    if turn_count % 5 == 0:

        try:

            summary_prompt = (
                "Ringkas cerita berikut menjadi poin penting "
                "agar karakter dan alur tetap konsisten:\n\n"
                f"{current_summary}"
            )

            final_summary, _ = await generate_story(summary_prompt)

        except Exception:

            final_summary = current_summary[-1000:]

    else:

        final_summary = current_summary[-1000:]

    # simpan DB
    await users.update_one(
        {"_id": user_id},
        {
            "$set": {
                "current_story.summary": final_summary,
                "current_story.turn_count": turn_count
            }
        }
    )

    # kirim hasil + nama model
    await update.message.reply_text(
    f"{ai_text}\n\n"
    f"━━━━━━━━━━\n"
    f"🤖 Model: {used_model}"
)


# =================================================================
# [6] MAIN
# =================================================================

def main():

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .concurrent_updates(True)
        .build()
    )

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CallbackQueryHandler(
            select_genre,
            pattern="^genre_"
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            chat_engine
        )
    )

    print("Bot berjalan...")

    app.run_polling()


# =================================================================
# RUN
# =================================================================

if __name__ == "__main__":
    main()
