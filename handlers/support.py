import time
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import ADMIN_IDS
from handlers.admin import AdminStates
from keyboards.admin import admin_main_keyboard

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
    
    # Пропускаем команды и сообщения админа
    if text.startswith('/') or user_id in ADMIN_IDS:
        return
    
    # Сохраняем сообщение
    save_support_message(user_id, text)
    
    # Уведомляем админов
    for admin_id in ADMIN_IDS:
        try:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Ответить пользователю", callback_data=f"reply_to_user_{user_id}")],
                [InlineKeyboardButton(text="📋 Все сообщения", callback_data="admin_support_messages")]
            ])
            await message.bot.send_message(
                admin_id,
                f"📩 <b>Новое сообщение от пользователя</b>\n\n"
                f"👤 ID: {user_id}\n"
                f"👤 Username: @{message.from_user.username or 'нет'}\n"
                f"📝 Сообщение: {text[:200]}",
                parse_mode="HTML",
                reply_markup=keyboard
            )
        except Exception as e:
            print(f"Ошибка уведомления админа {admin_id}: {e}")
    
    await message.answer("✅ Ваше сообщение отправлено администратору. Ответ придёт сюда в ближайшее время.")

# ---------- ОТВЕТ ПОЛЬЗОВАТЕЛЮ ----------
@router.callback_query(F.data.startswith("reply_to_user_"))
async def reply_to_user(callback: types.CallbackQuery, state: FSMContext):
    # Извлекаем user_id из callback_data
    user_id = int(callback.data.replace("reply_to_user_", ""))
    await state.update_data(reply_user_id=user_id)
    # Устанавливаем состояние ожидания ответа
    await state.set_state(AdminStates.waiting_for_reply_message)
    # Отвечаем в чат админу
    await callback.message.answer(f"✍️ Введите ответ для пользователя {user_id} (ответ получит ТОЛЬКО этот пользователь):")
    await callback.answer()

@router.message(AdminStates.waiting_for_reply_message, F.text)
async def send_reply_to_user(message: types.Message, state: FSMContext):
    data = await state.get_data()
    target_user_id = data.get("reply_user_id")
    reply_text = message.text
    
    try:
        # Отправляем ответ ТОЛЬКО конкретному пользователю
        await message.bot.send_message(
            target_user_id,
            f"📨 <b>Ответ от администратора:</b>\n\n{reply_text}",
            parse_mode="HTML"
        )
        await message.answer(f"✅ Ответ отправлен пользователю {target_user_id}")
    except Exception as e:
        await message.answer(f"❌ Не удалось отправить ответ: {e}")
    
    # Очищаем состояние
    await state.clear()
    # Показываем админ-панель
    await message.answer("👑 Админ-панель\n\nВыберите действие:", reply_markup=admin_main_keyboard())

# ---------- ПРОСМОТР НЕПРОЧИТАННЫХ СООБЩЕНИЙ ----------
@router.callback_query(F.data == "admin_support_messages")
async def admin_support_messages(callback: types.CallbackQuery):
    messages = get_unread_support_messages()
    
    # Клавиатура для возврата в админ-панель
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
        text += f"👤 ID: {user_id}\n📅 {date}\n📝 Сообщение: {msg[:200]}\n"
        text += f"➡️ Чтобы ответить, нажмите на кнопку в уведомлении выше\n\n"
    
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=back_keyboard)
    await callback.answer()