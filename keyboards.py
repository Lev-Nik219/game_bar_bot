from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def admin_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Начислить баллы", callback_data="admin_give"),
         InlineKeyboardButton(text="➖ Забрать баллы", callback_data="admin_take")],
        [InlineKeyboardButton(text="👤 Информация о пользователе / Список игроков", callback_data="admin_userinfo")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
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

def admin_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_cancel")]])

def admin_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]])

def admin_bot_choice_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤖 Основной бот", callback_data="broadcast_bot_main")],
        [InlineKeyboardButton(text="🔧 Админ-бот (текущий)", callback_data="broadcast_bot_admin")],
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_cancel")]
    ])