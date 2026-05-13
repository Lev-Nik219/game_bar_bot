#!/usr/bin/env python3
import asyncio
import logging
import os
import json
import sqlite3
import time
import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from config import MAIN_BOT_TOKEN, ADMIN_IDS
from database import init_db_pool, close_db_pool, create_db, execute_query
from handlers import user_router, admin_router, support_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_NAME = "casino.db"

AD_REWARD_AMOUNT = 25
FREE_BONUS_AMOUNT = 10
AD_COOLDOWN_SECONDS = 20

CRYPTOPAY_TOKEN = os.environ.get('CRYPTOPAY_TOKEN', '455143:AAPG9UlPyvoRj9opI3wL3KzmocGA5yz1lZd')
CRYPTOPAY_API_URL = 'https://pay.crypt.bot/api'

PRICE_LIST = {100:5, 250:20, 500:35, 750:50, 1000:65}

DAILY_BONUS_BASE = 10

SHOP_ITEMS = [
    {"id": "avatar_dog", "category": "avatars", "name": "🐶 Весёлый пёс", "desc": "Обычная аватарка", "price": 50, "type": "avatar", "emoji": "🐶"},
    {"id": "avatar_cat", "category": "avatars", "name": "🐱 Хитрый кот", "desc": "Обычная аватарка", "price": 50, "type": "avatar", "emoji": "🐱"},
    {"id": "avatar_frog", "category": "avatars", "name": "🐸 Лягушонок", "desc": "Обычная аватарка", "price": 50, "type": "avatar", "emoji": "🐸"},
    {"id": "avatar_monkey", "category": "avatars", "name": "🐵 Обезьянка", "desc": "Обычная аватарка", "price": 50, "type": "avatar", "emoji": "🐵"},
    {"id": "avatar_cow", "category": "avatars", "name": "🐮 Коровка", "desc": "Обычная аватарка", "price": 50, "type": "avatar", "emoji": "🐮"},
    {"id": "avatar_pig", "category": "avatars", "name": "🐷 Поросёнок", "desc": "Обычная аватарка", "price": 50, "type": "avatar", "emoji": "🐷"},
    {"id": "avatar_hamster", "category": "avatars", "name": "🐹 Хомяк", "desc": "Обычная аватарка", "price": 50, "type": "avatar", "emoji": "🐹"},
    {"id": "avatar_mouse", "category": "avatars", "name": "🐭 Мышонок", "desc": "Обычная аватарка", "price": 50, "type": "avatar", "emoji": "🐭"},
    {"id": "avatar_penguin", "category": "avatars", "name": "🐧 Пингвин", "desc": "Обычная аватарка", "price": 50, "type": "avatar", "emoji": "🐧"},
    {"id": "avatar_owl", "category": "avatars", "name": "🦉 Мудрая сова", "desc": "Обычная аватарка", "price": 50, "type": "avatar", "emoji": "🦉"},
    {"id": "avatar_fire_fox", "category": "avatars", "name": "🔥 Огненный лис", "desc": "Редкая аватарка", "price": 100, "type": "avatar", "emoji": "🔥🦊"},
    {"id": "avatar_ice_wolf", "category": "avatars", "name": "❄️ Ледяной волк", "desc": "Редкая аватарка", "price": 100, "type": "avatar", "emoji": "❄️🐺"},
    {"id": "avatar_butterfly", "category": "avatars", "name": "🦋 Радужная бабочка", "desc": "Редкая аватарка", "price": 100, "type": "avatar", "emoji": "🦋"},
    {"id": "avatar_rainbow_unicorn", "category": "avatars", "name": "🌈 Радужный единорог", "desc": "Легендарная аватарка", "price": 200, "type": "avatar", "emoji": "🌈🦄"},
    {"id": "avatar_octopus", "category": "avatars", "name": "🐙 Космический осьминог", "desc": "Легендарная аватарка", "price": 200, "type": "avatar", "emoji": "🐙👾"},
    {"id": "nickname_change", "category": "services", "name": "✏️ Смена никнейма", "desc": "Одноразовая смена (до 30 символов)", "price": 20, "type": "service"},
    {"id": "lucky_charm", "category": "boosts", "name": "🍀 Талисман удачи", "desc": "+5% к шансу выигрыша на 1 час", "price": 150, "type": "boost", "effect": "luck_5", "duration": 3600},
    {"id": "bet_insurance", "category": "boosts", "name": "💰 Страховка ставки", "desc": "50% возврат при проигрыше (1 раз)", "price": 100, "type": "boost", "effect": "insurance", "uses": 1},
]

ACHIEVEMENTS = {
    'first_game':{'name':'🎮 Первая игра','desc':'Сыграть первую игру','icon':'🎮','target':1},
    '10_games':{'name':'🎰 Игрок','desc':'Сыграть 10 игр','icon':'🎰','target':10},
    '50_games':{'name':'🎲 Завсегдатай','desc':'Сыграть 50 игр','icon':'🎲','target':50},
    '100_games':{'name':'🃏 Ветеран','desc':'Сыграть 100 игр','icon':'🃏','target':100},
    '500_games':{'name':'👑 Легенда','desc':'Сыграть 500 игр','icon':'👑','target':500},
    'first_win':{'name':'🍀 Первая победа','desc':'Одержать первую победу','icon':'🍀','target':1},
    '10_wins':{'name':'🏆 Победитель','desc':'Одержать 10 побед','icon':'🏆','target':10},
    '50_wins':{'name':'💪 Чемпион','desc':'Одержать 50 побед','icon':'💪','target':50},
    '100_wins':{'name':'🌟 Мастер','desc':'Одержать 100 побед','icon':'🌟','target':100},
    'big_win':{'name':'💰 Крупный выигрыш','desc':'Выиграть 500+ баллов за раз','icon':'💰','target':1},
    'balance_1000':{'name':'💎 Тысячник','desc':'Накопить 1000 баллов','icon':'💎','target':1},
    'balance_5000':{'name':'💵 Богач','desc':'Накопить 5000 баллов','icon':'💵','target':1},
    'depositor':{'name':'📥 Инвестор','desc':'Пополнить баланс','icon':'📥','target':1},
}

def execute_sqlite_with_retry(func, max_retries=5, delay=0.5):
    for attempt in range(max_retries):
        try: return func()
        except sqlite3.OperationalError as e:
            if 'locked' in str(e).lower() and attempt < max_retries - 1: time.sleep(delay * (attempt + 1))
            else: raise
    raise Exception("SQLite still locked")

def get_balance_sync(uid):
    def _do():
        conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
        c.execute("SELECT balance FROM users WHERE user_id=?",(uid,));r=c.fetchone();conn.close();return r[0] if r else 0
    return execute_sqlite_with_retry(_do)

def update_balance_sync(uid, bal):
    def _do():
        conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
        c.execute("UPDATE users SET balance=? WHERE user_id=?",(bal,uid));conn.commit();conn.close()
    execute_sqlite_with_retry(_do)

def update_stats_sync(uid, win):
    def _do():
        conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
        c.execute("SELECT total_games,wins FROM users WHERE user_id=?",(uid,));r=c.fetchone()
        if r: c.execute("UPDATE users SET total_games=?,wins=? WHERE user_id=?",(r[0]+1,r[1]+(1 if win else 0),uid))
        conn.commit();conn.close()
    execute_sqlite_with_retry(_do)

def get_user_stats_sync(uid):
    def _do():
        conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
        c.execute("SELECT balance,total_games,wins FROM users WHERE user_id=?",(uid,));r=c.fetchone();conn.close()
        return (r[0],r[1],r[2]) if r else (0,0,0)
    return execute_sqlite_with_retry(_do)

def save_game_history_sync(uid,bet,wa,game):
    def _do():
        conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
        c.execute("INSERT INTO game_history(user_id,game_type,bet_amount,win_amount,played_at) VALUES(?,?,?,?,?)",(uid,game,bet,wa,int(time.time())));conn.commit();conn.close()
    execute_sqlite_with_retry(_do)

def check_achievements_sync(uid,bal,tg,w,wa=0):
    def _do():
        conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS achievements(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,achievement_id TEXT NOT NULL,achieved_at INTEGER NOT NULL,UNIQUE(user_id,achievement_id))''')
        c.execute("SELECT achievement_id FROM achievements WHERE user_id=?",(uid,));existing={r[0] for r in c.fetchall()}
        checks={'first_game':tg>=1,'10_games':tg>=10,'50_games':tg>=50,'100_games':tg>=100,'500_games':tg>=500,'first_win':w>=1,'10_wins':w>=10,'50_wins':w>=50,'100_wins':w>=100,'big_win':wa>=500,'balance_1000':bal>=1000,'balance_5000':bal>=5000}
        new_achs=[];now=int(time.time())
        for aid,ach in checks.items():
            if ach and aid not in existing: c.execute("INSERT OR IGNORE INTO achievements(user_id,achievement_id,achieved_at) VALUES(?,?,?)",(uid,aid,now));new_achs.append(aid)
        conn.commit();conn.close();return new_achs
    return execute_sqlite_with_retry(_do)

def check_depositor_achievement(uid):
    def _do():
        conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS achievements(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,achievement_id TEXT NOT NULL,achieved_at INTEGER NOT NULL,UNIQUE(user_id,achievement_id))''')
        c.execute("INSERT OR IGNORE INTO achievements(user_id,achievement_id,achieved_at) VALUES(?,'depositor',?)",(uid,int(time.time())));conn.commit();conn.close()
    execute_sqlite_with_retry(_do)

def get_achievements_sync(uid):
    def _do():
        conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS achievements(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,achievement_id TEXT NOT NULL,achieved_at INTEGER NOT NULL,UNIQUE(user_id,achievement_id))''')
        c.execute("SELECT achievement_id,achieved_at FROM achievements WHERE user_id=? ORDER BY achieved_at DESC",(uid,));earned={r[0]:r[1] for r in c.fetchall()};conn.close();return earned
    return execute_sqlite_with_retry(_do)

def claim_daily_bonus_sync(uid):
    now=int(time.time());today_start=now-(now%86400)
    def _do():
        conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
        try: c.execute("ALTER TABLE users ADD COLUMN daily_bonus_last INTEGER DEFAULT 0")
        except: pass
        try: c.execute("ALTER TABLE users ADD COLUMN daily_bonus_streak INTEGER DEFAULT 0")
        except: pass
        c.execute("SELECT daily_bonus_last,daily_bonus_streak,balance FROM users WHERE user_id=?",(uid,));r=c.fetchone()
        if not r: conn.close();return None
        last,streak,bal=r[0] or 0,r[1] or 0,r[2]
        if last>=today_start: conn.close();return {'success':False,'error':'already_claimed','next':today_start+86400}
        yesterday=today_start-86400;new_streak=streak+1 if last>=yesterday else 1
        bonus=DAILY_BONUS_BASE+min(new_streak-1,7)*5
        new_bal=bal+bonus
        c.execute("UPDATE users SET daily_bonus_last=?,daily_bonus_streak=?,balance=? WHERE user_id=?",(now,new_streak,new_bal,uid))
        conn.commit();conn.close();return {'success':True,'bonus':bonus,'streak':new_streak,'new_balance':new_bal}
    return execute_sqlite_with_retry(_do)

def get_daily_bonus_status_sync(uid):
    now=int(time.time());today_start=now-(now%86400)
    def _do():
        conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
        c.execute("SELECT daily_bonus_last,daily_bonus_streak FROM users WHERE user_id=?",(uid,));r=c.fetchone()
        if not r: conn.close();return {'can_claim':True,'streak':0,'next_bonus':10}
        last,streak=r[0] or 0,r[1] or 0
        can=last<today_start;next_bonus=DAILY_BONUS_BASE+min(streak,7)*5
        conn.close();return {'can_claim':can,'streak':streak if last>=today_start-86400 else 0,'next_bonus':next_bonus}
    return execute_sqlite_with_retry(_do)

def get_last_ad_time_sync(uid):
    def _do():
        conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
        c.execute("SELECT last_ad_watch FROM users WHERE user_id=?",(uid,));r=c.fetchone();conn.close();return r[0] if r else 0
    return execute_sqlite_with_retry(_do)

def set_last_ad_time_sync(uid, ts):
    def _do():
        conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
        c.execute("UPDATE users SET last_ad_watch=? WHERE user_id=?",(ts,uid));conn.commit();conn.close()
    execute_sqlite_with_retry(_do)

def create_payment(user_id, amount_points, price_usdt, payment_id, invoice_id):
    def _do():
        conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
        c.execute("INSERT INTO crypto_payments(user_id,amount_points,price_usdt,payment_id,invoice_id,status,created_at) VALUES(?,?,?,?,?,'pending',?)",(user_id,amount_points,price_usdt,payment_id,invoice_id,int(time.time())));conn.commit();conn.close()
    execute_sqlite_with_retry(_do)

def confirm_payment(payment_id):
    def _do():
        conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
        c.execute("SELECT user_id,amount_points,status FROM crypto_payments WHERE payment_id=?",(payment_id,));r=c.fetchone()
        if not r or r[2]!='pending': conn.close();return None
        uid,amount,_=r
        c.execute("UPDATE crypto_payments SET status='paid' WHERE payment_id=?",(payment_id,))
        c.execute("SELECT balance FROM users WHERE user_id=?",(uid,));bal=c.fetchone()[0]
        c.execute("UPDATE users SET balance=? WHERE user_id=?",(bal+amount,uid))
        conn.commit();conn.close();check_depositor_achievement(uid);return (uid,amount)
    return execute_sqlite_with_retry(_do, max_retries=10, delay=0.3)

def init_sqlite_db():
    conn=sqlite3.connect(DB_NAME);c=conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY,username TEXT,balance INTEGER DEFAULT 0,total_games INTEGER DEFAULT 0,wins INTEGER DEFAULT 0,last_ad_watch INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS game_history(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,game_type TEXT NOT NULL,bet_amount INTEGER NOT NULL,win_amount INTEGER DEFAULT 0,played_at INTEGER NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS support_messages(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,message TEXT NOT NULL,created_at INTEGER NOT NULL,is_read INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS crypto_payments(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,amount_points INTEGER NOT NULL,price_usdt REAL NOT NULL,payment_id TEXT UNIQUE NOT NULL,invoice_id TEXT,status TEXT DEFAULT 'pending',created_at INTEGER NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS achievements(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,achievement_id TEXT NOT NULL,achieved_at INTEGER NOT NULL,UNIQUE(user_id,achievement_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS user_inventory(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,item_id TEXT NOT NULL,purchased_at INTEGER NOT NULL,used INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS active_boosts(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,boost_type TEXT NOT NULL,expires_at INTEGER NOT NULL,uses_left INTEGER DEFAULT 1)''')
    for col,typ in [('display_name','TEXT'),('avatar_emoji',"TEXT DEFAULT '🦊'"),('last_cashback','INTEGER DEFAULT 0'),('daily_bonus_last','INTEGER DEFAULT 0'),('daily_bonus_streak','INTEGER DEFAULT 0'),('exp','INTEGER DEFAULT 0')]:
        try: c.execute(f"ALTER TABLE users ADD COLUMN {col} {typ}")
        except: pass
    try: c.execute("ALTER TABLE users ADD COLUMN invited_by INTEGER DEFAULT NULL")
    except: pass
    conn.commit();conn.close()

bot=Bot(token=MAIN_BOT_TOKEN);storage=MemoryStorage();dp=Dispatcher(storage=storage)
dp.include_router(support_router);dp.include_router(admin_router);dp.include_router(user_router)

app=web.Application()
@web.middleware
async def cors_middleware(request,handler):
    if request.method=='OPTIONS':
        resp=web.Response();resp.headers['Access-Control-Allow-Origin']='*';resp.headers['Access-Control-Allow-Methods']='POST,GET,OPTIONS';resp.headers['Access-Control-Allow-Headers']='Content-Type,crypto-pay-api-sign';return resp
    resp=await handler(request);resp.headers['Access-Control-Allow-Origin']='*';return resp
app.middlewares.append(cors_middleware)

async def handle_get_balance(request):
    try:
        data=await request.json();uid=int(data.get('user_id'))
        if not uid: return web.json_response({'success':False,'error':'user_id required'},status=400)
        def _do():
            conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
            c.execute("SELECT balance FROM users WHERE user_id=?",(uid,));r=c.fetchone()
            if not r:
                c.execute("INSERT INTO users(user_id,balance,total_games,wins,avatar_emoji) VALUES(?,20,0,0,'🦊')",(uid,))
                conn.commit()
                async def sync_pg():
                    try: await execute_query("INSERT INTO users(user_id,balance,total_games,wins) VALUES($1,$2,$3,$4) ON CONFLICT(user_id) DO UPDATE SET balance=$2",uid,20,0,0)
                    except: pass
                asyncio.ensure_future(sync_pg())
                conn.close();return 20
            conn.close();return r[0]
        bal=execute_sqlite_with_retry(_do);return web.json_response({'success':True,'balance':bal})
    except Exception as e: return web.json_response({'success':False,'error':str(e)},status=500)

async def handle_get_profile(request):
    try:
        data=await request.json();uid=int(data.get('user_id'))
        if not uid: return web.json_response({'success':False,'error':'user_id required'},status=400)
        def _do():
            conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
            c.execute("SELECT balance,total_games,wins,COALESCE(exp,0),display_name,avatar_emoji FROM users WHERE user_id=?",(uid,));r=c.fetchone()
            if not r: conn.close();return None
            bal,tg,wins_val,exp_val,dn,av=r[0],r[1],r[2],r[3],r[4] if len(r)>4 else None,r[5] if len(r)>5 else '🦊'
            c.execute("SELECT game_type,bet_amount,win_amount,played_at FROM game_history WHERE user_id=? ORDER BY played_at DESC LIMIT 25",(uid,));games=c.fetchall();conn.close()
            return (bal,tg,wins_val,exp_val,dn,av,games)
        result=execute_sqlite_with_retry(_do)
        if not result: return web.json_response({'success':False,'error':'User not found'},status=404)
        bal,tg,wins_val,exp_val,dn,av,games=result;losses=tg-wins_val;wr=round(wins_val/tg*100,1) if tg>0 else 0
        if exp_val and exp_val > 0:
            level = 1; remaining = exp_val
            while remaining >= level * level * 500 and level < 10:
                remaining -= level * level * 500; level += 1
            exp_progress = remaining; exp_needed = level * level * 500
        else: level = 1; exp_progress = 0; exp_needed = 500
        rg=[{'game':g[0],'bet':g[1],'win_amount':g[2],'result':'win' if g[2]>0 else 'lose','time':g[3]} for g in games]
        return web.json_response({'success':True,'profile':{'user_id':uid,'balance':bal,'total_games':tg,'wins':wins_val,'losses':losses,'winrate':wr,'recent_games':rg,'display_name':dn,'avatar_emoji':av or '🦊','exp':exp_val,'level':level,'next_level_exp':(level+1)**2*500,'exp_progress':exp_progress,'exp_needed':exp_needed}})
    except Exception as e: return web.json_response({'success':False,'error':str(e)},status=500)

async def handle_get_achievements(request):
    try:
        data=await request.json();uid=int(data.get('user_id'))
        if not uid: return web.json_response({'success':False,'error':'user_id required'},status=400)
        bal,tg,w=get_user_stats_sync(uid);earned=get_achievements_sync(uid)
        all_a=[]
        for aid,ad in ACHIEVEMENTS.items():
            prog=0
            if aid in['first_game','10_games','50_games','100_games','500_games']: prog=tg
            elif aid in['first_win','10_wins','50_wins','100_wins']: prog=w
            elif aid in['balance_1000','balance_5000']: prog=bal
            else: prog=1 if aid in earned else 0
            all_a.append({'id':aid,'name':ad['name'],'desc':ad['desc'],'icon':ad['icon'],'target':ad['target'],'progress':prog,'earned':aid in earned,'earned_at':earned.get(aid,0)})
        return web.json_response({'success':True,'achievements':all_a})
    except Exception as e: return web.json_response({'success':False,'error':str(e)},status=500)

async def handle_save_profile(request):
    try:
        data=await request.json();uid=int(data.get('user_id'));dn=data.get('display_name','').strip();av=data.get('avatar_emoji','🦊')
        if not uid: return web.json_response({'success':False,'error':'user_id required'},status=400)
        if dn and len(dn)>30: return web.json_response({'success':False,'error':'Никнейм слишком длинный'},status=400)
        allowed=['🦊','🐺','🦁','🐯','🐻','🐼','🐨','🐰','🦄','🐲','🎃','🤖','👑','💀','👻','🐶','🐱','🐸','🐵','🐮','🐷','🐹','🐭','🐧','🦉','🦋','🐙','🐳','🦚','🔥🦊','❄️🐺','🦋','🌈🦄','🐙👾']
        if av not in allowed: av='🦊'
        def _do(): conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor();c.execute("UPDATE users SET display_name=?,avatar_emoji=? WHERE user_id=?",(dn or None,av,uid));conn.commit();conn.close()
        execute_sqlite_with_retry(_do);return web.json_response({'success':True,'message':'Профиль сохранён!','display_name':dn,'avatar_emoji':av})
    except Exception as e: return web.json_response({'success':False,'error':str(e)},status=500)

async def handle_game_result(request):
    try:
        data=await request.json();uid=int(data.get('user_id'));game=data.get('game');bet=data.get('bet');win=data.get('win');wa=data.get('win_amount',0)
        if not uid or not game or bet is None: return web.json_response({'success':False,'error':'Missing fields'},status=400)
        cur=get_balance_sync(uid);new=cur+wa if win else cur-bet
        update_balance_sync(uid,new);update_stats_sync(uid,win);save_game_history_sync(uid,bet,wa if win else 0,game)
        try: await execute_query("UPDATE users SET balance=$1 WHERE user_id=$2",new,uid)
        except: pass
        def _add_exp():
            conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
            try: c.execute("ALTER TABLE users ADD COLUMN exp INTEGER DEFAULT 0")
            except: pass
            c.execute("UPDATE users SET exp=COALESCE(exp,0)+? WHERE user_id=?",(50 if win else 25,uid));conn.commit();conn.close()
        execute_sqlite_with_retry(_add_exp)
        try: await execute_query("UPDATE users SET exp=COALESCE(exp,0)+$1,total_games=total_games+1,wins=wins+$2 WHERE user_id=$3",50 if win else 25,1 if win else 0,uid)
        except: pass
        bal,tg,w=get_user_stats_sync(uid);check_achievements_sync(uid,new,tg,w,wa if win else 0)
        return web.json_response({'success':True,'new_balance':new,'win':win})
    except Exception as e:
        logger.error(f"game_result error: {e}")
        return web.json_response({'success':False,'error':str(e)},status=500)

async def handle_claim_ad_reward(request):
    try:
        data=await request.json();uid=int(data.get('user_id'))
        if not uid: return web.json_response({'success':False,'error':'user_id required'},status=400)
        last_ad=get_last_ad_time_sync(uid);now=int(time.time())
        if last_ad and now-last_ad<AD_COOLDOWN_SECONDS:
            remaining=AD_COOLDOWN_SECONDS-(now-last_ad)
            return web.json_response({'success':False,'error':'cooldown','remaining':remaining},status=200)
        cur=get_balance_sync(uid);new=cur+AD_REWARD_AMOUNT
        update_balance_sync(uid,new);set_last_ad_time_sync(uid,now)
        try: await execute_query("UPDATE users SET balance=$1 WHERE user_id=$2",new,uid)
        except: pass
        return web.json_response({'success':True,'new_balance':new,'reward':AD_REWARD_AMOUNT})
    except Exception as e: return web.json_response({'success':False,'error':str(e)},status=500)

async def handle_claim_free_bonus(request):
    try:
        data=await request.json();uid=int(data.get('user_id'))
        if not uid: return web.json_response({'success':False,'error':'user_id required'},status=400)
        last_ad=get_last_ad_time_sync(uid);now=int(time.time())
        if last_ad and now-last_ad<AD_COOLDOWN_SECONDS:
            remaining=AD_COOLDOWN_SECONDS-(now-last_ad)
            return web.json_response({'success':False,'error':'cooldown','remaining':remaining},status=200)
        cur=get_balance_sync(uid);new=cur+FREE_BONUS_AMOUNT
        update_balance_sync(uid,new);set_last_ad_time_sync(uid,now)
        try: await execute_query("UPDATE users SET balance=$1 WHERE user_id=$2",new,uid)
        except: pass
        return web.json_response({'success':True,'new_balance':new,'reward':FREE_BONUS_AMOUNT})
    except Exception as e: return web.json_response({'success':False,'error':str(e)},status=500)

async def handle_create_invoice(request):
    try:
        data=await request.json();uid=int(data.get('user_id'));amount_points=data.get('amount_points')
        if not uid or not amount_points: return web.json_response({'success':False,'error':'user_id and amount_points required'},status=400)
        amount_points=int(amount_points)
        if amount_points not in PRICE_LIST: return web.json_response({'success':False,'error':'Invalid amount'},status=400)
        price_usdt=PRICE_LIST[amount_points]
        async with aiohttp.ClientSession() as session:
            headers={'Crypto-Pay-API-Token':CRYPTOPAY_TOKEN,'Content-Type':'application/json'}
            payload={'asset':'USDT','amount':str(price_usdt),'description':f'Пополнение {amount_points} баллов для Game Bar Casino','payload':json.dumps({'user_id':uid,'amount_points':amount_points}),'allow_comments':False,'allow_anonymous':False}
            try:
                async with session.post(f'{CRYPTOPAY_API_URL}/createInvoice',json=payload,headers=headers) as resp:
                    result = await resp.json()
            except Exception as e: return web.json_response({'success':False,'error':f'CryptoPay API error: {str(e)}'},status=500)
            if not result.get('ok'): return web.json_response({'success':False,'error':f'CryptoPay error: {result.get("error","unknown")}'},status=500)
            invoice=result['result'];payment_id=str(invoice['invoice_id']);invoice_url=invoice['pay_url']
            create_payment(uid,amount_points,price_usdt,payment_id,str(invoice['invoice_id']))
            return web.json_response({'success':True,'payment_id':payment_id,'invoice_url':invoice_url,'amount_points':amount_points,'price_usdt':price_usdt})
    except Exception as e: return web.json_response({'success':False,'error':str(e)},status=500)

async def handle_check_payment(request):
    try:
        data=await request.json();payment_id=data.get('payment_id');uid=data.get('user_id')
        if not payment_id and uid:
            def _find():
                conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
                c.execute("SELECT payment_id,amount_points,status FROM crypto_payments WHERE user_id=? AND status='pending' ORDER BY created_at DESC LIMIT 1",(int(uid),));r=c.fetchone();conn.close();return r
            row=execute_sqlite_with_retry(_find)
            if not row:
                def _find_paid():
                    conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
                    c.execute("SELECT payment_id,amount_points FROM crypto_payments WHERE user_id=? AND status='paid' ORDER BY created_at DESC LIMIT 1",(int(uid),));r=c.fetchone();conn.close();return r
                paid_row=execute_sqlite_with_retry(_find_paid)
                if paid_row: return web.json_response({'success':True,'status':'already_credited','message':f'✅ Баллы уже начислены! ({paid_row[1]} 💎)','new_balance':get_balance_sync(int(uid)),'amount_points':paid_row[1]})
                return web.json_response({'success':True,'status':'no_pending','message':'Нет ожидающих платежей.'})
            payment_id=row[0]
        if not payment_id: return web.json_response({'success':False,'error':'payment_id required'},status=400)
        def _check_local():
            conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
            c.execute("SELECT user_id,amount_points,status FROM crypto_payments WHERE payment_id=?",(payment_id,));r=c.fetchone();conn.close();return r
        row=execute_sqlite_with_retry(_check_local)
        if row and row[2]=='paid': return web.json_response({'success':True,'status':'paid','amount_points':row[1],'new_balance':get_balance_sync(row[0]),'message':f'✅ Начислено {row[1]} баллов!'})
        async with aiohttp.ClientSession() as session:
            headers={'Crypto-Pay-API-Token':CRYPTOPAY_TOKEN,'Content-Type':'application/json'}
            params={'invoice_ids':payment_id}
            try:
                async with session.get(f'{CRYPTOPAY_API_URL}/getInvoices',params=params,headers=headers,timeout=10) as resp:
                    result = await resp.json()
            except Exception: return web.json_response({'success':True,'status':'api_error','message':'⏳ Ошибка связи с CryptoPay.'})
            if not result.get('ok') or not result['result']['items']: return web.json_response({'success':True,'status':'not_found','message':'❌ Счёт не найден.'})
            invoice=result['result']['items'][0]
            if invoice['status']=='paid':
                confirmed=confirm_payment(payment_id)
                if confirmed: return web.json_response({'success':True,'status':'paid','user_id':confirmed[0],'amount_points':confirmed[1],'new_balance':get_balance_sync(confirmed[0]),'message':f'✅ Начислено {confirmed[1]} баллов!'})
                return web.json_response({'success':True,'status':'already_credited','message':'✅ Баллы уже начислены.'})
            return web.json_response({'success':True,'status':invoice['status'],'message':f'⏳ Статус: {invoice["status"]}.'})
    except Exception as e: return web.json_response({'success':False,'error':str(e)},status=500)

async def handle_daily_bonus(request):
    try:
        data=await request.json();uid=int(data.get('user_id'))
        if not uid: return web.json_response({'success':False,'error':'user_id required'},status=400)
        result=claim_daily_bonus_sync(uid)
        if not result: return web.json_response({'success':False,'error':'User not found'},status=404)
        if result.get('error')=='already_claimed': return web.json_response({'success':False,'error':'already_claimed','next':result['next']})
        return web.json_response({'success':True,'bonus':result['bonus'],'streak':result['streak'],'new_balance':result['new_balance']})
    except Exception as e: return web.json_response({'success':False,'error':str(e)},status=500)

async def handle_daily_bonus_status(request):
    try:
        data=await request.json();uid=int(data.get('user_id'))
        if not uid: return web.json_response({'success':False,'error':'user_id required'},status=400)
        return web.json_response({'success':True,'status':get_daily_bonus_status_sync(uid)})
    except Exception as e: return web.json_response({'success':False,'error':str(e)},status=500)

async def handle_get_price_list(request):
    return web.json_response({'success':True,'prices':{str(k):v for k,v in PRICE_LIST.items()}})

def get_user_inventory_sync(uid):
    def _do():
        conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
        c.execute("SELECT item_id,purchased_at FROM user_inventory WHERE user_id=?",(uid,))
        items=[{"item_id":r[0],"purchased_at":r[1]} for r in c.fetchall()]
        now=int(time.time())
        c.execute("SELECT boost_type,expires_at,uses_left FROM active_boosts WHERE user_id=? AND expires_at>?",(uid,now))
        boosts=[{"boost_type":r[0],"expires_at":r[1],"uses_left":r[2]} for r in c.fetchall()]
        conn.close();return {"items":items,"boosts":boosts}
    return execute_sqlite_with_retry(_do)

async def handle_shop_items(request):
    try:
        data=await request.json();uid=int(data.get('user_id'));category=data.get('category','all')
        if not uid: return web.json_response({'success':False,'error':'user_id required'},status=400)
        inventory=get_user_inventory_sync(uid);owned_items={inv["item_id"] for inv in inventory["items"]};active_boosts=inventory["boosts"]
        def _get_active():
            conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
            c.execute("SELECT avatar_emoji FROM users WHERE user_id=?",(uid,));row=c.fetchone();conn.close();return row[0] if row else '🦊'
        current_avatar=execute_sqlite_with_retry(_get_active)
        items=[]
        for item in SHOP_ITEMS:
            item_copy=item.copy();item_copy["owned"]=item["id"] in owned_items
            if item["type"]=="avatar": item_copy["active"]=item.get("emoji")==current_avatar
            if item["type"]=="boost":
                item_copy["active"]=False
                for b in active_boosts:
                    if b["boost_type"]==item.get("effect"):item_copy["active"]=True;item_copy["expires_at"]=b["expires_at"];item_copy["uses_left"]=b["uses_left"];break
            items.append(item_copy)
        if category!='all':items=[i for i in items if i["category"]==category]
        return web.json_response({'success':True,'items':items,'categories':[{'id':'all','name':'Все','icon':'🛍️'},{'id':'avatars','name':'Аватарки','icon':'🦊'},{'id':'boosts','name':'Бонусы','icon':'⚡'},{'id':'services','name':'Услуги','icon':'🔧'}]})
    except Exception as e: return web.json_response({'success':False,'error':str(e)},status=500)

async def handle_shop_buy(request):
    try:
        data=await request.json();uid=int(data.get('user_id'));item_id=data.get('item_id')
        if not uid or not item_id: return web.json_response({'success':False,'error':'user_id and item_id required'},status=400)
        item=next((i for i in SHOP_ITEMS if i["id"]==item_id),None)
        if not item: return web.json_response({'success':False,'error':'Товар не найден'},status=404)
        if item["type"]=="avatar":
            inventory=get_user_inventory_sync(uid)
            if item_id in {inv["item_id"] for inv in inventory["items"]}: return web.json_response({'success':False,'error':'Уже куплено!'})
        bal=get_balance_sync(uid)
        if bal<item["price"]: return web.json_response({'success':False,'error':f'Недостаточно баллов! Нужно {item["price"]} 💎'})
        new_bal=bal-item["price"];update_balance_sync(uid,new_bal)
        try: await execute_query("UPDATE users SET balance=$1 WHERE user_id=$2",new_bal,uid)
        except: pass
        def _add():
            conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor();now=int(time.time())
            if item["type"] in ["avatar","service"]:c.execute("INSERT INTO user_inventory(user_id,item_id,purchased_at) VALUES(?,?,?)",(uid,item_id,now))
            elif item["type"]=="boost":c.execute("INSERT INTO active_boosts(user_id,boost_type,expires_at,uses_left) VALUES(?,?,?,?)",(uid,item.get("effect"),now+item.get("duration",3600),item.get("uses",1)))
            conn.commit();conn.close()
        execute_sqlite_with_retry(_add)
        return web.json_response({'success':True,'new_balance':new_bal,'message':f'✅ Куплено: {item["name"]}!','item':item})
    except Exception as e: return web.json_response({'success':False,'error':str(e)},status=500)

async def handle_shop_inventory(request):
    try:
        data=await request.json();uid=int(data.get('user_id'))
        if not uid: return web.json_response({'success':False,'error':'user_id required'},status=400)
        return web.json_response({'success':True,'inventory':get_user_inventory_sync(uid)})
    except Exception as e: return web.json_response({'success':False,'error':str(e)},status=500)

async def handle_use_insurance(request):
    try:
        data=await request.json();uid=int(data.get('user_id'))
        if not uid: return web.json_response({'success':False,'error':'user_id required'},status=400)
        now=int(time.time())
        def _use():
            conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
            c.execute("SELECT id,uses_left FROM active_boosts WHERE user_id=? AND boost_type='insurance' AND expires_at>? AND uses_left>0 LIMIT 1",(uid,now));row=c.fetchone()
            if not row:conn.close();return None
            c.execute("UPDATE active_boosts SET uses_left=uses_left-1 WHERE id=?",(row[0],));conn.commit();conn.close();return True
        result=execute_sqlite_with_retry(_use)
        if result: return web.json_response({'success':True,'message':'🛡️ Страховка применена!'})
        return web.json_response({'success':False,'error':'Нет активной страховки'})
    except Exception as e: return web.json_response({'success':False,'error':str(e)},status=500)

async def handle_referral_join(request):
    try:
        data=await request.json();uid=int(data.get('user_id'));ref_id=data.get('ref_id')
        if not uid or not ref_id: return web.json_response({'success':False,'error':'user_id and ref_id required'},status=400)
        ref_id=int(ref_id)
        if ref_id==uid: return web.json_response({'success':False,'error':'Нельзя ввести свой ID'})
        def _check_this_ref():
            conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
            c.execute("SELECT id FROM user_inventory WHERE user_id=? AND item_id=?",(uid,f"ref_{ref_id}"));row=c.fetchone();conn.close();return row is not None
        already_used=execute_sqlite_with_retry(_check_this_ref)
        if already_used: return web.json_response({'success':False,'error':'Вы уже активировали промокод этого друга'})
        def _set_ref():
            conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
            c.execute("UPDATE users SET invited_by=COALESCE(invited_by,?) WHERE user_id=?",(ref_id,uid))
            c.execute("INSERT INTO user_inventory(user_id,item_id,purchased_at) VALUES(?,?,?)",(uid,f"ref_{ref_id}",int(time.time())))
            c.execute("UPDATE users SET balance=balance+25 WHERE user_id=?",(ref_id,))
            c.execute("UPDATE users SET balance=balance+25 WHERE user_id=?",(uid,))
            conn.commit();conn.close()
        execute_sqlite_with_retry(_set_ref)
        return web.json_response({'success':True,'message':'🎉 Промокод активирован! +25 баллов вам и другу!'})
    except Exception as e: return web.json_response({'success':False,'error':str(e)},status=500)

async def handle_get_referral_link(request):
    try:
        data=await request.json();uid=int(data.get('user_id'))
        if not uid: return web.json_response({'success':False,'error':'user_id required'},status=400)
        link="https://t.me/GamesAsino_bot/GamesAsino"
        def _count():
            conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
            c.execute("SELECT COUNT(*) FROM users WHERE invited_by=?",(uid,));count=c.fetchone()[0];conn.close();return count
        count=execute_sqlite_with_retry(_count)
        return web.json_response({'success':True,'link':link,'count':count})
    except Exception as e: return web.json_response({'success':False,'error':str(e)},status=500)

async def health(request): return web.json_response({'status':'ok'})

async def handle_webhook(request):
    update=types.Update(**await request.json());await dp.feed_update(bot,update);return web.Response()

app.router.add_post('/webhook',handle_webhook)
app.router.add_post('/api/get_balance',handle_get_balance)
app.router.add_post('/api/get_profile',handle_get_profile)
app.router.add_post('/api/get_achievements',handle_get_achievements)
app.router.add_post('/api/save_profile',handle_save_profile)
app.router.add_post('/api/game_result',handle_game_result)
app.router.add_post('/api/claim_ad_reward',handle_claim_ad_reward)
app.router.add_post('/api/claim_free_bonus',handle_claim_free_bonus)
app.router.add_post('/api/daily_bonus',handle_daily_bonus)
app.router.add_post('/api/daily_bonus_status',handle_daily_bonus_status)
app.router.add_post('/api/create_invoice',handle_create_invoice)
app.router.add_post('/api/check_payment',handle_check_payment)
app.router.add_get('/api/get_price_list',handle_get_price_list)
app.router.add_get('/health',health);app.router.add_get('/',health)
app.router.add_post('/api/shop/items',handle_shop_items)
app.router.add_post('/api/shop/buy',handle_shop_buy)
app.router.add_post('/api/shop/inventory',handle_shop_inventory)
app.router.add_post('/api/shop/use_insurance',handle_use_insurance)
app.router.add_post('/api/referral_join',handle_referral_join)
app.router.add_post('/api/get_referral_link',handle_get_referral_link)

async def on_startup():
    await init_db_pool();await create_db();init_sqlite_db()
    await bot.set_my_commands([BotCommand(command="start",description="Запустить бота"),BotCommand(command="myid",description="Мой Telegram ID"),BotCommand(command="admin",description="Админ-панель")])
    logger.info("Бот запущен")

async def on_shutdown(): await bot.session.close();await close_db_pool()

async def main():
    port=int(os.environ.get('PORT',10000));await on_startup()
    await bot.delete_webhook();await bot.set_webhook("https://game-bar-bot.onrender.com/webhook")
    runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'0.0.0.0',port);await site.start()
    logger.info(f"Сервер на порту {port}")
    try: await asyncio.Future()
    finally: await on_shutdown()

if __name__=="__main__": asyncio.run(main())