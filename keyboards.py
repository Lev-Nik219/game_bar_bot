from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo

def main_reply_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    webapp_url = f"https://game-bar-web.vercel.app?user_id={user_id}"
    
    keyboard = [
        [KeyboardButton(text="🎮 Играть в Game Bar Casino", web_app=WebAppInfo(url=webapp_url))],
        [KeyboardButton(text="👤 Мой профиль"), KeyboardButton(text="📺 Заработать монеты")],
        [KeyboardButton(text="ℹ️ О боте"), KeyboardButton(text="👥 Пригласить друга")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def deposit_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура пополнения с новыми ценами в USDT"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1000 баллов = 65 USDT", callback_data="deposit_1000")],
        [InlineKeyboardButton(text="750 баллов = 50 USDT", callback_data="deposit_750")],
        [InlineKeyboardButton(text="500 баллов = 35 USDT", callback_data="deposit_500")],
        [InlineKeyboardButton(text="250 баллов = 20 USDT", callback_data="deposit_250")],
        [InlineKeyboardButton(text="💰 Другая сумма", callback_data="deposit_custom")],
        [InlineKeyboardButton(text="🔙 Назад в профиль", callback_data="profile")]
    ])

# Остальные клавиатуры остаются без изменений...
def agreement_short_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📖 Читать полное соглашение", callback_data="read_full_agreement")],
        [InlineKeyboardButton(text="✅ Принять соглашение", callback_data="accept_agreement")]
    ])

def agreement_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принять", callback_data="accept_agreement")]
    ])

def bot_info_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❓ FAQ", callback_data="bot_info_faq")],
        [InlineKeyboardButton(text="👨‍💼 Связаться с администратором", callback_data="contact_admin")],
        [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_menu")]
    ])

def profile_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="deposit")],
        [InlineKeyboardButton(text="💸 Вывести средства", callback_data="withdraw")],
        [InlineKeyboardButton(text="🏆 Достижения", callback_data="achievements")],
        [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_menu")]
    ])

def achievements_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Все достижения", callback_data="achievements_all")],
        [InlineKeyboardButton(text="🏆 Мои достижения", callback_data="achievements_my")],
        [InlineKeyboardButton(text="🔙 Назад в профиль", callback_data="profile")]
    ])

def achievements_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="achievements_menu")]
    ])

def back_to_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])

def admin_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Начислить баллы", callback_data="admin_give"),
         InlineKeyboardButton(text="➖ Забрать баллы", callback_data="admin_take")],
        [InlineKeyboardButton(text="👁 Информация о пользователе", callback_data="admin_userinfo"),
         InlineKeyboardButton(text="👥 Список игроков", callback_data="admin_list")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="💸 Новые заявки на вывод", callback_data="admin_withdraw_requests"),
         InlineKeyboardButton(text="📜 Общие заявки на вывод", callback_data="admin_withdraw_history")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast"),
         InlineKeyboardButton(text="🏆 Создать турнир", callback_data="admin_create_tournament")],
    ])

def admin_stats_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Общая статистика", callback_data="admin_stats_main")],
        [InlineKeyboardButton(text="💸 Статистика выводов", callback_data="admin_stats_withdrawals")],
        [InlineKeyboardButton(text="💰 Статистика пополнений", callback_data="admin_stats_deposits")],
        [InlineKeyboardButton(text="👤 Статистика пользователя", callback_data="admin_stats_user")],
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