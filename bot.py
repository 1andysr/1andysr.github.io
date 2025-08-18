import os
import logging
import threading
import time
import requests
from fastapi import FastAPI
import uvicorn
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    Filters,
    CallbackContext
)
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
MODERATION_GROUP_ID = os.getenv("MODERATION_GROUP_ID")
PUBLIC_CHANNEL = os.getenv("PUBLIC_CHANNEL")
RENDER_APP_URL = os.getenv("RENDER_APP_URL")

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

app = FastAPI()
pending_confessions = {}

def start(update: Update, context: CallbackContext):
    update.message.reply_text("Hola 👋 Envíame tu confesión en texto.")

def handle_non_text(update: Update, context: CallbackContext):
    update.message.reply_text("⚠️ Solo acepto texto.")

def handle_confession(update: Update, context: CallbackContext):
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
    
    context.bot.send_message(
        chat_id=MODERATION_GROUP_ID,
        text=f"📝 Nueva confesión (ID: {confession_id}):\n\n{confession}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    update.message.reply_text("✋ Tu confesión ha sido enviada a moderación.")

def handle_moderation(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    confession_id = int(query.data.split("_")[1])
    
    if confession_id not in pending_confessions:
        query.edit_message_text("⚠️ Esta confesión ya fue procesada.")
        return
    
    confession_data = pending_confessions[confession_id]
    
    if "approve" in query.data:
        context.bot.send_message(
            chat_id=PUBLIC_CHANNEL,
            text=f"📢 Confesión anónima:\n\n{confession_data['text']}"
        )
        try:
            context.bot.send_message(
                chat_id=confession_data["user_id"],
                text="🎉 Tu confesión ha sido aprobada y publicada."
            )
        except Exception:
            pass
        query.edit_message_text(f"✅ Confesión {confession_id} aprobada")
    else:
        try:
            context.bot.send_message(
                chat_id=confession_data["user_id"],
                text="❌ Tu confesión no cumple con nuestras normas."
            )
        except Exception:
            pass
        query.edit_message_text(f"❌ Confesión {confession_id} rechazada")
    
    del pending_confessions[confession_id]

def run_bot():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_confession))
    dp.add_handler(MessageHandler(~Filters.text & ~Filters.command, handle_non_text))
    dp.add_handler(CallbackQueryHandler(handle_moderation))
    
    updater.start_polling()
    updater.idle()

def keep_alive():
    while True:
        try:
            requests.get(RENDER_APP_URL)
            logging.info("Keep-Alive: Ping enviado")
        except Exception as e:
            logging.error(f"Keep-Alive error: {e}")
        time.sleep(300)

@app.get("/")
def home():
    return {"status": "Bot activo"}

if __name__ == "__main__":
    threading.Thread(target=keep_alive, daemon=True).start()
    threading.Thread(target=run_bot, daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=10000)