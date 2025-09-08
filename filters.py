from aiogram.filters import BaseFilter
from aiogram import types
from db import is_admin

class IsAdminFilter(BaseFilter):
    async def __call__(self, message: types.Message) -> bool:
        return await is_admin(message.from_user.id)

class IsNotAdminFilter(BaseFilter):
    async def __call__(self, message: types.Message) -> bool:
        return not await is_admin(message.from_user.id)

class IsAdminMessageFilter(BaseFilter):
    async def __call__(self, message: types.Message) -> bool:
        return await is_admin(message.from_user.id) and bool(message.text)