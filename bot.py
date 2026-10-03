"""Telegram handlerlar: mijoz (ovozli yozilish) va ega (hisobot) rejimlari."""
import asyncio
import logging
import os
import tempfile
from urllib.parse import urlencode

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import FSInputFile, Message

import ai
import db
import voice

log = logging.getLogger(__name__)
router = Router()

OWNER_ID = 0
ADMIN_KEY = ""
PUBLIC_URL = ""
MAX_VOICE_SECONDS = 60

ERROR_TEXT = "Hozir javob bera olmayapman, birozdan keyin urinib ko'ring."
VOICE_ONLY_TEXT = "Iltimos, ovozli xabar yuboring."
TOO_LONG_TEXT = "Qisqaroq ovoz yuboring, 60 soniyagacha."
NOT_HEARD_TEXT = "Ovozingizni tushuna olmadim, iltimos qaytadan aytib yuboring."

_test_mode: set[int] = set()  # /test bilan mijoz rejimiga o'tgan ega


def setup(owner_id: int, admin_key: str, public_url: str) -> None:
    global OWNER_ID, ADMIN_KEY, PUBLIC_URL
    OWNER_ID, ADMIN_KEY, PUBLIC_URL = owner_id, admin_key, public_url.rstrip("/")


def is_owner(message: Message) -> bool:
    """Faqat OWNER_ID ega rejimiga kiradi (test rejimida emas)."""
    uid = message.from_user.id if message.from_user else 0
    return uid == OWNER_ID and uid not in _test_mode


def admin_link(day: str) -> str:
    if not PUBLIC_URL:
        return ""
    return f"{PUBLIC_URL}/admin?{urlencode({'key': ADMIN_KEY, 'date': day})}"


async def notify_owner(bot: Bot, text: str) -> None:
    try:
        await bot.send_message(OWNER_ID, text)
    except Exception:
        log.exception("Egaga xabar yuborib bo'lmadi")


async def notify_error(bot: Bot, where: str, err: Exception) -> None:
    log.exception("%s xatosi", where)
    await notify_owner(bot, f"Botda xato ({where}): {type(err).__name__}: {str(err)[:500]}")


async def notify_booking(bot: Bot, b: dict) -> None:
    client = b["name"] or "Noma'lum"
    if b["username"]:
        client += f" (@{b['username']})"
    lines = [
        "Yangi yozilish!",
        f"Mijoz: {client}",
        f"Xizmat: {b['service']} ({db.money_words(b['price'])})",
        f"Usta: {b['master']}",
        f"Sana va vaqt: {b['date']} {b['time']}",
        f"Telefon: {b['phone']}",
    ]
    link = admin_link(b["date"])
    if link:
        lines.append(f"Admin panel: {link}")
    await notify_owner(bot, "\n".join(lines))


async def download_voice(bot: Bot, message: Message, tmpdir: str) -> str:
    path = os.path.join(tmpdir, "in.ogg")
    await bot.download(message.voice, destination=path)
    return path


async def send_voice_reply(message: Message, text: str, tmpdir: str) -> None:
    out = os.path.join(tmpdir, "out.ogg")
    await asyncio.to_thread(voice.speak, text, out)
    await message.answer_voice(FSInputFile(out))


def user_info(message: Message) -> dict:
    u = message.from_user
    return {"uid": u.id, "name": u.full_name, "username": u.username or ""}


# ---------- buyruqlar ----------

@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    if is_owner(message):
        await message.answer(
            "Assalomu alaykum! Hisobot so'rang, masalan: \"bugungi hisobot\" yoki "
            "\"ertaga nechta mijoz bor\". Ovoz yoki matn bilan yozishingiz mumkin.\n"
            "/test - mijoz rejimini sinab ko'rish."
        )
    else:
        await message.answer(
            f"Assalomu alaykum! {db.CFG['business_name']} ga xush kelibsiz. "
            "Yozilish uchun ovozli xabar yuboring."
        )


@router.message(Command("test"))
async def cmd_test(message: Message) -> None:
    uid = message.from_user.id if message.from_user else 0
    if uid != OWNER_ID:
        await message.answer(VOICE_ONLY_TEXT)
        return
    ai.reset_history(uid)
    if uid in _test_mode:
        _test_mode.discard(uid)
        await message.answer("Ega rejimiga qaytdingiz.")
    else:
        _test_mode.add(uid)
        await message.answer("Mijoz rejimi yoqildi. Ovozli xabar yuboring. Qaytish uchun yana /test.")


# ---------- ovozli xabarlar ----------

@router.message(F.voice)
async def on_voice(message: Message, bot: Bot) -> None:
    if message.voice.duration and message.voice.duration > MAX_VOICE_SECONDS:
        await message.answer(TOO_LONG_TEXT)
        return
    owner = is_owner(message)
    with tempfile.TemporaryDirectory() as tmpdir:
        # 1) STT
        try:
            path = await download_voice(bot, message, tmpdir)
            text = await asyncio.to_thread(voice.recognize, path)
        except Exception as e:
            await message.answer(ERROR_TEXT)
            await notify_error(bot, "STT", e)
            return
        if not text:
            await message.answer(NOT_HEARD_TEXT)
            return
        log.info("STT %s: %s", message.from_user.id, text)

        # 2) Claude
        booked: list[dict] = []
        try:
            if owner:
                reply = await ai.owner_reply(message.from_user.id, text, voice=True)
            else:
                reply, booked = await ai.customer_reply(user_info(message), text)
        except Exception as e:
            await message.answer(ERROR_TEXT)
            await notify_error(bot, "Claude", e)
            return
        for b in booked:
            await notify_booking(bot, b)

        # 3) TTS
        try:
            await send_voice_reply(message, reply, tmpdir)
        except Exception as e:
            await message.answer(ERROR_TEXT)
            for b in booked:  # yozilish saqlangan, mijoz buni bilishi kerak
                await message.answer(f"Siz yozildingiz: {b['service']}, usta {b['master']}, {b['date']} soat {b['time']}.")
            await notify_error(bot, "TTS", e)


# ---------- matnli va boshqa xabarlar ----------

@router.message(F.text)
async def on_text(message: Message, bot: Bot) -> None:
    if not is_owner(message):
        await message.answer(VOICE_ONLY_TEXT)
        return
    try:
        reply = await ai.owner_reply(message.from_user.id, message.text, voice=False)
    except Exception as e:
        await message.answer(ERROR_TEXT)
        await notify_error(bot, "Claude", e)
        return
    await message.answer(reply)


@router.message()
async def on_other(message: Message) -> None:
    await message.answer(VOICE_ONLY_TEXT)
