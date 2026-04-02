#!/usr/bin/env python3
import asyncio
import logging
import threading
import os
import time
from flask import Flask, jsonify, request
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeDefault, InlineKeyboardMarkup, InlineKeyboardButton

from config import MAIN_BOT_TOKEN
from database import create_db, init_db_pool, close_db_pool
from handlers.main_bot import (
    games_router, profile_router, tournaments_router,
    payments_router, fallback_router, bot_info_router
)
from handlers.main_bot.cashback import router as cashback_router, process_cashback
from middlewares import UserStatusMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

loop = None

# ---------- Flask ----------
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return jsonify({"status": "Main bot is running", "time": time.time()})

@flask_app.route('/health')
def health():
    return jsonify({"status": "ok"}), 200

@flask_app.route('/favicon.ico')
def favicon():
    return '', 204

def run_flask():
    port = int(os.getenv('PORT', 10000))
    flask_app.run(host='0.0.0.0', port=port)

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
async def global_error_handler(update: types.Update, exception: Exception):
    logger.error(f"Глобальная ошибка: {exception}", exc_info=True)
    try:
        if update.message:
            await update.message.answer(
                "⚠️ Сервис временно недоступен. Ведутся технические работы.\n"
                "Пожалуйста, попробуйте позже."
            )
        elif update.callback_query:
            await update.callback_query.message.answer(
                "⚠️ Сервис временно недоступен. Ведутся технические работы.\n"
                "Пожалуйста, попробуйте позже."
            )
            try:
                await update.callback_query.answer()
            except:
                pass
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение об ошибке: {e}")
    return True

async def check_cashback_periodically():
    """Фоновая задача: проверка кэшбека каждый час."""
    while True:
        await asyncio.sleep(3600)
        try:
            from database import execute_query
            rows = await execute_query("SELECT user_id FROM users", fetch_all=True)
            if rows:
                for row in rows:
                    await process_cashback(row[0], bot)
        except Exception as e:
            logger.error(f"Ошибка в фоновой проверке кэшбека: {e}")

async def on_startup():
    await init_db_pool()
    await create_db()
    commands = [
        BotCommand(command="start", description="Запустить бота"),
        BotCommand(command="myid", description="Мой Telegram ID"),
        BotCommand(command="cancel", description="Отменить текущее действие"),
        BotCommand(command="cashback", description="Проверить кэшбек"),
        BotCommand(command="debug_tournament", description="Диагностика турниров"),
    ]
    await bot.set_my_commands(commands, scope=BotCommandScopeDefault())
    logger.info("База данных готова, команды установлены, бот запущен.")
    asyncio.create_task(check_cashback_periodically())

async def main():
    global loop
    loop = asyncio.get_event_loop()
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    await asyncio.sleep(2)
    dp.startup.register(on_startup)
    
    try:
        await dp.start_polling(bot)
    finally:
        await close_db_pool()

if __name__ == "__main__":
    asyncio.run(main())