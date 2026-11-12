from aiogram.filters import BaseFilter
from aiogram.types import Message

from database.models import get_user_state


class InState(BaseFilter):
    """
    Custom aiogram 3.x filter that checks the user's current state.
    Use instead of a bare F.text handler + state check inside the function,
    so the message is not "consumed" when the state doesn't match.
    """

    def __init__(self, state: str):
        self.state = state

    async def __call__(self, message: Message) -> bool:
        state = await get_user_state(message.from_user.id)
        return state == self.state
