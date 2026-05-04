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

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username
    await get_user(user_id, username)
    
    if user_id in ADMIN_IDS:
        await message.answer("👑 Админ-панель\n\nИспользуйте /admin")
    else:
        await message.answer(
            "🎮 Добро пожаловать в Game Bar Casino!\n\nНажмите на кнопку ниже, чтобы начать игру:",
            reply_markup=main_user_keyboard(user_id)
        )

@router.message(Command("myid"))
async def cmd_myid(message: types.Message):
    await message.answer(f"Ваш Telegram ID: {message.from_user.id}")