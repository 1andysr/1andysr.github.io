from telegram import Update
from telegram.ext import ContextTypes
from ..utils.helpers import is_user_banned
from ..config import banned_users
from ..utils.backup_manager import backup_manager

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hola 👋\n\nEnvíame tu confesión en texto o una encuesta nativa de Telegram "
        "y la publicaré anónimamente después de moderación."
    )

async def confesion(update: Update, context: ContextTypes.DEFAULT_TYPE):  
    user_id = update.message.from_user.id
    
    # Verificar si el usuario está baneado
    banned, message = is_user_banned(user_id, banned_users)
    if banned:
        await update.message.reply_text(message)
        return

    await update.message.reply_text(
        "No se permitirán:\n\n"
        "Política\nOfensas sin sentido\n"
        "Mención repetida de una misma persona\n"
        "Datos privados ajenos sin consentimiento"
    )
    
async def backup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando para hacer backup manual"""
    if update.message.chat.id != int(MODERATION_GROUP_ID):
        return
    
    await backup_manager.save_backup()
    await update.message.reply_text("💾 Backup realizado exitosamente!")    