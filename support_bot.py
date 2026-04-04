#!/usr/bin/env python3
import asyncio
import logging
import threading
import re
import os
import time
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage

from config import SUPPORT_BOT_TOKEN, ADMIN_IDS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Простой HTTP сервер для healthcheck
from http.server import HTTPServer, BaseHTTPRequestHandler

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health' or self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')
        else:
            self.send_response(404)
        self.end_headers()
    
    def log_message(self, format, *args):
        pass

def run_health_server():
    port = int(os.environ.get('PORT', 10002))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    server.serve_forever()

# ---------- Telegram Bot ----------
bot = Bot(token=SUPPORT_BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

ID_PATTERN = r"ID:\s*(\d+)"

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Здравствуйте! Это бот поддержки.\n\n"
        "Напишите ваш вопрос, и администратор ответит вам в ближайшее время.\n\n"
        "📌 Для связи с администратором используйте эту команду: /start"
    )

@dp.message()
async def handle_message(message: types.Message):
    user_id = message.from_user.id
    if user_id in ADMIN_IDS:
        if message.reply_to_message:
            match = re.search(ID_PATTERN, message.reply_to_message.text)
            if match:
                target_user_id = int(match.group(1))
                try:
                    await bot.send_message(
                        target_user_id,
                        f"📨 <b>Ответ от администратора:</b>\n\n{message.text}",
                        parse_mode="HTML"
                    )
                    await message.reply("✅ Ответ отправлен пользователю.")
                except Exception as e:
                    await message.reply(f"❌ Не удалось отправить ответ: {e}")
            else:
                await message.reply("❌ Не удалось определить, кому адресован ответ.")
        else:
            await message.reply(
                "Чтобы ответить пользователю, используйте 'ответить' на его сообщение.\n\n"
                "В сообщении пользователя есть его ID."
            )
        return

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"📩 <b>Сообщение от пользователя</b>\n\n"
                f"👤 @{message.from_user.username or 'нет username'} (ID: {user_id})\n"
                f"📝 Сообщение:\n{message.text}\n\n"
                f"💡 Чтобы ответить, нажмите 'Ответить' на это сообщение.",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение администратору {admin_id}: {e}")

    await message.reply(
        "✅ Ваше сообщение отправлено администратору.\n"
        "Ожидайте ответа в ближайшее время."
    )

@dp.errors()
async def global_error_handler(event: types.ErrorEvent):
    """Глобальный обработчик ошибок"""
    logger.error(f"Глобальная ошибка: {event.exception}", exc_info=True)
    return True

async def main():
    # Запускаем healthcheck сервер
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()
    
    await asyncio.sleep(1)
    
    await bot.delete_webhook()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())