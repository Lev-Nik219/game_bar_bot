# keyboards.py - полный исправленный файл

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

def main_reply_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text="🎰 Сыграть"), KeyboardButton(text="👤 Мой профиль")],
        [KeyboardButton(text="🏆 Турниры"), KeyboardButton(text="ℹ️ О боте")],
        [KeyboardButton(text="🎁 Ежедневный бонус")],
        [KeyboardButton(text="👥 Пригласить друга")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def agreement_short_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📖 Читать полное соглашение", callback_data="read_full_agreement")],
        [InlineKeyboardButton(text="🎮 Демо-режим", callback_data="demo_mode")]
    ])

def agreement_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принять", callback_data="accept_agreement")],
        [InlineKeyboardButton(text="🎮 Демо-режим", callback_data="demo_mode")]
    ])

def bot_info_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❓ FAQ", callback_data="bot_info_faq")],
        [InlineKeyboardButton(text="👨‍💼 Связаться с администратором", callback_data="contact_admin")],
        [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_menu")]
    ])

def games_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎰 Слоты", callback_data="game_slots"),
            InlineKeyboardButton(text="🎡 Рулетка", callback_data="game_roulette"),
            InlineKeyboardButton(text="🎲 Кости", callback_data="game_dice")
        ],
        [
            InlineKeyboardButton(text="🃏 Блэкджек", callback_data="game_blackjack"),
            InlineKeyboardButton(text="🎳 Боулинг", callback_data="game_bowling"),
            InlineKeyboardButton(text="🎯 Дартс", callback_data="game_darts")
        ],
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

def deposit_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1000 баллов = 1000 руб (≈11.11 USDT)", callback_data="deposit_1000")],
        [InlineKeyboardButton(text="750 баллов = 750 руб (≈8.33 USDT)", callback_data="deposit_750")],
        [InlineKeyboardButton(text="500 баллов = 500 руб (≈5.56 USDT)", callback_data="deposit_500")],
        [InlineKeyboardButton(text="250 баллов = 250 руб (≈2.78 USDT)", callback_data="deposit_250")],
        [InlineKeyboardButton(text="💰 Другая сумма", callback_data="deposit_custom")],
        [InlineKeyboardButton(text="🔙 Назад в профиль", callback_data="profile")]
    ])
# Новая клавиатура для подтверждения оплаты
def payment_confirmation_keyboard(payment_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"check_payment_{payment_id}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="deposit")]
    ])

def back_to_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])

def quick_bet_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔟", callback_data="bet_10"),
         InlineKeyboardButton(text="5️⃣0️⃣", callback_data="bet_50"),
         InlineKeyboardButton(text="1️⃣0️⃣0️⃣", callback_data="bet_100")],
        [InlineKeyboardButton(text="5️⃣0️⃣0️⃣", callback_data="bet_500"),
         InlineKeyboardButton(text="✏️ Своя сумма", callback_data="bet_custom")],
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="cancel_bet")]
    ])

def roulette_choice_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔴 Красное", callback_data="roulette_color_red"),
         InlineKeyboardButton(text="⚫ Черное", callback_data="roulette_color_black")],
        [InlineKeyboardButton(text="🟢 Зеленое (0)", callback_data="roulette_color_green"),
         InlineKeyboardButton(text="🟡 Четное", callback_data="roulette_parity_even")],
        [InlineKeyboardButton(text="🔵 Нечетное", callback_data="roulette_parity_odd"),
         InlineKeyboardButton(text="🎯 Конкретное число", callback_data="roulette_specific")],
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="cancel_bet")]
    ])

def blackjack_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎯 Взять карту", callback_data="bj_hit")],
        [InlineKeyboardButton(text="✋ Хватит", callback_data="bj_stand")],
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="cancel_bet")]
    ])

def bowling_choice_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬆️ Больше 3", callback_data="bowling_over"),
         InlineKeyboardButton(text="⬇️ Меньше 4", callback_data="bowling_under")],
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="cancel_bet")]
    ])

def darts_choice_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟡 Четное", callback_data="darts_even"),
         InlineKeyboardButton(text="🔵 Нечетное", callback_data="darts_odd")],
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="cancel_bet")]
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

def demo_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 Вернуться в демо‑меню", callback_data="demo_mode")],
        [InlineKeyboardButton(text="✅ Принять соглашение", callback_data="accept_agreement")]
    ])