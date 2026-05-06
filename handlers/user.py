from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, WebAppInfo

from config import ADMIN_IDS
from database import get_user

router = Router()

REFERRAL_BONUS_INVITED = 25
REFERRAL_BONUS_INVITER = 100

def main_user_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    webapp_url = f"https://game-bar-web.vercel.app?user_id={user_id}"
    keyboard = [
        [KeyboardButton(text="🎮 Играть в Game Bar Casino", web_app=WebAppInfo(url=webapp_url))],
        [KeyboardButton(text="📩 Поддержка")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def admin_user_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    """Клавиатура для админа — только кнопка Играть"""
    webapp_url = f"https://game-bar-web.vercel.app?user_id={user_id}"
    keyboard = [
        [KeyboardButton(text="🎮 Играть в Game Bar Casino", web_app=WebAppInfo(url=webapp_url))]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username
    await get_user(user_id, username)
    
    # Проверяем реферальный код в deep link
    args = message.text.split()
    if len(args) > 1 and args[1].startswith('ref_'):
        try:
            inviter_id = int(args[1].replace('ref_', ''))
            if inviter_id != user_id:
                import sqlite3
                import time
                DB_NAME = "casino.db"
                conn = sqlite3.connect(DB_NAME, timeout=10)
                conn.execute("PRAGMA busy_timeout = 5000")
                cursor = conn.cursor()
                
                # Проверяем, не приглашён ли уже
                cursor.execute("SELECT invited_by FROM users WHERE user_id = ?", (user_id,))
                row = cursor.fetchone()
                
                if not row or row[0] is None:
                    # Начисляем бонус приглашённому
                    cursor.execute("UPDATE users SET invited_by = ? WHERE user_id = ?", (inviter_id, user_id))
                    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
                    bal = cursor.fetchone()[0]
                    cursor.execute("UPDATE users SET balance = ? WHERE user_id = ?", (bal + REFERRAL_BONUS_INVITED, user_id))
                    conn.commit()
                    
                    await message.answer(
                        f"🎉 Вы перешли по реферальной ссылке!\n\n"
                        f"💰 На ваш счёт зачислено +{REFERRAL_BONUS_INVITED} 💎\n\n"
                        f"Теперь сыграйте в любую игру, и ваш друг получит +{REFERRAL_BONUS_INVITER} 💎!"
                    )
                    
                    # Уведомляем пригласившего
                    from main_bot import bot
                    try:
                        await bot.send_message(
                            inviter_id,
                            f"👤 По вашей ссылке присоединился новый игрок!\n\n"
                            f"🎁 Вы получите +{REFERRAL_BONUS_INVITER} 💎 после его первой игры!"
                        )
                    except:
                        pass
                
                conn.close()
        except Exception as e:
            print(f"Referral error: {e}")

        # Обработка реферальной ссылки (deep link через бота)
    import re
    match = re.search(r'/start\s+ref_(\d+)', message.text or '')
    if match:
        try:
            inviter_id = int(match.group(1))
            if inviter_id != user_id:
                import sqlite3
                conn = sqlite3.connect("casino.db")
                conn.execute("PRAGMA busy_timeout = 5000")
                cursor = conn.cursor()
                cursor.execute("SELECT invited_by FROM users WHERE user_id = ?", (user_id,))
                row = cursor.fetchone()
                if not row or row[0] is None:
                    cursor.execute("UPDATE users SET invited_by = ? WHERE user_id = ?", (inviter_id, user_id))
                    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
                    bal = cursor.fetchone()[0] if cursor.fetchone() else 0
                    cursor.execute("UPDATE users SET balance = ? WHERE user_id = ?", (bal + 25, user_id))
                    conn.commit()
                    conn.close()
                    await message.answer(
                        f"🎉 Вы перешли по реферальной ссылке!\n\n"
                        f"💰 На ваш счёт зачислено +25 💎\n\n"
                        f"Сыграйте в любую игру, и ваш друг получит +100 💎!"
                    )
                    # Уведомление пригласившему
                    from main_bot import bot
                    await bot.send_message(inviter_id, 
                        f"👤 Новый игрок присоединился по вашей ссылке!\n"
                        f"Вы получите +100 💎 после его первой игры!")
        except Exception as e:
            print(f"Referral error: {e}")
    
    if user_id in ADMIN_IDS:
        await message.answer(
            "👑 Админ-панель\n\nИспользуйте /admin",
            reply_markup=admin_user_keyboard(user_id)
        )
    else:
        await message.answer(
            "🎮 Добро пожаловать в Game Bar Casino!\n\nНажмите на кнопку ниже, чтобы начать игру:",
            reply_markup=main_user_keyboard(user_id)
        )

@router.message(Command("myid"))
async def cmd_myid(message: types.Message):
    await message.answer(f"Ваш Telegram ID: {message.from_user.id}")

@router.message(F.text)
async def handle_regular_text(message: types.Message):
    user_id = message.from_user.id
    text = message.text
    
    if text.startswith('/'):
        return
    
    if user_id in ADMIN_IDS:
        return
    
    from handlers.support import save_support_message, notify_admins
    save_support_message(user_id, text)
    await notify_admins(message.bot, user_id, message.from_user.username, text)
    await message.answer("✅ Ваше сообщение отправлено администратору. Ответ придёт сюда.")