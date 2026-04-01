#!/usr/bin/env python3
import asyncio
import logging
import threading
import re
import os
import time
from flask import Flask, jsonify
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage

from config import SUPPORT_BOT_TOKEN, ADMIN_IDS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- Flask ----------
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return jsonify({"status": "Support bot is running", "time": time.time()})

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

async def main():
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    await asyncio.sleep(2)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
