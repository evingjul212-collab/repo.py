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
# [2] ENGINE: PROMPT BUILDER (Ketat 1000 Karakter)
# =================================================================
def build_master_prompt(story_data, user_input, state):
    chars = story_data.get("characters", [])
    char_info = "".join([f"- {c['name']}: {c.get('sifat')}\n" for c in chars])
    
    # Instruksi ini memaksa AI untuk tetap ringkas dan fokus pada dialog
    prompt = (
        f"Instruksi: Penulis novel profesional. Gunakan Bahasa Indonesia.\n"
        f"ATURAN: TEPAT 3 PARAGRAF. Total panjang teks sekitar 1000 karakter.\n"
        f"Gaya: Dominasi dialog antar karakter, narasi minimal.\n"
        f"Konteks Karakter:\n{char_info}\n"
        f"Ringkasan Terakhir: {story_data.get('summary', '')[:500]}\n\n"
    )
    
    if state == "WAIT_TS":
        prompt += f"LOGIKA TIME SKIP: {user_input}. Tulis adegan pembuka setelah waktu tersebut berlalu."
    else:
        prompt += f"Input User: {user_input}\nLanjutkan cerita."
        
    return prompt

# =================================================================
# [3] HANDLERS
# =================================================================
async def start(update: Update, context):
    user_id = update.effective_user.id
    await users.update_one({"_id": user_id}, {"$set": {"state": "NORMAL"}}, upsert=True)
    
    keyboard = [
        [InlineKeyboardButton("Time Skip ⏳", callback_data="go_timeskip")],
        [InlineKeyboardButton("Export (.json) 📥", callback_data="go_export")]
    ]
    await update.message.reply_text(
        "Bot Aktif. Kirim file .json untuk Import atau ketik pesan untuk lanjut:", 
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_callback(update: Update, context):
    query = update.callback_query
    user_id = query.from_user.id
    
    if query.data == "go_timeskip":
        await users.update_one({"_id": user_id}, {"$set": {"state": "WAIT_TS"}})
        await query.edit_message_text("Ketik durasi waktu (misal: 'Besok pagi' atau '1 jam kemudian'):")

    elif query.data == "go_export":
        data = await users.find_one({"_id": user_id})
        story = data.get("current_story", {})
        file = io.BytesIO(json.dumps(story, indent=4).encode())
        file.name = f"cerita_{user_id}.json"
        await query.message.reply_document(document=file, caption="File cadangan ceritamu.")

    elif query.data == "confirm_import":
        new_data = context.user_data.get('temp_import')
        await users.update_one({"_id": user_id}, {"$set": {"current_story": new_data, "state": "NORMAL"}})
        await query.edit_message_text("Import Berhasil! ✅ Silakan lanjut ceritanya.")

async def message_handler(update: Update, context):
    user_id = update.effective_user.id
    
    # FITUR IMPORT
    if update.message.document:
        doc = update.message.document
        if doc.file_name.endswith(".json"):
            file = await doc.get_file()
            content = await file.download_as_bytearray()
            context.user_data['temp_import'] = json.loads(content.decode("utf-8"))
            kb = [[InlineKeyboardButton("Ya, Timpa Cerita ✅", callback_data="confirm_import")]]
            await update.message.reply_text("File terdeteksi. Timpa database?", reply_markup=InlineKeyboardMarkup(kb))
        return

    # GENERASI CERITA
    msg = update.message.text
    data = await users.find_one({"_id": user_id})
    if not data: return
    
    story = data.get("current_story", {})
    prompt = build_master_prompt(story, msg, data.get("state"))
    
    response = client_ai.models.generate_content(model=MODEL_NAME, contents=prompt)
    ai_text = response.text[:3500] # Pengaman agar tidak melebihi limit Telegram

    # Update Summary di DB (Dibatasi 1000 karakter agar tidak 'bengkak')
    new_summary = f"{story.get('summary', '')} | {msg} -> {ai_text}"[-1000:]
    await users.update_one({"_id": user_id}, {
        "$set": {"current_story.summary": new_summary, "state": "NORMAL"}
    })
    
    await update.message.reply_text(ai_text)

# =================================================================
# [4] RUN
# =================================================================
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT | filters.Document.ALL, message_handler))
    app.run_polling()

if __name__ == "__main__":
    main()
