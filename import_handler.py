# import_handler.py
import logging
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, MessageHandler, filters, CommandHandler

from memory import import_story, get_user

log = logging.getLogger(__name__)

# --------------------------------------------------------------
# /import  (perintah text)
# --------------------------------------------------------------
async def import_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Kirim file *.txt* yang berisi story replay. "
        "Format tiap scene harus:\n"
        "```\nTURN: <nomor>\nUSER: <teks>\nAI: <teks>\n```"
    )

# --------------------------------------------------------------
# Document handler – file .txt
# --------------------------------------------------------------
async def handle_import_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc.file_name.lower().endswith(".txt"):
        await update.message.reply_text("❌ Hanya menerima file *.txt*.")
        return

    # Download file ke memory (tidak disimpan di disk)
    file_obj = await doc.get_file()
    bytes_content = await file_obj.download_as_bytearray()
    text = bytes_content.decode("utf-8", errors="ignore")

    user_id = update.effective_user.id

    try:
        last_scene = await import_story(user_id, text)
    except ValueError as e:
        await update.message.reply_text(f"❌ {e}")
        return
    except Exception as exc:
        log.exception("Import story gagal")
        await update.message.reply_text("❌ Terjadi error saat meng‑import story.")
        return

    # Tampilkan scene terakhir – **tidak dipotong**
    turn = last_scene["turn"]
    user_txt = last_scene["user"]
    ai_txt = last_scene["ai"]

    await update.message.reply_text(
        f"*✅ Story berhasil di‑import!*\n"
        f"*TURN {turn}*\n"
        f"*USER:* {user_txt}\n"
        f"*AI:* {ai_txt}",
        parse_mode="Markdown"
    )

# --------------------------------------------------------------
# Register ke Application
# --------------------------------------------------------------
def register_import(app):
    app.add_handler(CommandHandler("import", import_cmd))
    app.add_handler(
        MessageHandler(filters.Document.FileExtension("txt"), handle_import_file)
    )
