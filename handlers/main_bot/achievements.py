import asyncio
from aiogram import Bot
from database import execute_query, get_user

async def check_achievements(user_id: int, bot: Bot):
    try:
        print(">>> check_achievements вызван для", user_id)
        user = await get_user(user_id)
    except Exception as e:
        print(f"Ошибка получения пользователя в achievements: {e}")
        return

    (balance, total_games, wins, level, exp, theme, dbl, daily_streak, ts,
     agreed, has_started, referral_count, referral_earnings,
     current_win_streak, max_win_streak, withdrawals_count) = user

    # Получаем существующие достижения из PostgreSQL
    rows = await execute_query(
        "SELECT achievement_id FROM achievements WHERE user_id = $1",
        user_id, fetch_all=True
    )
    existing = {row[0] for row in rows} if rows else set()
    new_achievements = []

    # Первая победа
    if wins >= 1 and 'first_win' not in existing:
        new_achievements.append(('first_win', "Первая победа", 50))
    # 10 побед
    if wins >= 10 and '10_wins' not in existing:
        new_achievements.append(('10_wins', "10 побед", 200))
    # 100 игр
    if total_games >= 100 and '100_games' not in existing:
        new_achievements.append(('100_games', "100 игр", 300))
    # Серии побед
    if max_win_streak >= 3 and 'streak_3' not in existing:
        new_achievements.append(('streak_3', "Везунчик (3 победы подряд)", 100))
    if max_win_streak >= 5 and 'streak_5' not in existing:
        new_achievements.append(('streak_5', "Удачливый (5 побед подряд)", 250))
    if max_win_streak >= 10 and 'streak_10' not in existing:
        new_achievements.append(('streak_10', "Непобедимый (10 побед подряд)", 500))
    # Ежедневный бонус
    if daily_streak >= 7 and 'daily_7' not in existing:
        new_achievements.append(('daily_7', "Бонус-хантер (7 дней бонуса подряд)", 200))
    # Рефералы
    if referral_count >= 1 and 'ref_1' not in existing:
        new_achievements.append(('ref_1', "Друг человека (1 приглашённый)", 100))
    if referral_count >= 3 and 'ref_3' not in existing:
        new_achievements.append(('ref_3', "Популярный (3 приглашённых)", 300))
    if referral_count >= 5 and 'ref_5' not in existing:
        new_achievements.append(('ref_5', "Лидер (5 приглашённых)", 500))
    # Богач
    if balance >= 5000 and 'rich_5000' not in existing:
        new_achievements.append(('rich_5000', "Богач (5000 баллов)", 400))
    # Игроман
    if total_games >= 500 and 'games_500' not in existing:
        new_achievements.append(('games_500', "Игроман (500 игр)", 600))
    # Турнирный боец
    tournament_count = await execute_query(
        "SELECT COUNT(DISTINCT tournament_id) FROM tournament_participants WHERE user_id = $1",
        user_id, fetch_val=True
    ) or 0
    if tournament_count >= 5 and 'tournament_5' not in existing:
        new_achievements.append(('tournament_5', "Турнирный боец (5 турниров)", 350))

    if new_achievements:
        total_bonus = 0
        for ach_id, name, prize in new_achievements:
            try:
                await execute_query(
                    "INSERT INTO achievements (user_id, achievement_id) VALUES ($1, $2) ON CONFLICT (user_id, achievement_id) DO NOTHING",
                    user_id, ach_id
                )
                total_bonus += prize
            except Exception as e:
                print(f"Ошибка добавления достижения {ach_id}: {e}")
        if total_bonus > 0:
            await execute_query(
                "UPDATE users SET balance = balance + $1 WHERE user_id = $2",
                total_bonus, user_id
            )
            text = "🏆 Новые достижения:\n" + "\n".join(f"• {name} +{prize} 💎" for _, name, prize in new_achievements)
            await bot.send_message(user_id, text)