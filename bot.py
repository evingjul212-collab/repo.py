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
        "referensi": s.get("referensi") or "",
        "desc_utama": s.get("desc_utama") or "Tokoh Utama",
        "step": s.get("step"),
        "history": s.get("history", []),
        "chars": s.get("chars", []),
        "selected": s.get("selected", -1),
        "last_prompt": s.get("last_prompt"),
        "last_system": s.get("last_system")
    }
    return state

async def save(uid, data):
    await users.update_one({"_id": uid}, {"$set": data}, upsert=True)

# ========= AI ENGINE (STRICT POV) =========
async def generate(prompt, system, history):
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
    if role_type == "UTAMA":
        pov = f"Kamu adalah {target_name} (Tokoh Utama). Gunakan kata ganti 'Aku'!"
    elif role_type == "NARATOR":
        pov = "Kamu adalah Narator/Dunia. Ceritakan secara deskriptif."
    else:
        pov = f"Kamu adalah {target_name} (NPC). JANGAN gunakan 'Aku', sebut dirimu '{target_name}'."

    return f"""Kamu RPG Engine. Plot Dunia: {referensi}.
Role Kamu: {pov}. Deskripsi: {desc}.
Aturan: Dialog "...". Narasi *(...)*. Max 3 paragraf."""

# ========= UI MENU =========
async def menu_utama(uid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📜 Karakter", callback_data="list_all"), InlineKeyboardButton("📝 Edit Plot", callback_data="edit_ref")],
        [InlineKeyboardButton("🎭 Narator", callback_data="step_narator"), InlineKeyboardButton("⏩ Lanjut", callback_data="lanjut")],
        [InlineKeyboardButton("💾 Simpan", callback_data="save_manual"), InlineKeyboardButton("📂 Muat", callback_data="load_list")],
        [InlineKeyboardButton("📖 Riwayat", callback_data="export_logs"), InlineKeyboardButton("🔄 Regen", callback_data="regen")],
        [InlineKeyboardButton("↩️ Undo", callback_data="undo"), InlineKeyboardButton("🧹 Reset", callback_data="reset_confirm")]
    ])

async def safe_send(obj, text, tag, markup):
    target = obj.message if hasattr(obj, "message") else obj.effective_message
    try: await target.reply_text(f"✨ **{tag}**\n\n{text}", parse_mode="Markdown", reply_markup=markup)
    except: await target.reply_text(f"✨ {tag}\n\n{text}", reply_markup=markup)

# ========= HANDLERS =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await save(uid, {"step": "set_referensi", "history": [], "chars": [], "referensi": ""})
    await update.message.reply_text("🎮 RPG Engine Siap.\n\nMasukkan Referensi Plot & Nama Tokoh Utama (Contoh: Cerita Kerajaan, Tokoh: Bayu):")

async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id; text = update.message.text; s = await get_state(uid)

    # AUTO GENERATE SETELAH INPUT PLOT PERTAMA
    if s["step"] == "set_referensi":
        # Coba ambil nama tokoh dari input (asumsi format "Tokoh: Nama")
        name = "Bayu"
        if "Tokoh:" in text: name = text.split("Tokoh:")[1].strip().split()[0]
        
        await save(uid, {"referensi": text, "name": name, "step": None})
        await update.message.reply_text(f"✅ Plot & Tokoh {name} disimpan. Memulai cerita...")
        
        # Langsung Generate Narasi Awal
        sys = build_system("NARASI", "Dunia Cerita", text, "NARATOR")
        out, _ = await generate("Mulai cerita dari awal berdasarkan plot.", sys, [])
        if out:
            s["history"].append(f"[NARASI]: {out}")
            await save(uid, {"history": s["history"], "last_system": sys, "last_prompt": "Mulai cerita."})
            await safe_send(update, out, "NARASI", await menu_utama(uid))
        return

    if s["step"] == "save_name_input":
        await archives.insert_one({"user_id": uid, "save_name": text, "history": s["history"], "referensi": s["referensi"], "chars": s["chars"], "date": datetime.now()})
        await save(uid, {"step": None})
        await update.message.reply_text(f"💾 Tersimpan: {text}", reply_markup=await menu_utama(uid))
        return

    if s["step"] == "updating_referensi":
        await save(uid, {"referensi": text, "step": None})
        await update.message.reply_text("✅ Referensi Plot diperbarui.", reply_markup=await menu_utama(uid))
        return

    if s["step"] == "char_name":
        await save(uid, {"temp_char": text, "step": "char_desc"})
        await update.message.reply_text(f"Deskripsi untuk {text}?"); return

    if s["step"] == "char_desc":
        s["chars"].append({"name": s["temp_char"], "desc": text})
        await save(uid, {"chars": s["chars"], "step": None})
        await update.message.reply_text(f"✅ NPC {s['temp_char']} aktif.", reply_markup=await menu_utama(uid)); return

    if s["step"] in ["action", "narator_input"]:
        idx = s["selected"]; is_u = (idx == -1)
        tag = s["name"] if is_u else s["chars"][idx]["name"]
        desc = s["desc_utama"] if is_u else s["chars"][idx]["desc"]
        r_type = "UTAMA" if is_u else "NPC"
        
        if s["step"] == "narator_input": tag, desc, r_type = "NARASI", "Dunia", "NARATOR"

        sys = build_system(tag, desc, s["referensi"], r_type)
        prompt = f"{tag} beraksi: {text}"
        out, _ = await generate(prompt, sys, s["history"])
        if out:
            s["history"].append(f"[{tag}]: {out}")
            await save(uid, {"history": s["history"], "step": None, "last_prompt": prompt, "last_system": sys})
            await safe_send(update, out, tag, await menu_utama(uid))

# ========= CALLBACK =========
async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; uid = q.from_user.id; s = await get_state(uid); await q.answer()

    if q.data == "export_logs":
        if not s["history"]: await q.message.reply_text("Riwayat kosong."); return
        txt = "RIWAYAT CERITA RPG\n\n" + "\n\n".join(s["history"])
        f = io.BytesIO(txt.encode()); f.name = "riwayat_cerita.txt"
        await context.bot.send_document(chat_id=uid, document=f, caption="📜 Seluruh isi cerita sejauh ini.")

    elif q.data == "edit_ref":
        await save(uid, {"step": "updating_referensi"})
        await q.message.reply_text(f"📝 **Plot Saat Ini:**\n\n`{s['referensi']}`\n\nSilakan masukkan Plot baru atau tambahkan detailnya:", parse_mode="Markdown")

    elif q.data == "list_all":
        kb = [[InlineKeyboardButton(f"🌟 {s['name']} (Utama)", callback_data="sel_-1")]]
        for i, c in enumerate(s["chars"]): kb.append([InlineKeyboardButton(f"👥 {c['name']}", callback_data=f"sel_{i}")])
        kb.append([InlineKeyboardButton("➕ Tambah NPC", callback_data="add_npc"), InlineKeyboardButton("⬅️ Menu", callback_data="main_menu")])
        await q.edit_message_text("Kontrol Karakter:", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("sel_"):
        idx = int(q.data.split("_")[1]); name = s["name"] if idx == -1 else s["chars"][idx]["name"]
        await save(uid, {"selected": idx, "step": "action"})
        await q.message.reply_text(f"🕹️ Mengontrol: **{name}**. Masukkan aksi:")

    elif q.data == "add_npc":
        await save(uid, {"step": "char_name"})
        await q.message.reply_text("Nama NPC?")

    elif q.data == "save_manual":
        await save(uid, {"step": "save_name_input"}); await q.message.reply_text("Nama Slot?")

    elif q.data == "load_list":
        cursor = archives.find({"user_id": uid}).sort("date", -1); items = await cursor.to_list(10)
        if not items: await q.message.reply_text("Tidak ada simpanan."); return
        kb = [[InlineKeyboardButton(f"📖 {i['save_name']}", callback_data=f"load:{str(i['_id'])}")] for i in items]
        await q.edit_message_text("Pilih Slot:", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("load:"):
        sid = q.data.split(":")[1]; data = await archives.find_one({"_id": ObjectId(sid)})
        if data:
            h = data.get("history", [])
            await save(uid, {"history": h, "chars": data.get("chars", []), "referensi": data.get("referensi", ""), "step": None})
            await q.message.reply_text(f"✅ Load Slot: {data['save_name']}", reply_markup=await menu_utama(uid))

    elif q.data == "regen":
        if not s["history"]: return
        s["history"].pop(); await q.message.reply_text("🔄 Mengulang..."); out, _ = await generate(s["last_prompt"], s["last_system"], s["history"])
        if out:
            tag = s["last_prompt"].split(" beraksi")[0]
            s["history"].append(f"[{tag}]: {out}"); await save(uid, {"history": s["history"]}); await safe_send(q, out, tag, await menu_utama(uid))

    elif q.data == "undo":
        if s["history"]: s["history"].pop(); await save(uid, {"history": s["history"]}); await q.message.reply_text("↩️ Undo Berhasil.")

    elif q.data == "main_menu": await q.edit_message_text("Menu Utama:", reply_markup=await menu_utama(uid))

    elif q.data == "step_narator":
        await save(uid, {"step": "narator_input"}); await q.message.reply_text("Narasi kejadian dunia?")

    elif q.data == "lanjut":
        sys = build_system("NARASI", "Dunia", s["referensi"], "NARATOR")
        out, _ = await generate("Lanjutkan cerita.", sys, s["history"])
        if out:
            s["history"].append(f"[NARASI]: {out}"); await save(uid, {"history": s["history"]}); await safe_send(q, out, "NARASI", await menu_utama(uid))

    elif q.data == "reset_confirm":
        await save(uid, {"history": [], "chars": [], "step": "set_referensi", "referensi": ""})
        await q.message.reply_text("🧹 Data direset. Masukkan Plot & Tokoh Baru:")

if __name__ == "__main__":
    try: requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook?drop_pending_updates=true", timeout=5)
    except: pass
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start)); app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))
    app.run_polling(drop_pending_updates=True)
