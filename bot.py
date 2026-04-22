import os
import asyncio
import io
import requests
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from motor.motor_asyncio import AsyncIOMotorClient
from google import genai
from bson import ObjectId

# ========= CONFIG & DATABASE =========
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
client_ai = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
# Menggunakan model flash untuk kecepatan respons
MODELS = ["gemini-3.1-flash-lite-preview", "gemini-2.5-flash"]

client_db = AsyncIOMotorClient(os.getenv("MONGO_URL"))
db = client_db.game_db
users = db.user_states
archives = db.archives 

# ========= DATABASE UTILITY =========
async def get_state(uid):
    s = await users.find_one({"_id": uid})
    if not s: s = {}
    state = {
        "_id": uid,
        "name": s.get("name") or "Bayu",
        "referensi": s.get("referensi") or "Belum ada plot.",
        "desc_utama": s.get("desc_utama") or "Tokoh Utama",
        "step": s.get("step"),
        "history": s.get("history", []),
        "chars": s.get("chars", []),
        "selected": s.get("selected", -1), # -1 adalah Tokoh Utama
        "last_prompt": s.get("last_prompt"),
        "last_system": s.get("last_system")
    }
    await users.update_one({"_id": uid}, {"$set": state}, upsert=True)
    return state

async def save(uid, data):
    await users.update_one({"_id": uid}, {"$set": data}, upsert=True)

# ========= AI ENGINE (STRICT POV) =========
async def generate(prompt, system, history):
    # Membatasi history agar konteks tetap tajam dan hemat token
    context = "\n---\n".join(history[-12:]) if history else "Mulai cerita."
    full_input = f"{system}\n\n[MEMORI CERITA]\n{context}\n\n[AKSI SEKARANG]\n{prompt}"
    for m in MODELS:
        try:
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(None, lambda: client_ai.models.generate_content(model=m, contents=full_input))
            return resp.text.strip(), m
        except: continue
    return None, None

def build_system(target_name, desc, referensi, role_type="NPC"):
    """
    role_type: 'UTAMA', 'NPC', atau 'NARATOR'
    """
    if role_type == "UTAMA":
        pov_instruction = f"Kamu adalah {target_name}. Gunakan kata ganti 'Aku' untuk dirimu sendiri."
    elif role_type == "NARATOR":
        pov_instruction = "Kamu adalah Narator/Dunia. Ceritakan kejadian secara objektif atau deskriptif."
    else: # NPC
        pov_instruction = f"Kamu adalah {target_name}. JANGAN gunakan 'Aku'. Sebut dirimu selalu dengan nama '{target_name}'."

    return f"""Kamu RPG Engine yang disiplin. 
REFERENSI DUNIA: {referensi}.
ROLE SAAT INI: {pov_instruction}.
DESKRIPSI KARAKTER: {desc}.

ATURAN:
1. Dialog menggunakan tanda kutip ("...").
2. Narasi aksi menggunakan tanda kurung dan miring (*...*).
3. MAKSIMAL 3 PARAGRAF per respons.
4. Jangan mengambil keputusan untuk karakter lain."""

# ========= UI MENU BUILDER =========
async def menu_utama(uid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📜 Karakter", callback_data="list_all"), InlineKeyboardButton("📝 Edit Plot", callback_data="edit_ref")],
        [InlineKeyboardButton("🎭 Narator", callback_data="step_narator"), InlineKeyboardButton("⏩ Lanjut", callback_data="lanjut")],
        [InlineKeyboardButton("💾 Simpan", callback_data="save_manual"), InlineKeyboardButton("📂 Muat", callback_data="load_list")],
        [InlineKeyboardButton("🔄 Regen", callback_data="regen"), InlineKeyboardButton("↩️ Undo", callback_data="undo")]
    ])

async def safe_send(obj, text, tag, markup):
    target = obj.message if hasattr(obj, "message") else obj.effective_message
    header = f"🎭 **{tag}**"
    try: await target.reply_text(f"{header}\n\n{text}", parse_mode="Markdown", reply_markup=markup)
    except: await target.reply_text(f"{header}\n\n{text}", reply_markup=markup)

# ========= MESSAGE HANDLERS =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await save(uid, {"step": "set_referensi", "history": [], "chars": []})
    await update.message.reply_text("🎮 RPG Engine Siap.\n\nMasukkan Referensi Plot & Nama Tokoh Utama (Contoh: Cerita Kerajaan, Tokoh: Bayu):")

async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id; text = update.message.text; s = await get_state(uid)

    if s["step"] == "set_referensi":
        await save(uid, {"referensi": text, "step": None})
        await update.message.reply_text("✅ Plot Disimpan. Gunakan menu di bawah untuk mulai.", reply_markup=await menu_utama(uid))
        return

    if s["step"] == "save_name_input":
        await archives.insert_one({
            "user_id": uid, "save_name": text, "history": s["history"], 
            "referensi": s["referensi"], "chars": s["chars"], "date": datetime.now()
        })
        await save(uid, {"step": None})
        await update.message.reply_text(f"💾 Slot '**{text}**' berhasil disimpan!", reply_markup=await menu_utama(uid))
        return

    if s["step"] == "updating_referensi":
        await save(uid, {"referensi": text, "step": None})
        await update.message.reply_text("✅ Referensi plot telah diperbarui.", reply_markup=await menu_utama(uid))
        return

    if s["step"] == "char_name":
        await save(uid, {"temp_char": text, "step": "char_desc"})
        await update.message.reply_text(f"Masukkan deskripsi/sifat untuk {text}:")
        return

    if s["step"] == "char_desc":
        s["chars"].append({"name": s["temp_char"], "desc": text})
        await save(uid, {"chars": s["chars"], "step": None})
        await update.message.reply_text(f"✅ Karakter {s['temp_char']} berhasil ditambah.", reply_markup=await menu_utama(uid))
        return

    if s["step"] in ["action", "narator_input"]:
        if s["step"] == "narator_input":
            tag, desc, r_type = "NARASI", "Dunia cerita", "NARATOR"
        else:
            idx = s["selected"]
            is_u = (idx == -1)
            tag = s["name"] if is_u else s["chars"][idx]["name"]
            desc = s["desc_utama"] if is_u else s["chars"][idx]["desc"]
            r_type = "UTAMA" if is_u else "NPC"

        sys = build_system(tag, desc, s["referensi"], r_type)
        prompt = f"{tag} melakukan aksi: {text}"
        out, _ = await generate(prompt, sys, s["history"])
        if out:
            s["history"].append(f"[{tag}]: {out}")
            await save(uid, {"history": s["history"], "step": None, "last_prompt": prompt, "last_system": sys})
            await safe_send(update, out, tag, await menu_utama(uid))

# ========= CALLBACK HANDLERS =========
async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; uid = q.from_user.id; s = await get_state(uid); await q.answer()

    if q.data == "main_menu":
        await q.edit_message_text("Menu Utama:", reply_markup=await menu_utama(uid))

    elif q.data == "list_all":
        kb = [[InlineKeyboardButton(f"🌟 {s['name']} (Utama)", callback_data="sel_-1")]]
        for i, c in enumerate(s["chars"]): kb.append([InlineKeyboardButton(f"👥 {c['name']}", callback_data=f"sel_{i}")])
        kb.append([InlineKeyboardButton("➕ Tambah NPC", callback_data="add_npc"), InlineKeyboardButton("⬅️ Menu", callback_data="main_menu")])
        await q.edit_message_text("Pilih Karakter untuk kontrol:", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("sel_"):
        idx = int(q.data.split("_")[1])
        name = s["name"] if idx == -1 else s["chars"][idx]["name"]
        await save(uid, {"selected": idx, "step": "action"})
        await q.message.reply_text(f"🕹️ Mode Kontrol: **{name}**\nKetik aksi yang ingin dilakukan:")

    elif q.data == "add_npc":
        await save(uid, {"step": "char_name"})
        await q.message.reply_text("Siapa nama NPC baru ini?")

    elif q.data == "save_manual":
        await save(uid, {"step": "save_name_input"})
        await q.message.reply_text("Masukkan nama untuk slot simpanan ini:")

    elif q.data == "load_list":
        cursor = archives.find({"user_id": uid}).sort("date", -1)
        items = await cursor.to_list(10)
        if not items:
            await q.message.reply_text("📂 Tidak ada data simpanan ditemukan.")
            return
        kb = [[InlineKeyboardButton(f"📖 {i['save_name']}", callback_data=f"load:{str(i['_id'])}")] for i in items]
        kb.append([InlineKeyboardButton("⬅️ Menu", callback_data="main_menu")])
        await q.edit_message_text("Pilih Slot untuk dimuat:", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("load:"):
        sid = q.data.split(":")[1]
        data = await archives.find_one({"_id": ObjectId(sid)})
        if data:
            h = data.get("history", [])
            await save(uid, {"history": h, "chars": data.get("chars", []), "referensi": data.get("referensi", ""), "step": None})
            preview = "\n\n".join(h[-2:]) if h else "Data kosong."
            await q.message.reply_text(f"✅ Berhasil Memuat Slot.\n\n{preview[-1500:]}", reply_markup=await menu_utama(uid))

    elif q.data == "regen":
        if not s["history"] or not s["last_prompt"]:
            await q.message.reply_text("⚠️ Tidak ada aksi terakhir untuk diulang.")
            return
        s["history"].pop(); await q.message.reply_text("🔄 Menghasilkan ulang respons...")
        out, _ = await generate(s["last_prompt"], s["last_system"], s["history"])
        if out:
            tag = s["last_prompt"].split(" melakukan")[0]
            s["history"].append(f"[{tag}]: {out}"); await save(uid, {"history": s["history"]})
            await safe_send(q, out, tag, await menu_utama(uid))

    elif q.data == "undo":
        if s["history"]:
            s["history"].pop(); await save(uid, {"history": s["history"]})
            await q.message.reply_text("↩️ Pesan terakhir dihapus dari riwayat.")

    elif q.data == "edit_ref":
        await save(uid, {"step": "updating_referensi"})
        await q.message.reply_text("Masukkan referensi plot/dunia yang baru:")

    elif q.data == "step_narator":
        await save(uid, {"step": "narator_input"})
        await q.message.reply_text("Gunakan Narator untuk mendeskripsikan kejadian lingkungan (Contoh: Tiba-tiba hujan badai datang):")

    elif q.data == "lanjut":
        sys = build_system("NARASI", "Dunia", s["referensi"], "NARATOR")
        out, _ = await generate("Lanjutkan alur cerita secara natural.", sys, s["history"])
        if out:
            s["history"].append(f"[NARASI]: {out}")
            await save(uid, {"history": s["history"], "last_prompt": "Lanjutkan alur.", "last_system": sys})
            await safe_send(q, out, "NARASI", await menu_utama(uid))

# ========= MAIN EXECUTION =========
if __name__ == "__main__":
    # Bersihkan koneksi lama sebelum jalan
    try: requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook?drop_pending_updates=true", timeout=5)
    except: pass
    
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))
    
    print("RPG Bot Engine is running...")
    app.run_polling(drop_pending_updates=True)
