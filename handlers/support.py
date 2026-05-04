import time
import logging
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import ADMIN_IDS
from keyboards.admin import admin_main_keyboard

logger = logging.getLogger(__name__)
router = Router()

def save_support_message(user_id: int, message: str):
    import sqlite3
    conn = sqlite3.connect("casino.db")
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO support_messages (user_id, message, created_at) VALUES (?, ?, ?)",
        (user_id, message, int(time.time()))
    )
    conn.commit()
    conn.close()

def get_unread_support_messages():
    import sqlite3
    conn = sqlite3.connect("casino.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, user_id, message, created_at FROM support_messages WHERE is_read = 0 ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return rows

async def notify_admins(bot, user_id, username, text):
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"📩 <b>Новое сообщение от пользователя</b>\n\n"
                f"👤 ID: {user_id}\n"
                f"👤 Username: @{username or 'нет'}\n"
                f"📝 Сообщение: {text}\n\n"
                f"💡 Чтобы ответить, используйте команду:\n"
                f"<code>/reply {user_id} ваш текст ответа</code>",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Ошибка уведомления админа: {e}")

@router.message(F.text == "📩 Поддержка")
async def support_contact(message: types.Message):
    await message.answer(
        "📩 **Служба поддержки**\n\n"
        "Напишите ваш вопрос или проблему одним сообщением.\n"
        "Администратор ответит вам в ближайшее время.\n\n"
        "✏️ Введите ваше сообщение:"
    )

# ===== КОМАНДА ДЛЯ ОТВЕТА (ПЕРВЫЙ ПРИОРИТЕТ) =====
@router.message(Command("reply"))
async def reply_to_user(message: types.Message):
    logger.info(f"=== /reply command received from {message.from_user.id} ===")
    
    admin_id = message.from_user.id
    if admin_id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    
    # Разбираем команду
    parts = message.text.split(maxsplit=2)
    logger.info(f"Parts: {parts}")
    
    if len(parts) < 3:
        await message.answer(
            "❌ Использование: /reply ID_пользователя текст_ответа\n\n"
            "Пример: /reply 1234567890 Спасибо за обращение!"
        )
        return
    
    try:
        target_user_id = int(parts[1])
        reply_text = parts[2]
    except ValueError:
        await message.answer("❌ ID пользователя должен быть числом.")
        return
    
    try:
        await message.bot.send_message(
            target_user_id,
            f"📨 <b>Ответ от администратора:</b>\n\n{reply_text}",
            parse_mode="HTML"
        )
        logger.info(f"Reply sent successfully to {target_user_id}")
        await message.answer(f"✅ Ответ отправлен пользователю {target_user_id}")
    except Exception as e:
        logger.error(f"Failed to send reply: {e}")
        await message.answer(f"❌ Не удалось отправить ответ: {e}")

# ===== ПРОСМОТР НЕПРОЧИТАННЫХ СООБЩЕНИЙ =====
@router.callback_query(F.data == "admin_support_messages")
async def admin_support_messages(callback: types.CallbackQuery):
    messages = get_unread_support_messages()
    
    back_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад в админ-панель", callback_data="admin_back")]
    ])
    
    if not messages:
        await callback.message.edit_text("📭 Нет непрочитанных сообщений.", reply_markup=back_keyboard)
        await callback.answer()
        return
    
    text = "📩 <b>Непрочитанные сообщения:</b>\n\n"
    for msg_id, user_id, msg, created_at in messages[:10]:
        date = time.strftime('%Y-%m-%d %H:%M', time.localtime(created_at))
        text += f"👤 ID: {user_id}\n📅 {date}\n📝 {msg}\n"
        text += f"➡️ Ответ: <code>/reply {user_id} ваш текст</code>\n\n"
    
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=back_keyboard)
    await callback.answer()