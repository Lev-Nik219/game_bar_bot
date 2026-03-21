import asyncpg
import logging
from database import init_db_pool
from aiogram import Bot

logger = logging.getLogger(__name__)

async def award_referral_bonus(user_id: int, inviter_id: int, bot: Bot):
    try:
        pool = await init_db_pool()
        async with pool.acquire() as conn:
            await conn.execute("UPDATE users SET balance = balance + 30 WHERE user_id = $1", user_id)
            await conn.execute("UPDATE users SET balance = balance + 30 WHERE user_id = $1", inviter_id)
        await pool.close()
        await bot.send_message(user_id, "🎉 Поздравляем! Вы сыграли первую игру и получили 30 бонусных баллов!")
        await bot.send_message(inviter_id, "🎉 Ваш друг сыграл первую игру! Вы получаете 30 бонусных баллов!")
    except Exception as e:
        logger.error(f"Ошибка начисления реферального бонуса: {e}")

async def award_referral_deposit_bonus(user_id: int, amount_points: int, bot: Bot):
    pool = await init_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT invited_by FROM users WHERE user_id = $1", user_id)
        if row and row['invited_by']:
            inviter_id = row['invited_by']
            bonus = int(amount_points * 0.15)
            await conn.execute("UPDATE users SET balance = balance + $1 WHERE user_id = $2", bonus, inviter_id)
            await conn.execute("UPDATE users SET referral_earnings = referral_earnings + $1 WHERE user_id = $2", bonus, inviter_id)
            try:
                await bot.send_message(
                    inviter_id,
                    f"💰 Ваш друг пополнил баланс на {amount_points} баллов!\n"
                    f"Вы получили бонус 15% — {bonus} баллов."
                )
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления о реферальном бонусе: {e}")
    await pool.close()