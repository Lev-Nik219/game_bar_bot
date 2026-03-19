import aiosqlite
import time
import random
import asyncio

DB_NAME = "casino.db"

async def create_db():
    async with aiosqlite.connect(DB_NAME, timeout=30) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=30000")  # 30 секунд ожидания

        # Основная таблица пользователей
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                balance INTEGER DEFAULT 0,
                bonus_total INTEGER DEFAULT 0,
                total_games INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                last_active INTEGER DEFAULT 0,
                invited_by INTEGER DEFAULT NULL,
                referral_bonus_claimed INTEGER DEFAULT 0,
                friend_played INTEGER DEFAULT 0,
                level INTEGER DEFAULT 1,
                exp INTEGER DEFAULT 0,
                theme TEXT DEFAULT 'classic',
                daily_bonus_last INTEGER DEFAULT 0,
                daily_bonus_streak INTEGER DEFAULT 0,
                tournament_score INTEGER DEFAULT 0,
                created_at INTEGER DEFAULT (strftime('%s','now')),
                agreed INTEGER DEFAULT 0,
                has_started INTEGER DEFAULT 0,
                referral_count INTEGER DEFAULT 0,
                referral_earnings INTEGER DEFAULT 0,
                current_win_streak INTEGER DEFAULT 0,
                max_win_streak INTEGER DEFAULT 0
            )
        ''')
        try:
            await db.execute("ALTER TABLE users ADD COLUMN withdrawals_count INTEGER DEFAULT 0;")
            await db.commit()
        except aiosqlite.OperationalError:
            pass

        # Достижения
        await db.execute('''
            CREATE TABLE IF NOT EXISTS achievements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                achievement_id TEXT NOT NULL,
                achieved_at INTEGER DEFAULT (strftime('%s','now')),
                UNIQUE(user_id, achievement_id),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')
        # Турниры
        await db.execute('''
            CREATE TABLE IF NOT EXISTS tournaments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                prize_points INTEGER NOT NULL,
                start_time INTEGER NOT NULL,
                end_time INTEGER NOT NULL,
                status TEXT DEFAULT 'pending',
                winner_id INTEGER DEFAULT NULL,
                winner_username TEXT DEFAULT NULL,
                winner_notified INTEGER DEFAULT 0,
                created_at INTEGER DEFAULT (strftime('%s','now'))
            )
        ''')
        # Участники турниров
        await db.execute('''
            CREATE TABLE IF NOT EXISTS tournament_participants (
                tournament_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                score INTEGER DEFAULT 0,
                registered INTEGER DEFAULT 0,
                last_update INTEGER DEFAULT (strftime('%s','now')),
                PRIMARY KEY (tournament_id, user_id),
                FOREIGN KEY (tournament_id) REFERENCES tournaments(id),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')
        # Переписка с администратором
        await db.execute('''
            CREATE TABLE IF NOT EXISTS admin_chats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                admin_id INTEGER NOT NULL,
                last_message_time INTEGER DEFAULT (strftime('%s','now')),
                UNIQUE(user_id, admin_id)
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS admin_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                from_user INTEGER NOT NULL,
                message TEXT,
                is_reply INTEGER DEFAULT 0,
                timestamp INTEGER DEFAULT (strftime('%s','now')),
                FOREIGN KEY (chat_id) REFERENCES admin_chats(id)
            )
        ''')
        # Реферальные уровни
        await db.execute('''
            CREATE TABLE IF NOT EXISTS referral_levels (
                user_id INTEGER PRIMARY KEY,
                level INTEGER DEFAULT 1,
                commission_rate REAL DEFAULT 0.05,
                total_earned INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')
        # Депозиты
        await db.execute('''
            CREATE TABLE IF NOT EXISTS deposits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                created_at INTEGER DEFAULT (strftime('%s','now')),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')
        # Праздничные события
        await db.execute('''
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                multiplier REAL DEFAULT 1.0,
                start_date INTEGER NOT NULL,
                end_date INTEGER NOT NULL,
                active INTEGER DEFAULT 1
            )
        ''')
        # Уведомления
        await db.execute('''
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                created_at INTEGER DEFAULT (strftime('%s','now')),
                read INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')
        # Розыгрыши
        await db.execute('''
            CREATE TABLE IF NOT EXISTS giveaways (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                prize INTEGER NOT NULL,
                start_time INTEGER NOT NULL,
                end_time INTEGER NOT NULL,
                max_winners INTEGER DEFAULT 1,
                status TEXT DEFAULT 'pending',
                created_by INTEGER,
                created_at INTEGER DEFAULT (strftime('%s','now'))
            )
        ''')
        # Участники розыгрышей
        await db.execute('''
            CREATE TABLE IF NOT EXISTS giveaway_participants (
                giveaway_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                joined_at INTEGER DEFAULT (strftime('%s','now')),
                PRIMARY KEY (giveaway_id, user_id),
                FOREIGN KEY (giveaway_id) REFERENCES giveaways(id),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')
        # Партнёры
        await db.execute('''
            CREATE TABLE IF NOT EXISTS partners (
                user_id INTEGER PRIMARY KEY,
                referral_link TEXT UNIQUE,
                commission_rate REAL DEFAULT 0.10,
                total_earned INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')
        # Крипто-транзакции
        await db.execute('''
            CREATE TABLE IF NOT EXISTS crypto_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount_rub INTEGER NOT NULL,
                amount_points INTEGER NOT NULL,
                payment_id TEXT UNIQUE NOT NULL,
                invoice_id TEXT,
                status TEXT DEFAULT 'pending',
                created_at INTEGER DEFAULT (strftime('%s','now')),
                confirmed_at INTEGER,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')
        # Заявки на вывод
        await db.execute('''
            CREATE TABLE IF NOT EXISTS withdraw_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount_points INTEGER NOT NULL,
                amount_usdt REAL NOT NULL,
                wallet_address TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at INTEGER DEFAULT (strftime('%s','now')),
                completed_at INTEGER,
                admin_comment TEXT,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')
        # Таблица согласий
        await db.execute('''
            CREATE TABLE IF NOT EXISTS agreements (
                user_id INTEGER PRIMARY KEY,
                agreed_at INTEGER NOT NULL,
                ip_address TEXT,
                user_agent TEXT
            )
        ''')
        await db.commit()

async def execute_with_retry(coro_func, *args, max_attempts=20, base_delay=0.1):
    """
    Универсальная функция для повторных попыток при блокировке БД.
    coro_func – асинхронная функция, возвращающая корутину.
    """
    for attempt in range(max_attempts):
        try:
            return await coro_func(*args)
        except aiosqlite.OperationalError as e:
            if "locked" in str(e) and attempt < max_attempts - 1:
                delay = base_delay * (2 ** attempt)  # экспоненциальная задержка
                print(f"⚠️ БД заблокирована, повтор через {delay:.2f} сек (попытка {attempt+1}/{max_attempts})")
                await asyncio.sleep(delay)
            else:
                raise
        except Exception as e:
            # Другие ошибки не повторяем
            raise

# ---- Основные функции с повторными попытками ----

async def get_user(user_id: int, username: str = None, initial_balance: int = 0):
    async def _get_user():
        async with aiosqlite.connect(DB_NAME, timeout=30) as db:
            async with db.execute(
                "SELECT balance, total_games, wins, level, exp, theme, daily_bonus_last, daily_bonus_streak, tournament_score, agreed, has_started, referral_count, referral_earnings, current_win_streak, max_win_streak, withdrawals_count FROM users WHERE user_id = ?",
                (user_id,)
            ) as cursor:
                row = await cursor.fetchone()

            if row:
                (balance, total_games, wins, level, exp, theme, daily_bonus_last,
                 daily_bonus_streak, tournament_score, agreed, has_started,
                 referral_count, referral_earnings, current_win_streak, max_win_streak,
                 withdrawals_count) = row
                await db.execute(
                    "UPDATE users SET last_active = ? WHERE user_id = ?",
                    (int(time.time()), user_id)
                )
                await db.commit()
                return (balance, total_games, wins, level, exp, theme, daily_bonus_last,
                        daily_bonus_streak, tournament_score, agreed, has_started,
                        referral_count, referral_earnings, current_win_streak, max_win_streak,
                        withdrawals_count)

            # Новый пользователь
            await db.execute(
                "INSERT INTO users (user_id, username, balance, last_active, agreed, has_started) VALUES (?, ?, ?, ?, 0, 0)",
                (user_id, username, initial_balance, int(time.time()))
            )
            await db.commit()
            return (initial_balance, 0, 0, 1, 0, 'classic', 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    return await execute_with_retry(_get_user)

async def get_bonus_total(user_id: int) -> int:
    async def _get_bonus_total():
        async with aiosqlite.connect(DB_NAME, timeout=30) as db:
            async with db.execute("SELECT bonus_total FROM users WHERE user_id = ?", (user_id,)) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0
    return await execute_with_retry(_get_bonus_total)

async def claim_daily_bonus(user_id: int) -> tuple[bool, int]:
    async def _claim_daily_bonus():
        async with aiosqlite.connect(DB_NAME, timeout=30) as db:
            async with db.execute(
                "SELECT daily_bonus_last, balance, bonus_total, daily_bonus_streak FROM users WHERE user_id = ?", (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return False, 0
                last_bonus, balance, bonus_total, streak = row

            now = int(time.time())
            today_start = now - (now % 86400)
            if last_bonus >= today_start:
                return False, balance

            new_balance = balance + 20
            new_bonus_total = bonus_total + 20
            new_streak = streak + 1
            await db.execute(
                "UPDATE users SET balance = ?, bonus_total = ?, daily_bonus_last = ?, daily_bonus_streak = ? WHERE user_id = ?",
                (new_balance, new_bonus_total, now, new_streak, user_id)
            )
            await db.commit()
            return True, new_balance
    return await execute_with_retry(_claim_daily_bonus)

async def update_balance(user_id: int, new_balance: int):
    async def _update_balance():
        async with aiosqlite.connect(DB_NAME, timeout=30) as db:
            await db.execute(
                "UPDATE users SET balance = ?, last_active = ? WHERE user_id = ?",
                (new_balance, int(time.time()), user_id)
            )
            await db.commit()
    await execute_with_retry(_update_balance)

async def update_stats(user_id: int, win: bool):
    async def _update_stats():
        async with aiosqlite.connect(DB_NAME, timeout=30) as db:
            async with db.execute(
                "SELECT exp, level, total_games, wins, current_win_streak, max_win_streak FROM users WHERE user_id = ?",
                (user_id,)
            ) as cursor:
                exp, level, total_games, wins, current_streak, max_streak = await cursor.fetchone()

            exp_gain = 10 + (5 if win else 0)
            new_exp = exp + exp_gain
            level_up = False
            while new_exp >= level * 100:
                new_exp -= level * 100
                level += 1
                level_up = True

            if win:
                new_streak = current_streak + 1
                new_max_streak = max(new_streak, max_streak)
                await db.execute(
                    "UPDATE users SET total_games = total_games + 1, wins = wins + 1, exp = ?, level = ?, last_active = ?, current_win_streak = ?, max_win_streak = ? WHERE user_id = ?",
                    (new_exp, level, int(time.time()), new_streak, new_max_streak, user_id)
                )
            else:
                new_streak = 0
                await db.execute(
                    "UPDATE users SET total_games = total_games + 1, exp = ?, level = ?, last_active = ?, current_win_streak = ? WHERE user_id = ?",
                    (new_exp, level, int(time.time()), new_streak, user_id)
                )
            await db.commit()
            return level_up
    return await execute_with_retry(_update_stats)

async def get_user_stats(user_id: int):
    async def _get_user_stats():
        async with aiosqlite.connect(DB_NAME, timeout=30) as db:
            async with db.execute(
                "SELECT balance, total_games, wins FROM users WHERE user_id = ?", (user_id,)
            ) as cursor:
                return await cursor.fetchone()
    return await execute_with_retry(_get_user_stats)

async def get_all_users(offset=0, limit=5, active_days=30):
    async def _get_all_users():
        async with aiosqlite.connect(DB_NAME, timeout=30) as db:
            if active_days == 0:
                async with db.execute(
                    "SELECT user_id, username, balance, total_games FROM users ORDER BY user_id LIMIT ? OFFSET ?",
                    (limit, offset)
                ) as cursor:
                    return await cursor.fetchall()
            else:
                threshold = int(time.time()) - active_days * 24 * 3600
                async with db.execute(
                    "SELECT user_id, username, balance, total_games FROM users WHERE last_active > ? ORDER BY user_id LIMIT ? OFFSET ?",
                    (threshold, limit, offset)
                ) as cursor:
                    return await cursor.fetchall()
    return await execute_with_retry(_get_all_users)

async def get_users_count(active_days=30):
    async def _get_users_count():
        async with aiosqlite.connect(DB_NAME, timeout=30) as db:
            if active_days == 0:
                async with db.execute("SELECT COUNT(*) FROM users") as cursor:
                    return (await cursor.fetchone())[0]
            else:
                threshold = int(time.time()) - active_days * 24 * 3600
                async with db.execute("SELECT COUNT(*) FROM users WHERE last_active > ?", (threshold,)) as cursor:
                    return (await cursor.fetchone())[0]
    return await execute_with_retry(_get_users_count)

async def set_user_agreed(user_id: int):
    async def _set_user_agreed():
        async with aiosqlite.connect(DB_NAME, timeout=30) as db:
            await db.execute("UPDATE users SET agreed = 1 WHERE user_id = ?", (user_id,))
            await db.commit()
            print(f"✅ set_user_agreed({user_id}) выполнено")
    await execute_with_retry(_set_user_agreed)

async def is_user_agreed(user_id: int) -> bool:
    async def _is_user_agreed():
        async with aiosqlite.connect(DB_NAME, timeout=30) as db:
            async with db.execute("SELECT agreed FROM users WHERE user_id = ?", (user_id,)) as cursor:
                row = await cursor.fetchone()
                result = row and row[0] == 1
                print(f"🔍 is_user_agreed({user_id}) = {result} (данные: {row})")
                return result
    return await execute_with_retry(_is_user_agreed)

async def set_user_started(user_id: int):
    async def _set_user_started():
        async with aiosqlite.connect(DB_NAME, timeout=30) as db:
            await db.execute("UPDATE users SET has_started = 1 WHERE user_id = ?", (user_id,))
            await db.commit()
            print(f"✅ set_user_started({user_id}) выполнено")
    await execute_with_retry(_set_user_started)

async def increment_referral_count(inviter_id: int):
    async def _increment_referral_count():
        async with aiosqlite.connect(DB_NAME, timeout=30) as db:
            await db.execute("UPDATE users SET referral_count = referral_count + 1 WHERE user_id = ?", (inviter_id,))
            await db.commit()
    await execute_with_retry(_increment_referral_count)

async def add_referral_earnings(inviter_id: int, amount: int):
    async def _add_referral_earnings():
        async with aiosqlite.connect(DB_NAME, timeout=30) as db:
            await db.execute("UPDATE users SET referral_earnings = referral_earnings + ? WHERE user_id = ?", (amount, inviter_id))
            await db.commit()
    await execute_with_retry(_add_referral_earnings)

async def increment_withdrawals_count(user_id: int):
    async def _increment_withdrawals_count():
        async with aiosqlite.connect(DB_NAME, timeout=30) as db:
            await db.execute("UPDATE users SET withdrawals_count = withdrawals_count + 1 WHERE user_id = ?", (user_id,))
            await db.commit()
    await execute_with_retry(_increment_withdrawals_count)

async def check_referral_bonus(user_id: int, bot):
    async def _check_referral_bonus():
        async with aiosqlite.connect(DB_NAME, timeout=30) as db:
            async with db.execute("SELECT invited_by, friend_played FROM users WHERE user_id = ?", (user_id,)) as cursor:
                row = await cursor.fetchone()
            if row and row[0] is not None and row[1] == 0:
                invited_by = row[0]
                await db.execute("UPDATE users SET friend_played = 1 WHERE user_id = ?", (user_id,))
                await db.execute("UPDATE users SET balance = balance + 30 WHERE user_id = ?", (user_id,))
                await db.execute("UPDATE users SET balance = balance + 30 WHERE user_id = ?", (invited_by,))
                await db.commit()
                try:
                    await bot.send_message(user_id, "🎉 Поздравляем! Вы сыграли первую игру и получили 30 бонусных баллов!")
                    await bot.send_message(invited_by, "🎉 Ваш друг сыграл первую игру! Вы получаете 30 бонусных баллов!")
                except Exception:
                    pass
    await execute_with_retry(_check_referral_bonus)

async def get_active_tournament():
    async def _get_active_tournament():
        async with aiosqlite.connect(DB_NAME, timeout=30) as db:
            now = int(time.time())
            async with db.execute(
                "SELECT id, name, prize_points, end_time FROM tournaments WHERE status='active' AND start_time <= ? AND end_time > ?",
                (now, now)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return (row[0], row[1], row[2], row[3])
                return None
    return await execute_with_retry(_get_active_tournament)

async def get_tournament_leaders(tournament_id, limit=10):
    async def _get_tournament_leaders():
        async with aiosqlite.connect(DB_NAME, timeout=30) as db:
            async with db.execute(
                "SELECT tp.user_id, u.username, tp.score FROM tournament_participants tp "
                "JOIN users u ON tp.user_id = u.user_id "
                "WHERE tp.tournament_id = ? ORDER BY tp.score DESC LIMIT ?",
                (tournament_id, limit)
            ) as cursor:
                return await cursor.fetchall()
    return await execute_with_retry(_get_tournament_leaders)

async def register_for_tournament(user_id: int, tournament_id: int):
    async def _register_for_tournament():
        async with aiosqlite.connect(DB_NAME, timeout=30) as db:
            await db.execute(
                "INSERT INTO tournament_participants (tournament_id, user_id, registered) VALUES (?, ?, 1) "
                "ON CONFLICT(tournament_id, user_id) DO UPDATE SET registered = 1",
                (tournament_id, user_id)
            )
            await db.commit()
    await execute_with_retry(_register_for_tournament)

async def is_registered_for_tournament(user_id: int, tournament_id: int) -> bool:
    async def _is_registered_for_tournament():
        async with aiosqlite.connect(DB_NAME, timeout=30) as db:
            async with db.execute(
                "SELECT registered FROM tournament_participants WHERE tournament_id = ? AND user_id = ?",
                (tournament_id, user_id)
            ) as cursor:
                row = await cursor.fetchone()
                return row and row[0] == 1
    return await execute_with_retry(_is_registered_for_tournament)

async def get_user_tournaments(user_id: int, offset: int = 0, limit: int = 5):
    async def _get_user_tournaments():
        async with aiosqlite.connect(DB_NAME, timeout=30) as db:
            async with db.execute(
                "SELECT t.id, t.name, t.prize_points, t.start_time, t.end_time, tp.score, t.winner_id, t.winner_username "
                "FROM tournaments t "
                "JOIN tournament_participants tp ON t.id = tp.tournament_id "
                "WHERE tp.user_id = ? ORDER BY t.start_time DESC LIMIT ? OFFSET ?",
                (user_id, limit, offset)
            ) as cursor:
                return await cursor.fetchall()
    return await execute_with_retry(_get_user_tournaments)

async def count_user_tournaments(user_id: int) -> int:
    async def _count_user_tournaments():
        async with aiosqlite.connect(DB_NAME, timeout=30) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM tournament_participants WHERE user_id = ?",
                (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0
    return await execute_with_retry(_count_user_tournaments)

async def update_tournament_score(user_id: int, score_gain: int):
    async def _update_tournament_score():
        async with aiosqlite.connect(DB_NAME, timeout=30) as db:
            now = int(time.time())
            async with db.execute(
                "SELECT id FROM tournaments WHERE status = 'active' AND start_time <= ? AND end_time > ?",
                (now, now)
            ) as cursor:
                tournament = await cursor.fetchone()
            if tournament:
                tournament_id = tournament[0]
                await db.execute(
                    "INSERT INTO tournament_participants (tournament_id, user_id, score) VALUES (?, ?, ?) "
                    "ON CONFLICT(tournament_id, user_id) DO UPDATE SET score = score + ?, last_update = ?",
                    (tournament_id, user_id, score_gain, score_gain, now)
                )
                await db.commit()
    await execute_with_retry(_update_tournament_score)

async def finish_tournament(tournament_id: int, bot):
    async def _finish_tournament():
        async with aiosqlite.connect(DB_NAME, timeout=30) as db:
            async with db.execute(
                "SELECT name, prize_points, winner_id FROM tournaments WHERE id = ? AND status = 'active'",
                (tournament_id,)
            ) as cursor:
                tournament = await cursor.fetchone()
                if not tournament:
                    return
                name, prize, winner_already = tournament

            if winner_already is not None:
                return

            async with db.execute(
                "SELECT tp.user_id, u.username, tp.score FROM tournament_participants tp "
                "JOIN users u ON tp.user_id = u.user_id "
                "WHERE tp.tournament_id = ? ORDER BY tp.score DESC",
                (tournament_id,)
            ) as cursor:
                participants = await cursor.fetchall()

            if not participants:
                await db.execute(
                    "UPDATE tournaments SET status = 'finished' WHERE id = ?",
                    (tournament_id,)
                )
                await db.commit()
                return

            max_score = participants[0][2]
            top_users = [p for p in participants if p[2] == max_score]
            winner_id, winner_username, _ = random.choice(top_users)

            await db.execute(
                "UPDATE users SET balance = balance + ? WHERE user_id = ?",
                (prize, winner_id)
            )
            await db.execute(
                "UPDATE tournaments SET status = 'finished', winner_id = ?, winner_username = ? WHERE id = ?",
                (winner_id, winner_username, tournament_id)
            )
            await db.commit()

        try:
            await bot.send_message(
                winner_id,
                f"🏆 Поздравляем! Вы выиграли турнир «{name}» и получили {prize} 💎!"
            )
            from config import ADMIN_IDS
            for admin_id in ADMIN_IDS:
                await bot.send_message(
                    admin_id,
                    f"🏆 Турнир «{name}» завершён. Победитель: {winner_username} (ID {winner_id}) – {prize} 💎."
                )
        except Exception as e:
            print(f"Ошибка при отправке уведомления: {e}")
    await execute_with_retry(_finish_tournament)

async def add_deposit(user_id: int, amount: int):
    async def _add_deposit():
        async with aiosqlite.connect(DB_NAME, timeout=30) as db:
            await db.execute("INSERT INTO deposits (user_id, amount) VALUES (?, ?)", (user_id, amount))
            await db.commit()
    await execute_with_retry(_add_deposit)

async def get_event_multiplier():
    async def _get_event_multiplier():
        async with aiosqlite.connect(DB_NAME, timeout=30) as db:
            now = int(time.time())
            async with db.execute(
                "SELECT multiplier FROM events WHERE active = 1 AND start_date <= ? AND end_date > ?",
                (now, now)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 1.0
    return await execute_with_retry(_get_event_multiplier)

async def log_agreement(user_id: int, ip_address: str = None, user_agent: str = None):
    async def _log_agreement():
        async with aiosqlite.connect(DB_NAME, timeout=30) as db:
            # Гарантированно создаём таблицу, если её нет
            await db.execute('''
                CREATE TABLE IF NOT EXISTS agreements (
                    user_id INTEGER PRIMARY KEY,
                    agreed_at INTEGER NOT NULL,
                    ip_address TEXT,
                    user_agent TEXT
                )
            ''')
            await db.execute(
                "INSERT OR REPLACE INTO agreements (user_id, agreed_at, ip_address, user_agent) VALUES (?, ?, ?, ?)",
                (user_id, int(time.time()), ip_address, user_agent)
            )
            await db.execute("UPDATE users SET agreed = 1 WHERE user_id = ?", (user_id,))
            await db.commit()
    await execute_with_retry(_log_agreement)

async def check_agreement(user_id: int) -> bool:
    return await is_user_agreed(user_id)

async def get_bot_stats():
    async def _get_bot_stats():
        async with aiosqlite.connect(DB_NAME, timeout=30) as db:
            async with db.execute("SELECT MIN(created_at) FROM users") as cursor:
                first_date = (await cursor.fetchone())[0] or int(time.time())
            days = (int(time.time()) - first_date) // 86400
            async with db.execute("SELECT COUNT(*) FROM users") as cursor:
                total_users = (await cursor.fetchone())[0]
            now = time.time()
            today_start = int(now - (now % 86400))
            async with db.execute("SELECT COUNT(*) FROM users WHERE created_at >= ?", (today_start,)) as cursor:
                new_today = (await cursor.fetchone())[0]
            async with db.execute("SELECT SUM(total_games) FROM users") as cursor:
                total_games = (await cursor.fetchone())[0] or 0
            async with db.execute("SELECT SUM(amount_points) FROM withdraw_requests WHERE status='completed'") as cursor:
                total_paid = (await cursor.fetchone())[0] or 0
            return {"days": days, "total_users": total_users, "new_today": new_today, "total_games": total_games, "total_paid": total_paid}
    return await execute_with_retry(_get_bot_stats)