#!/usr/bin/env python3
import asyncio
import logging
import os
import json
import sqlite3
from aiogram import Bot, Dispatcher, types
from aiogram.types import BotCommand, BotCommandScopeDefault
from aiohttp import web

from config import MAIN_BOT_TOKEN
from handlers.main_bot import (
    profile_router, payments_router, fallback_router, bot_info_router
)
from handlers.main_bot.cashback import router as cashback_router
from middlewares import UserStatusMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_NAME = "casino.db"

def get_balance_sync(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else 0

def update_balance_sync(user_id: int, new_balance: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, user_id))
    conn.commit()
    conn.close()

def update_stats_sync(user_id: int, win: bool):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT total_games, wins FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row:
        total_games, wins = row
        new_total = total_games + 1
        new_wins = wins + (1 if win else 0)
        cursor.execute("UPDATE users SET total_games = ?, wins = ? WHERE user_id = ?", (new_total, new_wins, user_id))
    conn.commit()
    conn.close()

def save_game_history_sync(user_id: int, bet: int, win_amount: int, game_type: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO game_history (user_id, game_type, bet_amount, win_amount, played_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, game_type, bet, win_amount, int(time.time()))
    )
    conn.commit()
    conn.close()

# ---------- aiohttp сервер (и для webhook, и для API) ----------
app = web.Application()
bot = Bot(token=MAIN_BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

dp.message.middleware(UserStatusMiddleware())
dp.include_router(profile_router)
dp.include_router(payments_router)
dp.include_router(bot_info_router)
dp.include_router(cashback_router)
dp.include_router(fallback_router)

# API endpoints
async def handle_get_balance(request):
    try:
        data = await request.json()
        user_id = data.get('user_id')
        if not user_id:
            return web.json_response({'success': False, 'error': 'user_id required'}, status=400)
        balance = get_balance_sync(int(user_id))
        return web.json_response({'success': True, 'balance': balance, 'bonus_total': 0})
    except Exception as e:
        logger.error(f"Error in get_balance: {e}")
        return web.json_response({'success': False, 'error': str(e)}, status=500)

async def handle_game_result(request):
    try:
        data = await request.json()
        user_id = data.get('user_id')
        game = data.get('game')
        bet = data.get('bet')
        win = data.get('win')
        win_amount = data.get('win_amount', 0)
        
        if not user_id or not game or bet is None:
            return web.json_response({'success': False, 'error': 'Missing required fields'}, status=400)
        
        current_balance = get_balance_sync(int(user_id))
        new_balance = current_balance + win_amount if win else current_balance - bet
        
        update_balance_sync(int(user_id), new_balance)
        update_stats_sync(int(user_id), win)
        save_game_history_sync(int(user_id), bet, win_amount if win else 0, game)
        
        return web.json_response({'success': True, 'new_balance': new_balance, 'win': win, 'win_amount': win_amount if win else 0})
    except Exception as e:
        logger.error(f"Error in game_result: {e}")
        return web.json_response({'success': False, 'error': str(e)}, status=500)

async def health(request):
    return web.json_response({'status': 'ok'})

app.router.add_post('/api/get_balance', handle_get_balance)
app.router.add_post('/api/game_result', handle_game_result)
app.router.add_get('/health', health)
app.router.add_get('/', health)

@dp.errors()
async def global_error_handler(event: types.ErrorEvent):
    logger.error(f"Global error: {event.exception}", exc_info=True)
    return True

async def on_startup():
    commands = [
        BotCommand(command="start", description="Запустить бота"),
        BotCommand(command="myid", description="Мой Telegram ID"),
    ]
    await bot.set_my_commands(commands, scope=BotCommandScopeDefault())
    logger.info("Bot commands set")

async def on_shutdown():
    await bot.session.close()
    logger.info("Bot stopped")

async def handle_webhook(request):
    update = types.Update(**await request.json())
    await dp.feed_update(bot, update)
    return web.Response()

app.router.add_post('/webhook', handle_webhook)

async def main():
    port = int(os.environ.get('PORT', 10000))
    
    await on_startup()
    
    # Устанавливаем webhook
    webhook_url = f"https://game-bar-bot.onrender.com/webhook"
    await bot.delete_webhook()
    await bot.set_webhook(webhook_url)
    logger.info(f"Webhook set to {webhook_url}")
    
    # Запускаем aiohttp сервер
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"Server started on port {port}")
    
    try:
        await asyncio.Future()
    finally:
        await on_shutdown()

if __name__ == "__main__":
    asyncio.run(main())