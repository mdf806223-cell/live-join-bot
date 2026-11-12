import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import BOT_TOKEN
from database.db import init_db
from utils.telegram_client import set_bot

from handlers import start, add_account, account_list, join_live, hand_raise, leave_live

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
log = logging.getLogger(__name__)


async def main():
    await init_db()
    log.info("✅ Database initialized.")

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
    )

    # Pass bot to telegram_client so it can send live-ended notifications
    set_bot(bot)

    dp = Dispatcher()

    dp.include_router(start.router)
    dp.include_router(account_list.router)
    dp.include_router(join_live.router)
    dp.include_router(hand_raise.router)
    dp.include_router(leave_live.router)
    dp.include_router(add_account.router)

    log.info("🚀 Bot starting...")
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
