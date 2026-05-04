import time
from aiogram import Router, types, F
from aiogram.filters import Command  # <-- ДОБАВИТЬ ЭТУ СТРОКУ
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import ADMIN_IDS
from keyboards.admin import admin_main_keyboard

router = Router()

# Хранилище ожидающих ответов {admin_id: user_id}
pending_replies = {}

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
    
    # Пропускаем команды и сообщения админа
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
                f"<code>/reply {user_id} ваш ответ</code>\n\n"
                f"Пример: <code>/reply {user_id} Спасибо за обращение!</code>",
                parse_mode="HTML"
            )
        except Exception:
            pass
    
    await message.answer("✅ Ваше сообщение отправлено администратору. Ответ придёт сюда в ближайшее время.")

# ---------- ОТВЕТ ПОЛЬЗОВАТЕЛЮ ЧЕРЕЗ КОМАНДУ ----------
@router.message(Command("reply"))
async def reply_to_user_command(message: types.Message):
    admin_id = message.from_user.id
    if admin_id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer(
            "❌ Использование: /reply <ID_пользователя> <текст ответа>\n\n"
            "Пример: /reply 1234567890 Спасибо за обращение!"
        )
        return
    
    try:
        target_user_id = int(args[1])
        reply_text = args[2]
    except ValueError:
        await message.answer("❌ ID пользователя должен быть числом.")
        return
    
    try:
        await message.bot.send_message(
            target_user_id,
            f"📨 <b>Ответ от администратора:</b>\n\n{reply_text}",
            parse_mode="HTML"
        )
        await message.answer(f"✅ Ответ отправлен пользователю {target_user_id}")
    except Exception as e:
        await message.answer(f"❌ Не удалось отправить ответ: {e}")

# ---------- ПРОСМОТР СООБЩЕНИЙ ----------
@router.callback_query(F.data == "admin_support_messages")
async def admin_support_messages(callback: types.CallbackQuery):
    messages = get_unread_support_messages()
    
    back_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад в админ-панель", callback_data="admin_back")]
    ])
    
    if not messages:
        await callback.message.edit_text("📭 Нет непрочитанных сообщений от пользователей.", reply_markup=back_keyboard)
        await callback.answer()
        return
    
    text = "📩 <b>Непрочитанные сообщения от пользователей:</b>\n\n"
    for msg_id, user_id, msg, created_at in messages[:10]:
        date = time.strftime('%Y-%m-%d %H:%M', time.localtime(created_at))
        text += f"👤 ID: {user_id}\n📅 {date}\n📝 {msg}\n"
        text += f"➡️ Чтобы ответить: <code>/reply {user_id} ваш ответ</code>\n\n"
    
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=back_keyboard)
    await callback.answer()