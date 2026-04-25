import os
import asyncio
import io
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from motor.motor_asyncio import AsyncIOMotorClient
from google import genai
from datetime import datetime

# ========= CONFIG =========
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
client_ai = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODELS = ["gemini-3.1-flash-lite-preview", "gemini-2.5-flash", "gemini-2.5-pro"]

client_db = AsyncIOMotorClient(os.getenv("MONGO_URL"))
db = client_db.game_db
users = db.user_states
archives = db.archives 

# ========= DATABASE (DENGAN RELATIONSHIP) =========
def fix_state(s):
    if not s: s = {}
    return {
        "_id": s.get("_id"),
        "name": s.get("name"),
        "desc_utama": s.get("desc_utama") or "Tokoh Utama",
        "step": s.get("step"),
        "history": s.get("history", []),
        "chars": s.get("chars", []), # Tiap char punya 'name', 'desc', 'rel'
        "selected": s.get("selected", -1),
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

# ========= AI SYSTEM =========
def build_romcom_system(tag, desc, rel="Awkward"):
    return f"""
Kamu adalah penulis Novel Visual RomCom. 
PERAN: {tag} ({desc}). Status Hubungan: {rel}.
ATURAN: 
1. Fokus pada interaksi RomCom (manis/lucu/awkward). 
2. DILARANG HOROR/Misteri. 
3. Panjang MAKSIMAL 2 paragraf. 
4. Di akhir cerita, jika memungkinkan, berikan 4 pilihan aksi (A, B, C, D) dengan format:
A. [Pilihan A]
B. [Pilihan B]
C. [Pilihan C]
D. [Pilihan D]
"""

async def generate(prompt, system, history):
    context = ""
    if len(history) >= 2:
        context = "[KONTEKS]\n" + "\n---\n".join(history[-2:]) + "\n---\n"
    elif history:
        context = "[KONTEKS]\n" + history[-1] + "\n---\n"
    
    full_input = f"{system}\n\n{context}\n[AKSI]\n{prompt}"
    for m in MODELS:
        try:
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(None, lambda: client_ai.models.generate_content(model=m, contents=full_input))
            return resp.text.strip(), m
        except: continue
    return None, None

# ========= UI & SEND =========
async def menu_utama(uid):
    kb = [
        [InlineKeyboardButton("📜 Karakter", callback_data="list_all")],
        [InlineKeyboardButton("🎭 Narator", callback_data="step_narator"), InlineKeyboardButton("⏩ Lanjut", callback_data="lanjut")],
        [InlineKeyboardButton("💾 Save", callback_data="save_manual"), InlineKeyboardButton("📂 Load", callback_data="load_list")],
        [InlineKeyboardButton("↩️ Undo", callback_data="undo"), InlineKeyboardButton("🔄 Regen", callback_data="regen")],
        [InlineKeyboardButton("🧹 Reset", callback_data="reset_confirm")]
    ]
    return InlineKeyboardMarkup(kb)

async def safe_send(obj, text, prev, tag, markup):
    target = obj.message if hasattr(obj, "message") else obj.effective_message
    header = f"✨ *{tag}*\n\n"
    ctx = f"_[Sebelumnya]_\n{prev[:500]}...\n\n━━━━━━━━━━\n\n" if prev else ""
    final = (ctx + header + text)[:4000]
    try: await target.reply_text(final, parse_mode="Markdown", reply_markup=markup)
    except: await target.reply_text(final, reply_markup=markup)

# ========= HANDLERS =========
async def start(update, context):
    uid = update.effective_user.id
    await save(uid, {"name": None, "step": "set_name", "history": [], "chars": []})
    await update.message.reply_text("🎮 RPG RomCom\n\nMasukkan nama karakter utama:")

async def msg(update, context):
    uid = update.effective_user.id; text = update.message.text; s = await get_state(uid)

    if s["step"] == "set_name":
        await save(uid, {"name": text.capitalize(), "step": None})
        await update.message.reply_text(f"🔥 Welcome {text.capitalize()}!", reply_markup=await menu_utama(uid)); return

    # LOGIKA PILIHAN A B C D (WAJIB ADA)
    if s["history"] and ("pilihan" in s["history"][-1].lower() or "lakukan?" in s["history"][-1].lower()):
        if re.match(r'^[a-dA-D]$', text.strip()):
            idx = s.get("selected", -1)
            tag = s["name"] if idx == -1 else s["chars"][idx]["name"]
            rel = "Main" if idx == -1 else s["chars"][idx].get("rel", "Awkward")
            sys = build_romcom_system(tag, s["desc_utama"] if idx == -1 else s["chars"][idx]["desc"], rel)
            prompt = f"User memilih opsi {text.upper()}. Lanjutkan cerita romcom."
            out, _ = await generate(prompt, sys, s["history"])
            if out:
                prev = s["history"][-1]
                s["history"].append(f"[{tag}]: {out}")
                await save(uid, {"history": s["history"], "last_prompt": prompt, "last_system": sys})
                await safe_send(update, out, prev, tag, await menu_utama(uid))
            return

    # EDIT PROSES
    if s["step"] and s["step"].startswith("editname_"):
        idx = int(s["step"].split("_")[1])
        await save(uid, {"temp_char": text, "step": f"editdesc_{idx}"})
        await update.message.reply_text(f"Nama: {text}. Masukkan Deskripsi:"); return
    
    if s["step"] and s["step"].startswith("editdesc_"):
        idx = int(s["step"].split("_")[1])
        if idx == -1: s["name"], s["desc_utama"] = s["temp_char"], text
        else: s["chars"][idx]["name"], s["chars"][idx]["desc"] = s["temp_char"], text
        await save(uid, {"name": s["name"], "desc_utama": s["desc_utama"], "chars": s["chars"], "step": None, "temp_char": None})
        await update.message.reply_text("✅ Updated!", reply_markup=await menu_utama(uid)); return

    # ACTION / INPUT BEBAS
    if s["step"] in ["action", "narator_input"]:
        idx = s.get("selected", -1)
        tag = "NARASI" if s["step"] == "narator_input" else (s["name"] if idx == -1 else s["chars"][idx]["name"])
        sys = build_romcom_system(tag, s["desc_utama"] if idx == -1 else s["chars"][idx]["desc"])
        prompt = f"Aksi: {text}"
        out, _ = await generate(prompt, sys, s["history"])
        if out:
            prev = s["history"][-1] if s["history"] else ""
            s["history"].append(f"[{tag}]: {out}")
            await save(uid, {"history": s["history"], "step": None, "last_prompt": prompt, "last_system": sys})
            await safe_send(update, out, prev, tag, await menu_utama(uid))
        return

    # SAVE SLOT NAME
    if s["step"] == "save_name":
        await archives.insert_one({"user_id": uid, "save_name": text, "history": s["history"], "chars": s["chars"], "name": s["name"], "desc_utama": s["desc_utama"]})
        await save(uid, {"step": None})
        await update.message.reply_text(f"✅ Saved as {text}", reply_markup=await menu_utama(uid)); return

# ========= CALLBACKS =========
async def callback(update, context):
    q = update.callback_query; uid = q.from_user.id; s = await get_state(uid); await q.answer()

    if q.data == "main_menu": await q.edit_message_text("Menu Utama:", reply_markup=await menu_utama(uid))
    
    elif q.data == "load_list":
        items = await archives.find({"user_id": uid}).sort("_id", -1).to_list(10)
        if not items: await q.message.reply_text(" Kosong."); return
        kb = [[InlineKeyboardButton(f"📖 {i['save_name']}", callback_data=f"load_{i['_id']}")] for i in items]
        await q.edit_message_text("Load Slot:", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("load_"):
        from bson import ObjectId
        data = await archives.find_one({"_id": ObjectId(q.data.split("_")[1])})
        if data:
            # FIX: Sinkronkan semua data ke state aktif
            await save(uid, {"history": data["history"], "chars": data.get("chars", []), "name": data["name"], "desc_utama": data.get("desc_utama", "Tokoh Utama"), "step": None})
            txt = data["history"][-1] if data["history"] else "Data dimuat."
            await q.message.reply_text(f"✅ LOAD SUCCESS\n\n{txt[:500]}...", reply_markup=await menu_utama(uid))

    elif q.data == "list_all":
        kb = [[InlineKeyboardButton(f"👤 {s['name']} (You)", callback_data="sel_-1")]]
        for i, c in enumerate(s["chars"]):
            rel = c.get("rel", "Awkward")
            kb.append([InlineKeyboardButton(f"👥 {c['name']} [{rel}]", callback_data=f"sel_{i}")])
        kb.append([InlineKeyboardButton("➕ NPC", callback_data="add_npc"), InlineKeyboardButton("⬅️ Menu", callback_data="main_menu")])
        await q.edit_message_text("📜 Karakter & Relationship:", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("sel_"):
        idx = int(q.data.split("_")[1]); await save(uid, {"selected": idx})
        name = s["name"] if idx == -1 else s["chars"][idx]["name"]
        rel = "Master" if idx == -1 else s["chars"][idx].get("rel", "Awkward")
        kb = [[InlineKeyboardButton("🎬 New Story", callback_data=f"new_{idx}"), InlineKeyboardButton("🎮 Aksi", callback_data=f"act_{idx}")],
              [InlineKeyboardButton("📝 Edit", callback_data=f"edit_{idx}"), InlineKeyboardButton("❤️ Set Rel", callback_data=f"rel_{idx}")],
              [InlineKeyboardButton("⬅️ Back", callback_data="list_all")]]
        await q.edit_message_text(f"Target: {name}\nStatus: {rel}", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("rel_") and not q.data.startswith("rel_set_"):
        idx = q.data.split("_")[1]
        kb = [[InlineKeyboardButton(r, callback_data=f"rel_set_{idx}_{r}")] for r in ["Awkward", "Friendzone", "Crush", "In Love", "Enemy"]]
        await q.edit_message_text("Set Relationship Status:", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("rel_set_"):
        _, _, idx, val = q.data.split("_"); idx = int(idx)
        if idx != -1: s["chars"][idx]["rel"] = val
        await save(uid, {"chars": s["chars"]})
        await q.message.reply_text(f"✅ Status updated to {val}", reply_markup=await menu_utama(uid))

    elif q.data == "lanjut":
        idx = s.get("selected", -1); tag = s["name"] if idx == -1 else s["chars"][idx]["name"]
        rel = "Main" if idx == -1 else s["chars"][idx].get("rel", "Awkward")
        sys = build_romcom_system(tag, s["desc_utama"] if idx == -1 else s["chars"][idx]["desc"], rel)
        out, _ = await generate("Lanjutkan cerita RomCom.", sys, s["history"])
        if out:
            prev = s["history"][-1] if s["history"] else ""
            s["history"].append(f"[{tag}]: {out}")
            await save(uid, {"history": s["history"], "last_prompt": "Lanjut", "last_system": sys})
            await safe_send(q, out, prev, tag, await menu_utama(uid))

    elif q.data == "undo" and s["history"]:
        s["history"].pop(); await save(uid, {"history": s["history"]})
        await q.message.reply_text("↩️ Undone.", reply_markup=await menu_utama(uid))

    elif q.data == "regen" and s.get("last_prompt"):
        s["history"].pop(); out, _ = await generate(s["last_prompt"], s["last_system"], s["history"])
        if out:
            tag = s["history"][-1].split("]: ")[0][1:] if s["history"] else s["name"]
            s["history"].append(f"[{tag}]: {out}"); await save(uid, {"history": s["history"]})
            await safe_send(q, out, "", tag, await menu_utama(uid))

    elif q.data.startswith("edit_"):
        await save(uid, {"step": f"editname_{q.data.split('_')[1]}"})
        await q.message.reply_text("Input Nama Baru:")
    elif q.data.startswith("act_"):
        await save(uid, {"step": "action"}); await q.message.reply_text("Apa aksimu?")
    elif q.data == "step_narator":
        await save(uid, {"step": "narator_input"}); await q.message.reply_text("Kejadian apa?")
    elif q.data == "save_manual":
        await save(uid, {"step": "save_name"}); await q.message.reply_text("Nama Slot?")
    elif q.data == "reset_confirm":
        await save(uid, {"name": None, "history": [], "chars": [], "step": "set_name"})
        await q.message.reply_text("🧹 Reset! Nama baru?")

# ========= RUN =========
if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))
    print("🔥 RPG BOT FIXED - NO MORE EXPERIMENTS!")
    app.run_polling(drop_pending_updates=True)
