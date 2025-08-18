import os
import logging
import threading
import time
import requests
from fastapi import FastAPI
import uvicorn
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
from dotenv import load_dotenv

# Configuración inicial
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
MODERATION_GROUP_ID = os.getenv("MODERATION_GROUP_ID")
PUBLIC_CHANNEL = os.getenv("PUBLIC_CHANNEL")
RENDER_APP_URL = os.getenv("RENDER_APP_URL")  # Ej: https://tudominio.onrender.com

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

app = FastAPI()
pending_confessions = {}

# Handlers del bot
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hola 👋 Envíame tu confesión en texto.")

async def handle_non_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚠️ Solo acepto texto.")

async def handle_confession(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        return
    
    user_id = update.message.from_user.id
    confession = update.message.text
    
    confession_id = abs(hash(f"{user_id}{confession}")) % (10**8)
    pending_confessions[confession_id] = {"text": confession, "user_id": user_id}
    
    keyboard = [[
        InlineKeyboardButton("✅ Aprobar", callback_data=f"approve_{confession_id}"),
        InlineKeyboardButton("❌ Rechazar", callback_data=f"reject_{confession_id}")
    ]]
    
    await context.bot.send_message(
        chat_id=MODERATION_GROUP_ID,
        text=f"📝 Nueva confesión (ID: {confession_id}):\n\n{confession}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    await update.message.reply_text("✋ Tu confesión ha sido enviada a moderación.")

async def handle_moderation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    confession_id = int(query.data.split("_")[1])
    
    if confession_id not in pending_confessions:
        await query.edit_message_text("⚠️ Esta confesión ya fue procesada.")
        return
    
    confession_data = pending_confessions[confession_id]
    
    if "approve" in query.data:
        await context.bot.send_message(
            chat_id=PUBLIC_CHANNEL,
            text=f"📢 Confesión anónima:\n\n{confession_data['text']}"
        )
        try:
            await context.bot.send_message(
                chat_id=confession_data["user_id"],
                text="🎉 Tu confesión ha sido aprobada y publicada."
            )
        except Exception:
            pass
        await query.edit_message_text(f"✅ Confesión {confession_id} aprobada")
    else:
        try:
            await context.bot.send_message(
                chat_id=confession_data["user_id"],
                text="❌ Tu confesión no cumple con nuestras normas."
            )
        except Exception:
            pass
        await query.edit_message_text(f"❌ Confesión {confession_id} rechazada")
    
    del pending_confessions[confession_id]

# Keep-Alive para Render
def keep_alive():
    while True:
        try:
            requests.get(RENDER_APP_URL)
            logging.info("Keep-Alive: Ping enviado a Render")
        except Exception as e:
            logging.error(f"Keep-Alive error: {e}")
        time.sleep(300)  # Ping cada 5 minutos

# Inicialización
def run_bot():
    bot_app = ApplicationBuilder().token(TOKEN).build()
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_confession))
    bot_app.add_handler(MessageHandler(~filters.TEXT & ~filters.COMMAND, handle_non_text))
    bot_app.add_handler(CallbackQueryHandler(handle_moderation))
    bot_app.run_polling()

@app.get("/")
def home():
    return {"status": "Bot activo"}

if __name__ == "__main__":
    threading.Thread(target=keep_alive, daemon=True).start()
    threading.Thread(target=run_bot, daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=10000)