#!/usr/bin/env python3
import asyncio
import logging
import threading
import os
import time
import aiosqlite
from flask import Flask, jsonify, request
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeDefault, InlineKeyboardMarkup, InlineKeyboardButton

from config import MAIN_BOT_TOKEN
from database import DB_NAME, create_db
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

@flask_app.route('/crypto_webhook', methods=['GET', 'POST'])
def crypto_webhook():
    if request.method == 'GET':
        logger.info("Webhook check request received")
        return jsonify({"status": "ok"}), 200
    
    try:
        data = request.json
        logger.info(f"Webhook received: {data}")
        
        if data and data.get('status') == 'paid':
            payload = data.get('payload')
            if payload:
                asyncio.run_coroutine_threadsafe(
                    handle_successful_payment(payload),
                    loop
                )
        
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        logger.error(f"Error in webhook: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

async def handle_successful_payment(payment_id: str):
    import aiosqlite
    from database import get_user, update_balance, update_crypto_transaction_status, add_deposit
    
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute(
                "SELECT user_id, amount_points, status FROM crypto_transactions WHERE payment_id = ?",
                (payment_id,)
            )
            row = await cursor.fetchone()
            if not row:
                logger.error(f"Transaction not found for payment_id: {payment_id}")
                return
            
            user_id, amount_points, status = row
            if status == 'paid':
                logger.info(f"Payment {payment_id} already processed")
                return
            
            await db.execute(
                "UPDATE crypto_transactions SET status = 'paid', confirmed_at = ? WHERE payment_id = ?",
                (int(time.time()), payment_id)
            )
            
            balance, *_ = await get_user(user_id, None)
            new_balance = balance + amount_points
            await update_balance(user_id, new_balance)
            await add_deposit(user_id, amount_points)
            
            # Бонус за первый депозит
            cursor = await db.execute(
                "SELECT first_deposit_bonus_claimed FROM users WHERE user_id = ?",
                (user_id,)
            )
            row2 = await cursor.fetchone()
            first_deposit_claimed = row2[0] if row2 else 0
            
            if not first_deposit_claimed:
                bonus_amount = int(amount_points * 0.5)
                await db.execute(
                    "UPDATE users SET balance = balance + ?, bonus_total = bonus_total + ?, "
                    "bonus_balance = bonus_balance + ?, first_deposit_bonus_claimed = 1 WHERE user_id = ?",
                    (bonus_amount, bonus_amount, bonus_amount, user_id)
                )
                new_balance += bonus_amount
                
                bot = Bot(token=MAIN_BOT_TOKEN)
                await bot.send_message(
                    user_id,
                    f"🎁 <b>Бонус за первый депозит!</b>\n\n"
                    f"Вы получили +50% бонусных баллов: {bonus_amount} баллов!\n\n"
                    f"🎲 Отыграйте их с вейджером 3x, чтобы вывести.",
                    parse_mode="HTML"
                )
                await bot.session.close()
            
            await db.commit()
        
        from services.referral import award_referral_deposit_bonus
        await award_referral_deposit_bonus(user_id, amount_points, None)
        
        bot = Bot(token=MAIN_BOT_TOKEN)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Вернуться в меню", callback_data="back_to_menu")]
        ])
        await bot.send_message(
            chat_id=user_id,
            text=(
                f"✅ <b>Оплата подтверждена!</b>\n\n"
                f"💰 Начислено: {amount_points} баллов\n"
                f"💎 Новый баланс: {new_balance} баллов\n\n"
                f"Нажмите на кнопку ниже, чтобы вернуться в главное меню:"
            ),
            parse_mode="HTML",
            reply_markup=keyboard
        )
        await bot.session.close()
        logger.info(f"Payment {payment_id} processed successfully for user {user_id}")
        
    except Exception as e:
        logger.error(f"Error processing payment {payment_id}: {e}")

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
        await asyncio.sleep(3600)  # каждый час
        try:
            async with aiosqlite.connect(DB_NAME) as db:
                cursor = await db.execute("SELECT user_id FROM users")
                users = await cursor.fetchall()
                for (user_id,) in users:
                    await process_cashback(user_id, bot)
        except Exception as e:
            logger.error(f"Ошибка в фоновой проверке кэшбека: {e}")

async def on_startup():
    await create_db()
    commands = [
        BotCommand(command="start", description="Запустить бота"),
        BotCommand(command="myid", description="Мой Telegram ID"),
        BotCommand(command="cancel", description="Отменить текущее действие"),
        BotCommand(command="cashback", description="Проверить кэшбек"),
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
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())