from aiogram.fsm.state import State, StatesGroup

class SlotStates(StatesGroup):
    waiting_for_bet = State()

class RouletteStates(StatesGroup):
    waiting_for_bet = State()
    waiting_for_choice = State()
    waiting_for_number = State()

class DiceStates(StatesGroup):
    waiting_for_bet = State()
    waiting_for_choice = State()

class BlackjackStates(StatesGroup):
    waiting_for_bet = State()
    in_game = State()

class BowlingStates(StatesGroup):
    waiting_for_bet = State()
    waiting_for_choice = State()

class DartsStates(StatesGroup):
    waiting_for_bet = State()
    waiting_for_choice = State()

class AdminGiveStates(StatesGroup):
    waiting_for_target_id = State()
    waiting_for_amount = State()

class AdminTakeStates(StatesGroup):
    waiting_for_target_id = State()
    waiting_for_amount = State()

class AdminUserInfoStates(StatesGroup):
    waiting_for_target_id = State()

class AdminListStates(StatesGroup):
    browsing = State()

class AdminStatsUserStates(StatesGroup):
    waiting_for_user_id = State()

class WithdrawStates(StatesGroup):
    waiting_for_amount = State()
    waiting_for_wallet = State()

class AdminBroadcastStates(StatesGroup):
    waiting_for_bot_choice = State()
    waiting_for_message = State()

class CreateTournamentStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_prize = State()
    waiting_for_duration = State()

class CustomDepositStates(StatesGroup):
    waiting_for_amount = State()

# Для чата с администратором (в разделе "О боте")
class AdminChatStates(StatesGroup):
    waiting_for_message = State()