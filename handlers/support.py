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

@router.message(F.text == "📩 Поддержка")
async def support_contact(message: types.Message):
    await message.answer(
        "📩 **Служба поддержки**\n\n"
        "Напишите ваш вопрос или проблему одним сообщением.\n"
        "Администратор ответит вам в ближайшее время.\n\n"
        "✏️ Введите ваше сообщение:"
    )

@router.message(F.text)
async def handle_user_message(message: types.Message):
    user_id = message.from_user.id
    text = message.text
    
    if text.startswith('/') or user_id in ADMIN_IDS:
        return
    
    save_support_message(user_id, text)
    
    for admin_id in ADMIN_IDS:
        try:
            await message.bot.send_message(
                admin_id,
                f"📩 <b>Новое сообщение от пользователя</b>\n\n"
                f"👤 ID: {user_id}\n"
                f"👤 Username: @{message.from_user.username or 'нет'}\n"
                f"📝 Сообщение: {text}\n\n"
                f"💡 Чтобы ответить, отправьте команду:\n"
                f"<code>/reply {user_id} ваш текст ответа</code>",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Ошибка уведомления админа: {e}")
    
    await message.answer("✅ Ваше сообщение отправлено администратору. Ответ придёт сюда в ближайшее время.")

# ---------- ОТВЕТ ПОЛЬЗОВАТЕЛЮ ----------
@router.message(Command("reply"))
async def reply_to_user(message: types.Message):
    logger.info(f"КОМАНДА /reply ПОЛУЧЕНА от {message.from_user.id}: {message.text}")
    
    admin_id = message.from_user.id
    if admin_id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    
    # Разбираем команду
    text = message.text
    parts = text.split(maxsplit=2)
    
    logger.info(f"Разбор команды: parts={parts}, len={len(parts)}")
    
    if len(parts) < 3:
        logger.warning(f"Недостаточно аргументов: {parts}")
        await message.answer(
            "❌ Использование: /reply ID_пользователя текст_ответа\n\n"
            "Пример: `/reply 1234567890 Спасибо за обращение!`",
            parse_mode="HTML"
        )
        return
    
    try:
        target_user_id = int(parts[1])
        reply_text = parts[2]
        logger.info(f"Целевой пользователь: {target_user_id}, текст: {reply_text}")
    except ValueError as e:
        logger.error(f"Ошибка преобразования ID: {e}")
        await message.answer("❌ ID пользователя должен быть числом.")
        return
    
    try:
        await message.bot.send_message(
            target_user_id,
            f"📨 <b>Ответ от администратора:</b>\n\n{reply_text}",
            parse_mode="HTML"
        )
        logger.info(f"Ответ успешно отправлен пользователю {target_user_id}")
        await message.answer(f"✅ Ответ отправлен пользователю {target_user_id}")
    except Exception as e:
        logger.error(f"Ошибка отправки ответа: {e}")
        await message.answer(f"❌ Не удалось отправить ответ: {e}")

# ---------- ПРОСМОТР СООБЩЕНИЙ ----------
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