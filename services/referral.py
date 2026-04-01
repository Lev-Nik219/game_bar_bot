import aiosqlite
import logging
from database import DB_NAME
from aiogram import Bot

logger = logging.getLogger(__name__)

async def award_referral_bonus(user_id: int, inviter_id: int, bot: Bot):
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("UPDATE users SET balance = balance + 30 WHERE user_id = ?", (user_id,))
            await db.execute("UPDATE users SET balance = balance + 30 WHERE user_id = ?", (inviter_id,))
            await db.commit()
        await bot.send_message(user_id, "🎉 Поздравляем! Вы сыграли первую игру и получили 30 бонусных баллов!")
        await bot.send_message(inviter_id, "🎉 Ваш друг сыграл первую игру! Вы получаете 30 бонусных баллов!")
    except Exception as e:
        logger.error(f"Ошибка начисления реферального бонуса: {e}")

async def award_referral_deposit_bonus(user_id: int, amount_points: int, bot: Bot):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT invited_by FROM users WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        if row and row[0]:
            inviter_id = row[0]
            bonus = int(amount_points * 0.15)
            cursor = await db.execute("SELECT balance FROM users WHERE user_id = ?", (inviter_id,))
            inviter_balance = (await cursor.fetchone())[0]
            await db.execute("UPDATE users SET balance = ? WHERE user_id = ?", (inviter_balance + bonus, inviter_id))
            await db.execute("UPDATE users SET referral_earnings = referral_earnings + ? WHERE user_id = ?", (bonus, inviter_id))
            await db.commit()
            try:
                await bot.send_message(
                    inviter_id,
                    f"💰 Ваш друг пополнил баланс на {amount_points} баллов!\n"
                    f"Вы получили бонус 15% — {bonus} баллов."
                )
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления о реферальном бонусе: {e}")
