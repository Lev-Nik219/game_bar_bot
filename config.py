import os

# Токены ботов (каждый сервис получает ТОЛЬКО свой)
MAIN_BOT_TOKEN = os.getenv('MAIN_BOT_TOKEN')
ADMIN_BOT_TOKEN = os.getenv('ADMIN_BOT_TOKEN')
SUPPORT_BOT_TOKEN = os.getenv('SUPPORT_BOT_TOKEN')
CRYPTOBOT_TOKEN = os.getenv('CRYPTOBOT_TOKEN')

# ID администратора (можно несколько через запятую)
ADMIN_IDS_STR = os.getenv('ADMIN_IDS', '')
ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_STR.split(',') if x.strip()]

# Username основного бота
MAIN_BOT_USERNAME = "CasinoMainBot"

# Константы для игр
WIN_REDUCTION_FACTOR = 0.05  # 5% выигрышей становятся проигрышами

# Курсы валют
RUB_PER_BALL_RATE = 1.5          # 1.5 рубля за 1 балл (при пополнении)
FIRST_WITHDRAW_RATE = 4.5        # первый вывод: 4.5 балла = 1 рубль
STANDARD_WITHDRAW_RATE = 2.0     # последующие выводы: 2 балла = 1 рубль
USD_RATE = 90                    # 1 USDT = 90 рублей