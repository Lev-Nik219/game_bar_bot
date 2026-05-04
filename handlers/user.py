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

# ===== ВАЖНО: обработчик для любых текстовых сообщений НЕ ДОЛЖЕН ПЕРЕХВАТЫВАТЬ КОМАНДЫ =====
@router.message(F.text)
async def handle_regular_text(message: types.Message):
    user_id = message.from_user.id
    text = message.text
    
    # КЛЮЧЕВОЕ: пропускаем ВСЕ команды
    if text.startswith('/'):
        return
    
    # Пропускаем админов
    if user_id in ADMIN_IDS:
        return
    
    # Если дошли сюда — это обычный пользователь с обычным текстом
    # Но мы не должны обрабатывать текстовые сообщения обычных пользователей,
    # потому что у них нет других кнопок, кроме "Играть" и "Поддержка"
    # Всё, что они пишут — это сообщение в поддержку
    
    from handlers.support import save_support_message, notify_admins
    save_support_message(user_id, text)
    await notify_admins(message.bot, user_id, message.from_user.username, text)
    await message.answer("✅ Ваше сообщение отправлено администратору. Ответ придёт сюда.")