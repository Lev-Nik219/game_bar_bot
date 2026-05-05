from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def admin_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Начислить баллы", callback_data="admin_give"),
         InlineKeyboardButton(text="➖ Забрать баллы", callback_data="admin_take")],
        [InlineKeyboardButton(text="👥 Список игроков", callback_data="admin_list")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="📩 Сообщения поддержки", callback_data="admin_support_messages")],
        [InlineKeyboardButton(text="💰 Запустить кэшбек", callback_data="admin_cashback")],
        [InlineKeyboardButton(text="🗑 Очистить базу", callback_data="admin_clear_db")],
    ])

def admin_stats_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Общая статистика", callback_data="admin_stats_main")],
        [InlineKeyboardButton(text="💰 Статистика пополнений", callback_data="admin_stats_deposits")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
    ])

def admin_stats_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад в меню статистики", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🔙 Назад в админ-панель", callback_data="admin_back")]
    ])

def users_list_keyboard(users, page, total_pages) -> InlineKeyboardMarkup:
    keyboard = []
    for uid, username, balance, total_games in users:
        name = f"@{username}" if username else f"ID {uid}"
        keyboard.append([InlineKeyboardButton(
            text=f"🆔 {uid} | {name} | 💎 {balance}",
            callback_data=f"user_info_{uid}"
        )])
    
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="◀️ Назад", callback_data="admin_list_prev"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data="admin_list_next"))
    if nav_row:
        keyboard.append(nav_row)
    keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def clear_db_confirm_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура подтверждения очистки базы"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚠️ ДА, ОЧИСТИТЬ ВСЁ", callback_data="admin_clear_db_confirm")],
        [InlineKeyboardButton(text="❌ ОТМЕНА", callback_data="admin_back")]
    ])

