import os
import logging
from fastapi import FastAPI
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
import uvicorn
import asyncio
import urllib.request

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
    await update.message.reply_text("Hola 👋\n\nEnvíame tu confesión en texto y la publicaré anónimamente.")

async def handle_non_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚠️ Solo acepto confesiones en texto.")

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

async def run_bot():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_confession))
    app.add_handler(MessageHandler(~filters.TEXT & ~filters.COMMAND, handle_non_text))
    app.add_handler(CallbackQueryHandler(handle_moderation))
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    
    while True:
        await asyncio.sleep(3600)

def run_fastapi():
    app = FastAPI()

    @app.get("/")
    def read_root():
        return {"status": "Bot is running"}
    
    uvicorn.run(app, host="0.0.0.0", port=10000)

async def self_ping():
    url = os.getenv("RENDER_EXTERNAL_URL") or "https://oneandysr-github-io.onrender.com"
    while True:
        try:
            urllib.request.urlopen(url, timeout=10)
            logging.info("Ping sent to keep server alive")
        except Exception as e:
            logging.warning(f"Ping failed: {e}")
        await asyncio.sleep(300)  # cada 5 minutos

async def main():
    await asyncio.gather(
        run_bot(),
        asyncio.to_thread(run_fastapi),
        self_ping()
    )

if __name__ == "__main__":
    asyncio.run(main())
