# --------------------------------------------------------------
# import_handler.py
# --------------------------------------------------------------
import logging
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler, filters

log = logging.getLogger(__name__)

# ------------------------------------------------------------------
# /import – meminta user mengirim file .txt
# ------------------------------------------------------------------
async def import_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📄 Kirim file *.txt* yang berisi story lengkap.\n"
        "Format tiap scene harus:\n"
        "TURN <n>\nUSER: <teks>\nAI: <teks>\n--- (garis kosong) ---\n"
        "Jika format tidak tepat, bot akan mencoba mem‑parse semampunya."
    )

# ------------------------------------------------------------------
# Handler file upload
# ------------------------------------------------------------------
async def handle_import_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    if not document.file_name.lower().endswith(".txt"):
        await update.message.reply_text("⚠️ Hanya file .txt yang diterima.")
        return

    # download file ke memory
    file_obj = await context.bot.get_file(document.file_id)
    raw_bytes = await file_obj.download_as_bytearray()
    text = raw_bytes.decode("utf-8", errors="ignore")

    # --------------------------------------------------------------
    # Parse teks menjadi list scene
    # --------------------------------------------------------------
    scenes = []
    current = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.upper().startswith("TURN"):
            if current:
                scenes.append(current)
                current = {}
            try:
                current["turn"] = int(line.split()[1])
            except Exception:
                current["turn"] = len(scenes) + 1
        elif line.upper().startswith("USER:"):
            current["user"] = line[5:].strip()
        elif line.upper().startswith("AI:"):
            current["ai"] = line[3:].strip()
    if current:
        scenes.append(current)

    if not scenes:
        await update.message.reply_text("❌ Tidak dapat menemukan scene dalam file.")
        return

    # --------------------------------------------------------------
    # Simpan ke DB
    # --------------------------------------------------------------
    user_id = update.effective_user.id
    from memory import (
        set_genre,
        update_story,
        users,
    )

    # Set genre ke "imported" (atau ke nilai yang Anda inginkan)
    await set_genre(user_id, "imported", "Story di‑import, lanjutkan dari scene terakhir.")
    # Simpan list scene ke koleksi stories
    await update_story(user_id, [], "", "")          # memastikan dokumen ada
    # langsung timpa dengan scenes yang di‑import
    from memory import db
    await db.stories.update_one(
        {"_id": user_id},
        {"$set": {"scenes": scenes}},
        upsert=True,
    )
    # Simpan scene terakhir sebagai last_scene
    await users.update_one(
        {"_id": user_id},
        {"$set": {"last_scene": scenes[-1]}},
        upsert=True,
    )

    # --------------------------------------------------------------
    # Tampilkan scene terakhir (sebagai titik awal selanjutnya)
    # --------------------------------------------------------------
    last = scenes[-1]
    preview = (
        f"✅ Story berhasil di‑import!\n\n"
        f"*TURN {last['turn']}*\n"
        f"USER: {last['user']}\n"
        f"AI:   {last['ai']}\n\n"
        f"Ketik pesan selanjutnya untuk melanjutkan."
    )
    await update.message.reply_text(preview, parse_mode="Markdown")

# ------------------------------------------------------------------
# Registrasi handler ke Application (panggil di bot.py)
# ------------------------------------------------------------------
def register_import(app):
    app.add_handler(CommandHandler("import", import_command))
    app.add_handler(
        MessageHandler(filters.Document.TXT, handle_import_file)
    )
