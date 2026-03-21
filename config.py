import os

# Токены ботов (обязательно задать в окружении Render)
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_BOT_TOKEN = os.getenv('ADMIN_BOT_TOKEN')
SUPPORT_BOT_TOKEN = os.getenv('SUPPORT_BOT_TOKEN')
CRYPTOBOT_TOKEN = os.getenv('CRYPTOBOT_TOKEN')

# Для удобства – alias для основного токена
MAIN_BOT_TOKEN = BOT_TOKEN

# ID администратора
ADMIN_IDS_STR = os.getenv('ADMIN_IDS', '')
ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_STR.split(',') if x.strip()]

# Username основного бота
MAIN_BOT_USERNAME = "GamesAsino_bot"

# Константы для игр
WIN_REDUCTION_FACTOR = 0.05