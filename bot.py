import os
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = int(os.getenv("GROUP_ID"))

logging.basicConfig(level=logging.INFO)

# Comando /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hola 👋\n\nEnvíame tu confesión y la publicaré anónimamente.")

# Manejo de mensajes
async def handle_confession(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type == "private":  # Solo responde en privado
        confession = update.message.text
        await context.bot.send_message(chat_id=GROUP_ID, text=f"📢 Nueva confesión:\n\n{confession}")
        await update.message.reply_text("✅ Confesión enviada.")
    
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_confession))
    app.run_polling()

if __name__ == "__main__":
    main()
    