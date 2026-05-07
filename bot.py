import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from motor.motor_asyncio import AsyncIOMotorClient
from google import genai

# =================================================================
# [1] CONFIG & DATABASE
# =================================================================
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
client_ai = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODELS = ["gemini-2.5-flash"] # Menggunakan versi terbaru yang stabil

client_db = AsyncIOMotorClient(os.getenv("MONGO_URL"))
db = client_db.game_db
users = db.user_states

# =================================================================
# [2] HANDLER: START & GENRE
# =================================================================
async def start(update: Update, context):
    user_id = update.effective_user.id
    # Reset state di DB
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
        "Selamat datang di AI Story Generator! ✍️\nPilih tema ceritamu:",
        reply_markup=reply_markup
    )

async def select_genre(update: Update, context):
    query = update.callback_query
    user_id = query.from_user.id
    genre = query.data.split("_")[1]
    
    # Instruksi sistem berdasarkan genre
    prompts = {
        "romcom": "Gaya bahasa romantis-komedi, ringan, dan penuh candaan.",
        "adventure": "Gaya bahasa naratif petualangan dengan unsur romansa yang kuat.",
        "mature": "Gaya bahasa intens, emosional, dan eksplisit (21+). Fokus pada ketegangan hubungan."
    }

    await users.update_one(
        {"_id": user_id},
        {"$set": {
            "current_story": {
                "genre": genre,
                "sys_prompt": prompts[genre],
                "summary": "Cerita baru saja dimulai.",
                "turn_count": 0
            },
            "state": "STORY_ONGOING"
        }}
    )
    
    await query.answer()
    await query.edit_message_text(f"Genre {genre.upper()} terpilih! Silakan ketik premis awal ceritamu...")

# =================================================================
# [3] ENGINE: STORY GENERATOR & AUTO-SUMMARY
# =================================================================
async def chat_engine(update: Update, context):
    user_id = update.effective_user.id
    user_msg = update.message.text
    
    # Ambil data dari MongoDB
    data = await users.find_one({"_id": user_id})
    if not data or data.get("state") != "STORY_ONGOING":
        return

    story = data["current_story"]
    turn_count = story.get("turn_count", 0) + 1

    # Konstruksi Master Prompt
    master_prompt = (
        f"Role: {story['sys_prompt']}\n"
        f"Konteks Alur Sebelumnya: {story['summary']}\n\n"
        f"Input User: {user_msg}\n"
        f"Tugas: Lanjutkan cerita dengan konsisten."
    )

    # Generate dari Gemini
    response = client_ai.models.generate_content(model=MODELS[0], contents=master_prompt)
    ai_text = response.text

    # Update Ringkasan Otomatis (Setiap 5 putaran)
    current_summary = f"{story['summary']}\nUser: {user_msg}\nAI: {ai_text}"
    
    if turn_count % 5 == 0:
        summary_prompt = f"Ringkas alur cerita berikut menjadi poin-poin penting agar konsisten: {current_summary}"
        summary_res = client_ai.models.generate_content(model=MODELS[0], contents=summary_prompt)
        final_summary = summary_res.text
    else:
        final_summary = current_summary[-2000:] # Jaga agar tidak overload jika belum waktunya ringkas

    # Simpan kembali ke DB
    await users.update_one(
        {"_id": user_id},
        {"$set": {
            "current_story.summary": final_summary,
            "current_story.turn_count": turn_count
        }}
    )

    await update.message.reply_text(ai_text, parse_mode='Markdown')

# =================================================================
# [4] MAIN APP
# =================================================================
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(select_genre, pattern="^genre_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_engine))
    
    print("Bot Berjalan...")
    app.run_polling()

if __name__ == "__main__":
    main()
