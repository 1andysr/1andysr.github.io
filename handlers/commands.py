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
    await backup_manager.save_backup()
    await update.message.reply_text("💾 Backup realizado exitosamente!")    
    
async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manejar audios como confesiones"""
    if update.message.chat.type != "private":
        return

    user_id = update.message.from_user.id
    
    # Verificar baneo
    banned, message = is_user_banned(user_id, banned_users)
    if banned:
        await update.message.reply_text(message)
        return

    # Verificar rate limit
    rate_limited, message = check_rate_limit(user_id, user_last_confession)
    if rate_limited:
        await update.message.reply_text(message)
        return

    current_time = time.time()
    user_last_confession[user_id] = current_time
    
    audio = update.message.audio
    audio_file = await audio.get_file()
    
    # Guardar información del audio
    audio_id = generate_id(user_id, audio.file_id, current_time)
    
    pending_audios[audio_id] = {
        "file_id": audio.file_id,
        "duration": audio.duration,
        "file_size": audio.file_size,
        "user_id": user_id,
        "timestamp": current_time
    }
    
    await send_to_moderation(
        context, 
        audio_id, 
        None, 
        user_id, 
        is_audio=True,
        audio_data=pending_audios[audio_id]
    )
    
    await update.message.reply_text("✋ Tu audio confesión ha sido enviada a moderación.")    