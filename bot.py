import os
import asyncio
import io
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from motor.motor_asyncio import AsyncIOMotorClient
from google import genai
from datetime import datetime
from bson import ObjectId

# ========= CONFIG =========
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
client_ai = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODELS = ["gemini-3.1-flash-lite-preview", "gemini-2.5-flash", "gemini-2.5-pro"]

client_db = AsyncIOMotorClient(os.getenv("MONGO_URL"))
db = client_db.game_db
users = db.user_states
archives = db.archives 

# ========= DATABASE =========
def fix_state(s):
    if not s: s = {}
    return {
        "_id": s.get("_id"),
        "name": s.get("name") or "Bayu", # Default nama Utama
        "referensi": s.get("referensi") or "Belum ada referensi.",
        "desc_utama": s.get("desc_utama") or "Tokoh Utama",
        "step": s.get("step"),
        "history": s.get("history", []),
        "chars": s.get("chars", []),
        "selected": s.get("selected", -1), # -1 adalah Tokoh Utama
        "last_prompt": s.get("last_prompt"),
        "last_system": s.get("last_system"),
        "temp_char": s.get("temp_char")
    }

async def get_state(uid):
    s = await users.find_one({"_id": uid})
    s = fix_state(s)
    await users.update_one({"_id": uid}, {"$set": s}, upsert=True)
    return s

async def save(uid, data):
    await users.update_one({"_id": uid}, {"$set": data}, upsert=True)

# ========= AI ENGINE (CORE POV FIX) =========
async def generate(prompt, system, history):
    context = "\n---\n".join(history[-12:]) if history else "Mulai."
    full_input = f"{system}\n\n[MEMORI TERBARU]\n{context}\n\n[AKSI SEKARANG]\n{prompt}"
    for m in MODELS:
        try:
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(
                None, lambda: client_ai.models.generate_content(model=m, contents=full_input)
            )
            return resp.text.strip(), m
        except: continue
    return None, None

def build_system(target_name, desc, referensi, is_utama=True):
    """
    Kunci utama perbaikan POV:
    - Jika Tokoh Utama: Pakai 'Aku'.
    - Jika NPC: Pakai Nama mereka sendiri (Maya, dsb) untuk menyebut diri sendiri.
    """
    role_play_rule = ""
    if is_utama:
        role_play_rule = f"Kamu adalah {target_name} (Tokoh Utama). Gunakan kata ganti 'Aku' untuk dirimu sendiri."
    else:
        role_play_rule = f"Kamu adalah {target_name} (NPC). JANGAN gunakan 'Aku'. Sebut dirimu sebagai '{target_name}'."

    return f"""Kamu RPG Engine. REFERENSI DUNIA: {referensi}.
ATURAN POV: {role_play_rule}. Deskripsi: {desc}.

GAYA BAHASA:
1. Interaksi sangat spesifik sebagai {target_name}.
2. Dialog pakai tanda kutip "...". Narasi aksi pakai tanda kurung bintang *(...)*.
3. Maksimal 3 paragraf. 
4. Jika {target_name} bereaksi terhadap orang lain, sebut nama mereka.
5. JANGAN menggerakkan atau mengambil keputusan untuk karakter lain."""

# ========= UI MENU =========
async def menu_utama(uid):
    kb = [
        [InlineKeyboardButton("📜 Karakter", callback_data="list_all")],
        [InlineKeyboardButton("📝 Edit Plot", callback_data="edit_ref")],
        [InlineKeyboardButton("🎭 Narator", callback_data="step_narator"),
         InlineKeyboardButton("⏩ Lanjut", callback_data="lanjut")],
        [InlineKeyboardButton("💾 Simpan", callback_data="save_manual"),
         InlineKeyboardButton("📂 Muat", callback_data="load_list")],
        [InlineKeyboardButton("🔄 Regen", callback_data="regen"),
         InlineKeyboardButton("↩️ Undo", callback_data="undo")]
    ]
    return InlineKeyboardMarkup(kb)

async def safe_send(obj, text, tag, markup):
    target = obj.message if hasattr(obj, "message") else obj.effective_message
    try: await target.reply_text(f"🎭 **{tag}**\n\n{text}", parse_mode="Markdown", reply_markup=markup)
    except: await target.reply_text(f"🎭 {tag}\n\n{text}", reply_markup=markup)

# ========= HANDLERS =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await save(update.effective_user.id, {"step": "set_referensi", "history": [], "chars": []})
    await update.message.reply_text("🎮 RPG Engine Siap.\n\nMasukkan Referensi Plot & Nama Tokoh Utama (Contoh: Bayu):")

async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id; text = update.message.text; s = await get_state(uid)

    if s["step"] == "set_referensi":
        await save(uid, {"referensi": text, "step": None})
        await update.message.reply_text("✅ Referensi disimpan. Klik Menu Karakter untuk mulai aksi.")
        return

    if s["step"] in ["action", "narator_input"]:
        idx = s.get("selected", -1)
        is_utama = (idx == -1)
        
        # Penentuan Nama & Role
        tag = s["name"] if is_utama else s["chars"][idx]["name"]
        desc = s["desc_utama"] if is_utama else s["chars"][idx]["desc"]
        
        sys = build_system(tag, desc, s["referensi"], is_utama)
        prompt = f"{tag} melakukan: {text}"
        
        out, _ = await generate(prompt, sys, s["history"])
        if out:
            formatted_msg = f"[{tag}]: {out}"
            s["history"].append(formatted_msg)
            await save(uid, {"history": s["history"], "step": None, "last_prompt": prompt, "last_system": sys})
            await safe_send(update, out, tag, await menu_utama(uid))

# ========= CALLBACK (FIXED POV) =========
async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; uid = q.from_user.id; s = await get_state(uid); await q.answer()

    if q.data == "list_all":
        kb = [[InlineKeyboardButton(f"🌟 {s['name']} (Utama)", callback_data="sel_-1")]]
        for i, c in enumerate(s["chars"]): kb.append([InlineKeyboardButton(f"👥 {c['name']}", callback_data=f"sel_{i}")])
        kb.append([InlineKeyboardButton("➕ Tambah NPC", callback_data="add_new"), InlineKeyboardButton("⬅️ Menu", callback_data="main_menu")])
        await q.edit_message_text("Pilih siapa yang beraksi:", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("sel_"):
        idx = int(q.data.split("_")[1])
        name = s["name"] if idx == -1 else s["chars"][idx]["name"]
        await save(uid, {"selected": idx, "step": "action"})
        await q.message.reply_text(f"🕹️ Sekarang mengontrol: **{name}**\n\nKetik aksinya:")

    elif q.data == "regen":
        if not s.get("last_prompt") or not s["history"]: return
        s["history"].pop(); await q.message.reply_text("🔄 Mengulang...")
        out, _ = await generate(s["last_prompt"], s["last_system"], s["history"])
        if out:
            tag = s["last_prompt"].split(" melakukan")[0]
            s["history"].append(f"[{tag}]: {out}"); await save(uid, {"history": s["history"]}); await safe_send(q, out, tag, await menu_utama(uid))

    elif q.data.startswith("load:"):
        slot_id = q.data.split(":")[1]
        data = await archives.find_one({"_id": ObjectId(slot_id)})
        if data:
            h = data.get("history", [])
            await save(uid, {"history": h, "chars": data.get("chars", []), "referensi": data.get("referensi", ""), "step": None})
            preview = "\n\n".join(h[-2:]) if h else "Kosong."
            await q.message.reply_text(f"✅ Load Berhasil.\n\n{preview[-2000:]}", reply_markup=await menu_utama(uid))

    elif q.data == "lanjut":
        sys = build_system("NARASI", "Narator", s["referensi"], False)
        out, _ = await generate("Lanjutkan cerita secara natural.", sys, s["history"])
        if out:
            s["history"].append(f"[NARASI]: {out}")
            await save(uid, {"history": s["history"], "last_prompt": "Lanjutkan.", "last_system": sys})
            await safe_send(q, out, "NARASI", await menu_utama(uid))

    elif q.data == "undo":
        if s["history"]: s["history"].pop(); await save(uid, {"history": s["history"]}); await q.message.reply_text("↩️ Terhapus.")
    elif q.data == "main_menu": await q.edit_message_text("Menu Utama:", reply_markup=await menu_utama(uid))
    elif q.data == "save_manual": await save(uid, {"step": "save_name_input"}); await q.message.reply_text("Nama slot?")
    elif q.data == "load_list":
        cursor = archives.find({"user_id": uid}).sort("_id", -1); items = await cursor.to_list(10)
        if not items: await q.message.reply_text("Kosong."); return
        kb = [[InlineKeyboardButton(f"📖 {i['save_name']}", callback_data=f"load:{str(i['_id'])}")] for i in items]
        await q.edit_message_text("Pilih Slot:", reply_markup=InlineKeyboardMarkup(kb))

if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start)); app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg)); app.run_polling()
