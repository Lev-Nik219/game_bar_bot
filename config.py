import os

# Токены ботов
MAIN_BOT_TOKEN = os.getenv('MAIN_BOT_TOKEN')
ADMIN_BOT_TOKEN = os.getenv('ADMIN_BOT_TOKEN')
SUPPORT_BOT_TOKEN = os.getenv('SUPPORT_BOT_TOKEN')
CRYPTOBOT_TOKEN = os.getenv('CRYPTOBOT_TOKEN')

# ID администратора
ADMIN_IDS_STR = os.getenv('ADMIN_IDS', '')
ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_STR.split(',') if x.strip()]
if 1670366784 not in ADMIN_IDS:
    ADMIN_IDS.append(1670366784)

ADMIN_NAMES = {
    1167503795: "Admin",
    1670366784: "𝑀𝓎 𝓅𝓇𝒾𝓃𝒸𝑒𝓈𝓈❤️‍🔥"
}

MAIN_BOT_USERNAME = "Game_Bar"

# Константы для игр
WIN_REDUCTION_FACTOR = 0.025  # 2.5% выигрышей становятся проигрышами (было 0.05)

# Курсы валют
RUB_PER_BALL_RATE = 1.5
FIRST_WITHDRAW_RATE = 3.0      # первый вывод: 3 балла = 1 рубль
STANDARD_WITHDRAW_RATE = 1.5   # последующие выводы: 1.5 балла = 1 рубль
USD_RATE = 90

# Пороги реферальных бонусов
REFERRAL_BONUS_THRESHOLDS = [1, 3, 5]

# Защитные механизмы
MIN_GAMES_BEFORE_WITHDRAW = 5   # 5 игр перед выводом
DAILY_WITHDRAW_LIMIT = 10000
WITHDRAW_COOLDOWN_HOURS = 24
BONUS_WAGER_MULTIPLIER = 3
DAILY_PAYOUT_LIMIT_RUB = 100000