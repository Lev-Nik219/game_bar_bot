from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, WebAppInfo

from config import ADMIN_IDS
from database import get_user

router = Router()

def main_user_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    webapp_url = f"https://game-bar-web.vercel.app?user_id={user_id}"
    keyboard = [
        [KeyboardButton(text="🎮 Играть в Game Bar Casino", web_app=WebAppInfo(url=webapp_url))],
        [KeyboardButton(text="📩 Поддержка")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def admin_user_keyboard(user_id: int) -> ReplyKeyboardMarkup:
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
    
    # Обработка реферальной ссылки через deep link /start ref_XXX
    import re
    import sqlite3 as sq
    match = re.search(r'/start\s+ref_(\d+)', message.text or '')
    if match:
        inviter_id = int(match.group(1))
        if inviter_id != user_id:
            try:
                conn = sq.connect("casino.db", timeout=10)
                conn.execute("PRAGMA busy_timeout = 5000")
                c = conn.cursor()
                c.execute("SELECT invited_by FROM users WHERE user_id = ?", (user_id,))
                row = c.fetchone()
                if not row or row[0] is None:
                    c.execute("UPDATE users SET invited_by = ? WHERE user_id = ?", (inviter_id, user_id))
                    c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
                    bal = c.fetchone()[0] or 0
                    c.execute("UPDATE users SET balance = ? WHERE user_id = ?", (bal + 25, user_id))
                    conn.commit()
                    conn.close()
                    await message.answer(
                        f"🎉 Вы перешли по реферальной ссылке!\n\n"
                        f"💰 На ваш счёт зачислено +25 💎\n\n"
                        f"Сыграйте в любую игру, и ваш друг получит +100 💎!"
                    )
                    try:
                        await message.bot.send_message(
                            inviter_id,
                            f"👤 По вашей ссылке присоединился новый игрок!\n"
                            f"🎁 Вы получите +100 💎 после его первой игры!"
                        )
                    except:
                        pass
                else:
                    conn.close()
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