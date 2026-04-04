#!/usr/bin/env python3
import asyncio
import logging
import os
import time
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeDefault

from config import MAIN_BOT_TOKEN
from database import create_db, init_db_pool, close_db_pool
from handlers.main_bot import (
    games_router, profile_router, tournaments_router,
    payments_router, fallback_router, bot_info_router
)
from handlers.main_bot.cashback import router as cashback_router
from middlewares import UserStatusMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Простой HTTP сервер для healthcheck
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

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
    port = int(os.environ.get('PORT', 10000))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    server.serve_forever()

# ---------- Telegram Bot ----------
bot = Bot(token=MAIN_BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

dp.message.middleware(UserStatusMiddleware())

dp.include_router(games_router)
dp.include_router(profile_router)
dp.include_router(tournaments_router)
dp.include_router(payments_router)
dp.include_router(bot_info_router)
dp.include_router(cashback_router)
dp.include_router(fallback_router)

@dp.errors()
async def global_error_handler(event: types.ErrorEvent):
    """Глобальный обработчик ошибок"""
    logger.error(f"Глобальная ошибка: {event.exception}", exc_info=True)
    return True

async def on_startup():
    await init_db_pool()
    await create_db()
    commands = [
        BotCommand(command="start", description="Запустить бота"),
        BotCommand(command="myid", description="Мой Telegram ID"),
    ]
    await bot.set_my_commands(commands, scope=BotCommandScopeDefault())
    logger.info("База данных готова, команды установлены, бот запущен.")

async def main():
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()
    
    await asyncio.sleep(1)
    
    await bot.delete_webhook()
    
    dp.startup.register(on_startup)
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())