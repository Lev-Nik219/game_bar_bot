#!/usr/bin/env python3
import asyncio
import logging
import re
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage

from config import SUPPORT_BOT_TOKEN, ADMIN_IDS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=SUPPORT_BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

ID_PATTERN = r"ID:\s*(\d+)"

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Здравствуйте! Это бот поддержки. Напишите ваш вопрос, "
        "и администратор ответит вам в ближайшее время."
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
                        f"📨 Ответ от администратора:\n\n{message.text}"
                    )
                    await message.reply("✅ Ответ отправлен пользователю.")
                except Exception as e:
                    await message.reply(f"❌ Не удалось отправить ответ: {e}")
            else:
                await message.reply("❌ Не удалось определить, кому адресован ответ.")
        else:
            await message.reply("Чтобы ответить пользователю, используйте 'ответить' на его сообщение.")
        return

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"📩 Сообщение от @{message.from_user.username or 'пользователь'} "
                f"(ID: {user_id}):\n\n{message.text}",
                reply_markup=None
            )
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение администратору {admin_id}: {e}")

    await message.reply("✅ Ваше сообщение отправлено администратору. Ожидайте ответа.")

@dp.errors()
async def global_error_handler(update: types.Update, exception: Exception):
    logger.error(f"Глобальная ошибка в боте поддержки: {exception}", exc_info=True)
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
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())