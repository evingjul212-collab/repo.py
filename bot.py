import os
import asyncio
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters 
from motor.motor_asyncio import AsyncIOMotorClient
from google import genai
from google.genai import types

# =================================================================
# [1] CONFIG & DATABASE
# =================================================================
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
client_ai = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

MODELS = ["gemini-2.5-flash", "gemini-3.1-flash-lite-preview"] 

client_db = AsyncIOMotorClient(os.getenv("MONGO_URL"))
db = client_db.game_db
users = db.user_states

# =================================================================
# [2] HANDLER: START & GENRE
# =================================================================
async def start(update: Update, context):
    user_id = update.effective_user.id
    await users.update_one(
        {"_id": user_id},
        {"$set": {"state": "CHOOSING_GENRE"}},
        upsert=True
    )
    
    keyboard = [
        [InlineKeyboardButton("Roman Komedi 😂", callback_data="genre_romcom")],
        [InlineKeyboardButton("Roman Petualangan 🗺️", callback_data="genre_adventure")],
        [InlineKeyboardButton("Dewasa (21+) 🔥", callback_data="genre_mature")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "AI Story Engine v2 (No-Meta Edition) ✍️\nPilih tema ceritamu:",
        reply_markup=reply_markup
    )

async def select_genre(update: Update, context):
    query = update.callback_query
    user_id = query.from_user.id
    genre = query.data.split("_")[1]
    
    prompts = {
        "romcom": "Gaya bahasa romantis-komedi, ringan, penuh candaan, dan dialog yang mengalir.",
        "adventure": "Gaya bahasa naratif petualangan dengan deskripsi aksi yang tajam dan romansa kuat.",
        "mature": "Gaya bahasa intens, emosional, eksplisit (21+), fokus pada ketegangan fisik dan batin."
    }

    await users.update_one(
        {"_id": user_id},
        {"$set": {
            "current_story": {
                "genre": genre,
                "sys_prompt": prompts[genre],
                "summary": "Cerita baru dimulai.",
                "turn_count": 0
            },
            "state": "STORY_ONGOING"
        }}
    )
    
    await query.answer()
    await query.edit_message_text(f"Genre {genre.upper()} Terpilih! 🔓\nKetik premis atau aksi pertamamu...")

# =================================================================
# [3] ENGINE: ENHANCED GENERATOR WITH META-FILTER
# =================================================================
# =================================================================
# [3] ENGINE: DENGAN FITUR REGENERATE (!ulang)
# =================================================================
async def chat_engine(update: Update, context):
    user_id = update.effective_user.id
    user_msg = update.message.text
    
    # 1. AMBIL DATA
    data = await users.find_one({"_id": user_id})
    if not data or data.get("state") != "STORY_ONGOING":
        return

    story = data["current_story"]
    
    # =============================================================
    # FITUR PROTES / ULANG (!ulang)
    # =============================================================
    # Jika user mengetik !ulang, kita tidak menambah pesan ke summary, 
    # tapi langsung menembak AI lagi dengan input terakhir yang tersimpan.
    
    is_regenerate = False
    if user_msg.lower().startswith("!ulang"):
        is_regenerate = True
        # Ambil pesan terakhir user dari DB jika kamu menyimpannya, 
        # atau gunakan input manual terakhir. 
        # Untuk simpelnya, kita minta user: "!ulang [protesnya]"
        user_msg = user_msg.replace("!ulang", "").strip()
        if not user_msg:
            # Jika cuma ketik !ulang tanpa instruksi baru
            await update.message.reply_text("🔄 Mengulang alur sebelumnya...")
            # Kita gunakan pesan terakhir yang ada di summary (opsional)
        else:
            await update.message.reply_text(f"🛠 Memperbaiki alur: {user_msg}")
    
    # =============================================================

    turn_count = story.get("turn_count", 0) + 1

    # MASTER PROMPT (Instruksi diperketat agar tidak halu)
    master_prompt = (
        f"PERINTAH SISTEM:\n"
        f"- Kamu penulis genre {story['genre']}. TEPAT 3 paragraf (~1000 karakter).\n"
        f"- ANTI-HALU: Ikuti alur cerita secara logis. Perbanyak dialog interaktif.\n"
        f"- ANTI-META: Jangan pernah bahas sistem/metadata.\n"
        f"{'CATATAN PERBAIKAN: User protes alur sebelumnya halu. Perbaiki dengan instruksi: ' + user_msg if is_regenerate else ''}\n\n"
        f"KONTEKS ALUR:\n{story['summary']}\n\n"
        f"INPUT USER:\n{user_msg if not is_regenerate else 'Lanjutkan cerita dengan perbaikan di atas.'}\n\n"
        f"LANJUTKAN CERITA:"
    )

    safety_settings = [
        types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
        types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
        types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
        types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
    ]

    ai_text = None
    current_model_idx = 0 

    while ai_text is None:
        target_model = MODELS[current_model_idx]
        try:
            response = client_ai.models.generate_content(
                model=target_model,
                contents=master_prompt,
                config=types.GenerateContentConfig(safety_settings=safety_settings, temperature=0.8)
            )

            if response and response.text:
                ai_text = response.text.strip()
            else:
                raise Exception("Empty")
        except Exception as e:
            error_str = str(e).upper()
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                if current_model_idx == 0:
                    current_model_idx = 1
                    continue
                else:
                    await asyncio.sleep(10)
            else:
                await asyncio.sleep(3)
                current_model_idx = 1 if current_model_idx == 0 else 0

    # 4. UPDATE DATABASE
    # Jika ini REGENERATE, kita timpa log terakhir (opsional)
    # Jika ini NORMAL, kita tambahkan ke summary
    current_log = f"{story['summary']}\nAI (Perbaikan): {ai_text}" if is_regenerate else f"{story['summary']}\nUser: {user_msg}\nAI: {ai_text}"
    
    # Jaga agar summary tidak kepanjangan
    final_summary = current_log[-2500:]

    await users.update_one(
        {"_id": user_id},
        {"$set": {
            "current_story.summary": final_summary,
            "current_story.turn_count": turn_count
        }}
    )

    await update.message.reply_text(ai_text, parse_mode='Markdown')
    # Update Ringkasan (Setiap 5 Turn)
    current_log = f"{story['summary']}\nUser: {user_msg}\nAI: {ai_text}"
    
    if turn_count % 5 == 0:
        try:
            summary_res = client_ai.models.generate_content(
                model=MODELS[0],
                contents=f"Tugas: Buat ringkasan alur cerita (Maksimal 5 poin) agar tetap konsisten tanpa menyebut metadata teknis: {current_log}"
            )
            final_summary = summary_res.text if summary_res.text else current_log[-1500:]
        except:
            final_summary = current_log[-1500:]
    else:
        final_summary = current_log[-2000:]

    await users.update_one(
        {"_id": user_id},
        {"$set": {
            "current_story.summary": final_summary,
            "current_story.turn_count": turn_count
        }}
    )

    await update.message.reply_text(ai_text, parse_mode='Markdown')

# =================================================================
# [4] MAIN
# =================================================================
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(select_genre, pattern="^genre_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_engine))
    
    print("Engine v2 Berjalan. Target: 1000 Karakter, 3 Paragraf, Anti-Meta Aktif.")
    app.run_polling()

if __name__ == "__main__":
    main()
