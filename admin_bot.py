#!/usr/bin/env python3
import asyncio
import logging
import threading
import os
import time
from flask import Flask, jsonify
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage

from config import ADMIN_BOT_TOKEN
from database import create_db
from handlers.admin_bot import main as admin_handlers

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- Flask ----------
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return jsonify({"status": "Admin bot is running", "time": time.time()})

@flask_app.route('/health')
def health():
    return jsonify({"status": "ok"}), 200

@flask_app.route('/favicon.ico')
def favicon():
    return '', 204

def run_flask():
    port = int(os.getenv('PORT', 8081))
    flask_app.run(host='0.0.0.0', port=port)

# ---------- Telegram Bot ----------
bot = Bot(token=ADMIN_BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

dp.include_router(admin_handlers.router)

@dp.errors()
async def global_error_handler(update: types.Update, exception: Exception):
    logger.error(f"Глобальная ошибка в админ-боте: {exception}", exc_info=True)
    try:
        if update.message:
            await update.message.answer(
                "⚠️ Сервис временно недоступен. Ведутся технические работы. "
                "Пожалуйста, попробуйте позже."
            )
        elif update.callback_query:
            await update.callback_query.message.answer(
                "⚠️ Сервис временно недоступен. Ведутся технические работы. "
                "Пожалуйста, попробуйте позже."
            )
            try:
                await update.callback_query.answer()
            except:
                pass
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение об ошибке: {e}")
    return True

async def main():
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    await asyncio.sleep(2)
    await create_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())