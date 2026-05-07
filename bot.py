import os
import io
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from motor.motor_asyncio import AsyncIOMotorClient
from google import genai

# =================================================================
# [1] CONFIG & DATABASE
# =================================================================
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
client_ai = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODEL_NAME = "gemini-2.5-flash" 

client_db = AsyncIOMotorClient(os.getenv("MONGO_URL"))
db = client_db.game_db
users = db.user_states

# =================================================================
# [2] ENGINE: PROMPT BUILDER
# =================================================================
def build_master_prompt(story_data, user_input, state):
    chars = story_data.get("characters", [])
    char_info = ""
    for c in chars:
        char_info += f"- {c['name']} (Fisik: {c.get('fisik')}, Sifat: {c.get('sifat')}, Hubungan: {c.get('hubungan')})\n"
    
    prompt = (
        f"Instruksi: Penulis novel {story_data.get('genre', 'dewasa')} profesional.\n"
        f"Format: WAJIB 3 PARAGRAF. Gunakan SEDIKIT narasi dan BANYAK dialog intens.\n"
        f"Karakter:\n{char_info}\n"
        f"Ringkasan Sebelumnya: {story_data.get('summary', 'Baru dimulai')}\n\n"
    )
    
    if state == "WAIT_TS":
        prompt += f"LOGIKA TIME SKIP: {user_input}. Tulis adegan setelah waktu berlalu tersebut."
    else:
        prompt += f"Input User: {user_input}\nLanjutkan cerita dengan dialog yang kuat."
        
    return prompt

# =================================================================
# [3] HANDLERS
# =================================================================
async def start(update: Update, context):
    user_id = update.effective_user.id
    await users.update_one({"_id": user_id}, {"$set": {"state": "NORMAL"}}, upsert=True)
    
    keyboard = [
        [InlineKeyboardButton("Genre: Romansa Petualangan", callback_data="set_adventure")],
        [InlineKeyboardButton("Genre: Dewasa (21+)", callback_data="set_mature")],
        [InlineKeyboardButton("Time Skip ⏳", callback_data="go_timeskip")],
        [InlineKeyboardButton("Export (.json) 📥", callback_data="go_export")]
    ]
    await update.message.reply_text(
        "Sistem Siap. Kirim file .json untuk Import, pilih menu, atau ketik untuk mulai:", 
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_callback(update: Update, context):
    query = update.callback_query
    user_id = query.from_user.id
    
    if query.data.startswith("set_"):
        genre = query.data.split("_")[1]
        await users.update_one({"_id": user_id}, {"$set": {
            "current_story": {"genre": genre, "summary": "Awal cerita.", "characters": []},
            "state": "NORMAL"
        }})
        await query.edit_message_text(f"Genre {genre.upper()} aktif. Silakan tulis premis!")

    elif query.data == "go_timeskip":
        await users.update_one({"_id": user_id}, {"$set": {"state": "WAIT_TS"}})
        await query.edit_message_text("Mau melompat berapa lama? (Contoh: 'Besok pagi' atau '1 tahun kemudian')")

    elif query.data == "go_export":
        data = await users.find_one({"_id": user_id})
        story = data.get("current_story", {})
        file = io.BytesIO(json.dumps(story, indent=4).encode())
        file.name = f"cerita_{user_id}.json"
        await query.message.reply_document(document=file, caption="Cadangan ceritamu.")

    elif query.data == "confirm_import":
        new_data = context.user_data.get('temp_import')
        await users.update_one({"_id": user_id}, {"$set": {"current_story": new_data, "state": "NORMAL"}})
        await query.edit_message_text("Import Berhasil! ✅ Silakan lanjut ceritanya.")

async def message_handler(update: Update, context):
    user_id = update.effective_user.id
    
    # Cek jika ada file (Import)
    if update.message.document:
        doc = update.message.document
        if doc.file_name.endswith(".json"):
            file = await doc.get_file()
            content = await file.download_as_bytearray()
            import_data = json.loads(content.decode("utf-8"))
            context.user_data['temp_import'] = import_data
            
            kb = [[InlineKeyboardButton("Ya, Timpa ✅", callback_data="confirm_import")]]
            await update.message.reply_text(f"File terdeteksi. Timpa cerita lama?", reply_markup=InlineKeyboardMarkup(kb))
        return

    # Chat Biasa / Time Skip
    msg = update.message.text
    data = await users.find_one({"_id": user_id})
    if not data: return
    
    state = data.get("state")
    story = data.get("current_story", {})
    
    prompt = build_master_prompt(story, msg, state)
    response = client_ai.models.generate_content(model=MODEL_NAME, contents=prompt)
    ai_text = response.text

    # Update Summary (Simpan 1500 karakter terakhir agar konsisten)
    new_summary = f"{story.get('summary', '')} | {msg} -> {ai_text}"[-1500:]
    await users.update_one({"_id": user_id}, {
        "$set": {"current_story.summary": new_summary, "state": "NORMAL"}
    })
    
    await update.message.reply_text(ai_text)

# =================================================================
# [4] MAIN
# =================================================================
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT | filters.Document.ALL, message_handler))
    app.run_polling()

if __name__ == "__main__":
    main()
