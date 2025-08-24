import asyncio
import uvicorn
import urllib.request
import logging
from fastapi import FastAPI
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from utils.backup_manager import backup_manager

from config import TOKEN
from handlers import (
    start, confesion, handle_non_text, 
    handle_confession, handle_poll, handle_moderation
)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

async def run_bot():
    # Cargar backup 
    await backup_manager.load_backup()
    
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("confesion", confesion))
    app.add_handler(CommandHandler("backup", backup_cmd))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_confession))
    app.add_handler(MessageHandler(filters.POLL & ~filters.COMMAND, handle_confession))
    app.add_handler(MessageHandler(~filters.TEXT & ~filters.POLL & ~filters.COMMAND, handle_non_text))
    app.add_handler(MessageHandler(filters.AUDIO & ~filters.COMMAND, handle_audio))
    
    app.add_handler(CallbackQueryHandler(handle_moderation))
    
    # Iniciar backup automático en segundo plano
    asyncio.create_task(backup_manager.start_auto_backup())
    
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
    from config import RENDER_EXTERNAL_URL
    url = RENDER_EXTERNAL_URL or "https://oneandysr-github-io.onrender.com"
    while True:
        try:
            urllib.request.urlopen(url, timeout=10)
            logging.info("Ping sent to keep server alive")
        except Exception as e:
            logging.warning(f"Ping failed: {e}")
        await asyncio.sleep(300)

async def main():
    await asyncio.gather(
        run_bot(),
        asyncio.to_thread(run_fastapi),
        self_ping()
    )

if __name__ == "__main__":
    asyncio.run(main())