"""Ishga tushirish: Telegram bot va admin panel bitta jarayonda."""
import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiohttp import web
from dotenv import load_dotenv

load_dotenv()  # boshqa modullardan oldin: DB_PATH, CONFIG_PATH .env da bo'lishi mumkin

import admin  # noqa: E402
import bot as bot_module  # noqa: E402
import db  # noqa: E402


def env(name: str, required: bool = True, default: str = "") -> str:
    value = os.getenv(name, default).strip()
    if required and not value:
        raise SystemExit(f".env da {name} to'ldirilmagan")
    return value


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    token = env("BOT_TOKEN")
    owner_id = int(env("OWNER_ID"))
    admin_key = env("ADMIN_KEY")
    env("ANTHROPIC_API_KEY")
    env("MUXLISA_API_KEY")
    public_url = env("PUBLIC_URL", required=False)
    port = int(env("PORT", required=False, default="8080"))

    db.init_db()
    bot_module.setup(owner_id, admin_key, public_url)

    # admin panel
    runner = web.AppRunner(admin.create_app(admin_key))
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    logging.info("Admin panel: http://0.0.0.0:%s/admin?key=...", port)

    # telegram bot (long polling)
    bot = Bot(token)
    dp = Dispatcher()
    dp.include_router(bot_module.router)
    try:
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
