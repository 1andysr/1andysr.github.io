import json
import os
import logging
from datetime import datetime
from ..config import pending_confessions, pending_polls, banned_users, user_last_confession

class BackupManager:
    def __init__(self, backup_file="bot_backup.json"):
        self.backup_file = backup_file
        self.backup_interval = 300  # 5 minutos
    
    async def save_backup(self):
        """Guarda un backup de los datos en memoria"""
        try:
            backup_data = {
                'pending_confessions': pending_confessions,
                'pending_polls': pending_polls,
                'banned_users': banned_users,
                'user_last_confession': user_last_confession,
                'backup_timestamp': datetime.now().isoformat()
            }
            
            with open(self.backup_file, 'w', encoding='utf-8') as f:
                json.dump(backup_data, f, ensure_ascii=False, indent=2)
            
            logging.info(f"💾 Backup guardado: {self.backup_file}")
            
        except Exception as e:
            logging.error(f"❌ Error guardando backup: {e}")
    
    async def load_backup(self):
        """Carga un backup existente"""
        try:
            if os.path.exists(self.backup_file):
                with open(self.backup_file, 'r', encoding='utf-8') as f:
                    backup_data = json.load(f)
                
                # Actualizar las variables globales
                pending_confessions.update(backup_data.get('pending_confessions', {}))
                pending_polls.update(backup_data.get('pending_polls', {}))
                banned_users.update(backup_data.get('banned_users', {}))
                user_last_confession.update(backup_data.get('user_last_confession', {}))
                
                logging.info(f"📂 Backup cargado: {len(pending_confessions)} confesiones, {len(pending_polls)} encuestas")
                return True
                
        except Exception as e:
            logging.error(f"❌ Error cargando backup: {e}")
        
        return False
    
    async def start_auto_backup(self):
        """Inicia backup automático cada X tiempo"""
        import asyncio
        while True:
            await asyncio.sleep(self.backup_interval)
            await self.save_backup()

# Instancia global
backup_manager = BackupManager()