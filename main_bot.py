#!/usr/bin/env python3
import asyncio
import logging
import os
import time
import json
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeDefault
from flask import Flask, request, jsonify

from config import MAIN_BOT_TOKEN
from database import create_db, init_db_pool, close_db_pool, get_user, update_balance, update_stats, save_game_history
from handlers.main_bot import (
    profile_router, payments_router, fallback_router, bot_info_router
)
from handlers.main_bot.cashback import router as cashback_router
from handlers.main_bot.achievements import check_achievements
from middlewares import UserStatusMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- Flask для API Mini App ----------
flask_app = Flask(__name__)

def _add_cors_headers(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
    response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS, GET')
    return response

def _build_cors_preflight_response():
    response = jsonify({'success': True})
    return _add_cors_headers(response)

@flask_app.route('/api/get_balance', methods=['POST', 'OPTIONS', 'GET'])
def api_get_balance():
    if request.method == 'OPTIONS':
        return _build_cors_preflight_response()
    
    try:
        if request.method == 'GET':
            user_id = request.args.get('user_id')
        else:
            data = request.get_json()
            user_id = data.get('user_id') if data else None
        
        if not user_id:
            return jsonify({'success': False, 'error': 'user_id required'}), 400
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        user_data = loop.run_until_complete(get_user(int(user_id), None))
        loop.close()
        
        balance = user_data[0]
        bonus_total = user_data[2] if len(user_data) > 2 else 0
        
        response = jsonify({
            'success': True,
            'balance': balance,
            'bonus_total': bonus_total
        })
        return _add_cors_headers(response)
    except Exception as e:
        logger.error(f"Ошибка в api_get_balance: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@flask_app.route('/api/game_result', methods=['POST', 'OPTIONS'])
def api_game_result():
    if request.method == 'OPTIONS':
        return _build_cors_preflight_response()
    
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        game = data.get('game')
        bet = data.get('bet')
        win = data.get('win')
        win_amount = data.get('win_amount', 0)
        details = data.get('details', {})
        
        if not user_id or not game or bet is None:
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        user_data = loop.run_until_complete(get_user(int(user_id), None))
        current_balance = user_data[0]
        
        if win:
            new_balance = current_balance + win_amount
        else:
            new_balance = current_balance - bet
        
        loop.run_until_complete(update_balance(int(user_id), new_balance))
        loop.run_until_complete(update_stats(int(user_id), win=win))
        loop.run_until_complete(save_game_history(int(user_id), bet, win_amount if win else 0, game))
        
        async def check_achievements_async():
            await check_achievements(int(user_id), None)
        loop.run_until_complete(check_achievements_async())
        
        loop.close()
        
        response = jsonify({
            'success': True,
            'new_balance': new_balance,
            'win': win,
            'win_amount': win_amount if win else 0
        })
        return _add_cors_headers(response)
    except Exception as e:
        logger.error(f"Ошибка в api_game_result: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@flask_app.route('/health', methods=['GET'])
def health():
    return _add_cors_headers(jsonify({'status': 'ok'}))

def run_flask():
    port = int(os.environ.get('PORT', 10000))
    flask_app.run(host='0.0.0.0', port=port, debug=False)

# ---------- HTTP сервер для healthcheck ----------
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health' or self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')
        else:
            self.send_response(404)
        self.end_headers()
    
    def log_message(self, format, *args):
        pass

def run_health_server():
    port = int(os.environ.get('HEALTH_PORT', 10001))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    server.serve_forever()

# ---------- Telegram Bot ----------
bot = Bot(token=MAIN_BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

dp.message.middleware(UserStatusMiddleware())

# Подключаем только нужные роутеры (без игр и турниров)
dp.include_router(profile_router)
dp.include_router(payments_router)
dp.include_router(bot_info_router)
dp.include_router(cashback_router)
dp.include_router(fallback_router)

@dp.errors()
async def global_error_handler(event: types.ErrorEvent):
    logger.error(f"Глобальная ошибка: {event.exception}", exc_info=True)
    return True

async def on_startup():
    await init_db_pool()
    await create_db()
    commands = [
        BotCommand(command="start", description="Запустить бота"),
        BotCommand(command="myid", description="Мой Telegram ID"),
    ]
    await bot.set_my_commands(commands, scope=BotCommandScopeDefault())
    logger.info("База данных готова, команды установлены, бот запущен.")

async def main():
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()
    
    await asyncio.sleep(1)
    
    await bot.delete_webhook()
    
    dp.startup.register(on_startup)
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())