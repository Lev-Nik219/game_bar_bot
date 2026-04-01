from aiogram import BaseMiddleware
from aiogram.types import Message
from typing import Callable, Dict, Any, Awaitable
from database import get_user
from handlers.main_bot.profile import show_agreement, show_welcome_with_invite
from states import DemoSlotStates, DemoDiceStates  # импортируем демо-состояния

class UserStatusMiddleware(BaseMiddleware):
    """
    Проверяет, принял ли пользователь соглашение и начал ли игру.
    Если нет – перенаправляет на соответствующий экран.
    """
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any]
    ) -> Any:
        if isinstance(event, Message):
            # Получаем текущее состояние FSM
            state = data.get('state')
            if state:
                current_state = await state.get_state()
                # Если пользователь находится в демо-режиме, пропускаем проверку
                if current_state in [
                    DemoSlotStates.waiting_for_bet,
                    DemoDiceStates.waiting_for_bet,
                    DemoDiceStates.waiting_for_choice
                ]:
                    return await handler(event, data)

            user_id = event.from_user.id
            username = event.from_user.username
            first_name = event.from_user.first_name
            user_data = await get_user(user_id, username)
            agreed = user_data[9]
            has_started = user_data[10]

            if not agreed:
                await show_agreement(event)
                return
            if agreed and not has_started:
                await show_welcome_with_invite(event, user_id, first_name, username, event.bot)
                return
        return await handler(event, data)