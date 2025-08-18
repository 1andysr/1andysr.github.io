import os
import logging
from threading import Thread
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

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
MODERATION_GROUP_ID = os.getenv("MODERATION_GROUP_ID")
PUBLIC_CHANNEL = os.getenv("PUBLIC_CHANNEL")

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

pending_confessions = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hola 👋\n\nEnvíame tu confesión en texto y la publicaré anónimamente."
    )

async def handle_non_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚠️ Solo acepto confesiones en texto.")

async def handle_confession(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        return
    
    user_id = update.message.from_user.id
    confession = update.message.text
    
    confession_id = abs(hash(f"{user_id}{confession}")) % (10**8)
    pending_confessions[confession_id] = {
        "text": confession,
        "user_id": user_id
    }
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Aprobar", callback_data=f"approve_{confession_id}"),
            InlineKeyboardButton("❌ Rechazar", callback_data=f"reject_{confession_id}")
        ]
    ]
    
    await context.bot.send_message(
        chat_id=MODERATION_GROUP_ID,
        text=f"📝 Nueva confesión (ID: {confession_id}):\n\n{confession}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    await update.message.reply_text("✋ Tu confesión ha sido enviada a moderación.")

async def handle_moderation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    action, confession_id = query.data.split("_")
    confession_id = int(confession_id)
    
    if confession_id not in pending_confessions:
        await query.edit_message_text("⚠️ Esta confesión ya fue procesada.")
        return
    
    confession_data = pending_confessions[confession_id]
    
    if action == "approve":
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

def run_bot():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_confession))
    app.add_handler(MessageHandler(~filters.TEXT & ~filters.COMMAND, handle_non_text))
    app.add_handler(CallbackQueryHandler(handle_moderation))
    app.run_polling()

def run_web():
    web_app = FastAPI()
    
    @web_app.get("/")
    def home():
        return {"status": "Bot running"}
    
    uvicorn.run(web_app, host="0.0.0.0", port=10000)

if __name__ == "__main__":
    bot_thread = Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    run_web()