"""Claude bilan ishlash: system promptlar, vositalar (tools) va suhbat tarixi."""
import asyncio
import json
import logging
from collections import defaultdict
from datetime import timedelta

from anthropic import AsyncAnthropic

import db

log = logging.getLogger(__name__)

MODEL = "claude-sonnet-5-5"
EFFORT = "medium"        # ovozli suhbat uchun tezlik va aniqlik muvozanati
MAX_TOKENS = 8000
HISTORY_LIMIT = 12       # har bir foydalanuvchi uchun oxirgi 12 xabar
MAX_TOOL_ROUNDS = 6
# Claude rad etsa (refusal), server tomonda tavsiya etilgan zaxira modelda qayta urinadi
BETAS = ["server-side-fallback-2026-07-01"]
FALLBACKS = "default"

_client: AsyncAnthropic | None = None
_history: dict[str, list[dict]] = defaultdict(list)
_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


def client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic()  # ANTHROPIC_API_KEY .env dan olinadi
    return _client


# ---------- vositalar ----------

CUSTOMER_TOOLS = [
    {
        "name": "check_slots",
        "description": "Berilgan sana va xizmat uchun bo'sh vaqtlarni ustalar bo'yicha qaytaradi. "
                       "Mijozga vaqt taklif qilishdan oldin har doim chaqir.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Sana, YYYY-MM-DD"},
                "service": {"type": "string", "description": "Xizmat nomi, ro'yxatdagidek"},
                "master": {"type": "string", "description": "Usta ismi (ixtiyoriy)"},
            },
            "required": ["date", "service"],
        },
    },
    {
        "name": "book_appointment",
        "description": "Mijozni yozib qo'yadi. Faqat xizmat, sana, vaqt va telefon raqami aniq bo'lganda chaqir. "
                       "Usta aytilmagan bo'lsa master bermasdan chaqir, tizim bo'sh ustani o'zi tanlaydi.",
        "input_schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Xizmat nomi, ro'yxatdagidek"},
                "master": {"type": "string", "description": "Usta ismi (ixtiyoriy)"},
                "date": {"type": "string", "description": "Sana, YYYY-MM-DD"},
                "time": {"type": "string", "description": "Boshlanish vaqti, HH:MM (24 soatlik)"},
                "phone": {"type": "string", "description": "Mijozning telefon raqami"},
            },
            "required": ["service", "date", "time", "phone"],
        },
    },
]

OWNER_TOOLS = [
    {
        "name": "daily_report",
        "description": "Berilgan kun bo'yicha hisobot: yozilishlar soni, kutilayotgan tushum, ustalar bo'yicha "
                       "mijoz va tushum, bandlik foizi, bekor qilinganlar va vaqt bo'yicha ro'yxat.",
        "input_schema": {
            "type": "object",
            "properties": {"date": {"type": "string", "description": "Sana, YYYY-MM-DD"}},
            "required": ["date"],
        },
    },
]


# ---------- system promptlar ----------

def _today_block() -> str:
    """Har so'rovda yangilanadigan sana/vaqt: "ertaga", "juma kuni" ni sanaga aylantirish uchun."""
    n = db.now()
    days = []
    for i in range(8):
        d = n.date() + timedelta(days=i)
        days.append(f"{db.WEEKDAYS[d.weekday()]} {d.isoformat()}")
    return (
        f"Bugun: {n.date().isoformat()}, {db.WEEKDAYS[n.weekday()]}, hozir soat {n:%H:%M} (Toshkent vaqti).\n"
        f"Yaqin kunlar: {'; '.join(days)}."
    )


def _business_block() -> str:
    cfg = db.CFG
    services = "; ".join(
        f"{name} - {db.money_words(s['price'])}, {s['min']} daqiqa" for name, s in cfg["services"].items()
    )
    return (
        f"Barbershop: {cfg['business_name']}. Manzil: {cfg['address_info']}.\n"
        f"Ish vaqti: har kuni soat {cfg['open_hour']}:00 dan {cfg['close_hour']}:00 gacha.\n"
        f"Ustalar: {', '.join(cfg['masters'])}.\n"
        f"Xizmatlar: {services}."
    )


def customer_system() -> str:
    return f"""Sen barbershopning ovozli yozilish yordamchisisan. Mijozlar bilan Telegramda ovozli xabar orqali gaplashasan.

{_business_block()}

{_today_block()}

Qoidalar:
- Faqat o'zbek tilida (lotin yozuvida) javob ber. Javob 2-3 qisqa gapdan iborat bo'lsin.
- Javobing ovozga aylantirilib o'qiladi: emoji, ro'yxat, qavs, yulduzcha va boshqa belgilarni ishlatma. Vaqtni "soat 15:00" ko'rinishida yoz.
- Bo'sh vaqtlarni faqat check_slots natijasidan ayt, hech qachon o'ylab topma. Natijada bo'lmagan vaqtni taklif qilma.
- Mijoz "soat 3", "soat 5" desa, ish vaqtiga qarab kunduzgi vaqt deb tushun (15:00, 17:00).
- Yozish uchun xizmat, sana, vaqt va telefon raqami kerak. Telefon raqamini so'ra. Usta aytilmasa, ustani so'rama.
- Faqat book_appointment muvaffaqiyatli natija qaytarsa "yozib qo'ydim" de va usta ismi, sana va vaqtni ayt. Xato qaytsa, sababini qisqa tushuntirib, check_slots bo'yicha boshqa bo'sh vaqt taklif qil.
- Narx, manzil va ish vaqti haqidagi savollarga yuqoridagi ma'lumotdan javob ber. Barbershopga aloqasiz mavzularda gaplashma."""


def owner_system(voice: bool) -> str:
    style = (
        "Javob ovozda o'qiladi: 3-5 qisqa gap, emoji, ro'yxat va belgilarsiz."
        if voice else
        "Javob matnda: qisqa, oddiy matn, emoji va markdown belgilarisiz."
    )
    return f"""Sen barbershop egasining shaxsiy yordamchisisan. Ega senga ovoz yoki matn bilan hisobot so'raydi.

{_business_block()}

{_today_block()}

Qoidalar:
- Faqat o'zbek tilida (lotin yozuvida) javob ber. {style}
- Hisobot uchun daily_report vositasini chaqir ("bugun", "ertaga", "kecha" ni sanaga aylantir). Bir nechta kun so'ralsa, har biri uchun chaqir.
- Raqamlarni faqat vosita natijasidan ol, o'zingdan qo'shma va taxmin qilma.
- Avval umumiy raqamlar: mijozlar soni, kutilayotgan tushum, bandlik foizi, bekor qilinganlar. Keyin qisqa tafsilot: ustalar bo'yicha mijoz va tushum, kerak bo'lsa vaqtlar.
- Summalarni "ming so'm" yoki "million so'm" deb ayt (natijadagi *_text maydonlaridan foydalan)."""


# ---------- vositalarni bajarish ----------

def _run_customer_tool(name: str, args: dict, user: dict, booked: list) -> dict:
    if name == "check_slots":
        return db.free_slots(args.get("date"), args.get("service"), args.get("master"))
    if name == "book_appointment":
        b = db.book(
            uid=user["uid"], name=user["name"], username=user["username"],
            service=args.get("service"), master=args.get("master"),
            day_str=args.get("date"), time_str=args.get("time"), phone=args.get("phone"),
        )
        booked.append(b)
        return {"ok": True, "booking": b, "price_text": db.money_words(b["price"])}
    raise db.BookingError(f"Noma'lum vosita: {name}")


def _run_owner_tool(name: str, args: dict) -> dict:
    if name == "daily_report":
        return db.daily_report(args.get("date"))
    raise db.BookingError(f"Noma'lum vosita: {name}")


async def _agent_loop(key: str, system: str, tools: list, user_text: str, run_tool) -> str:
    """Claude bilan vosita tsikli. Tarixga faqat matnlar saqlanadi (oxirgi 12 xabar)."""
    history = _history[key]
    messages = list(history) + [{"role": "user", "content": user_text}]
    reply = ""
    for _ in range(MAX_TOOL_ROUNDS):
        resp = await client().beta.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            tools=tools,
            messages=messages,
            output_config={"effort": EFFORT},
            betas=BETAS,
            fallbacks=FALLBACKS,
        )
        if resp.stop_reason == "refusal":
            reply = "Kechirasiz, bu savolga javob bera olmayman."
            break
        reply = "".join(b.text for b in resp.content if b.type == "text").strip()
        tool_uses = [b for b in resp.content if b.type == "tool_use"]
        if resp.stop_reason != "tool_use" or not tool_uses:
            break
        # tsikl ichida javobni (thinking bloklari bilan) o'zgartirmasdan qaytaramiz
        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for tu in tool_uses:
            try:
                out = run_tool(tu.name, dict(tu.input or {}))
                results.append({"type": "tool_result", "tool_use_id": tu.id,
                                "content": json.dumps(out, ensure_ascii=False)})
            except db.BookingError as e:
                results.append({"type": "tool_result", "tool_use_id": tu.id,
                                "content": str(e), "is_error": True})
        messages.append({"role": "user", "content": results})
    if not reply:
        reply = "Kechirasiz, tushunmadim. Qaytadan aytib bera olasizmi?"
    # Tarix: faqat matn. Thinking bloklari saqlanmaydi, chunki system prompt (sana/soat)
    # har so'rovda o'zgaradi va tarix 12 xabarga qisqartiriladi.
    history.extend([{"role": "user", "content": user_text},
                    {"role": "assistant", "content": reply}])
    del history[:-HISTORY_LIMIT]
    return reply


async def customer_reply(user: dict, text: str) -> tuple[str, list[dict]]:
    """Mijoz matniga javob va shu so'rovda yaratilgan yozilishlar ro'yxati."""
    key = f"c:{user['uid']}"
    booked: list[dict] = []
    async with _locks[key]:
        reply = await _agent_loop(
            key, customer_system(), CUSTOMER_TOOLS, text,
            lambda n, a: _run_customer_tool(n, a, user, booked),
        )
    return reply, booked


async def owner_reply(uid: int, text: str, voice: bool) -> str:
    key = f"o:{uid}"
    async with _locks[key]:
        return await _agent_loop(key, owner_system(voice), OWNER_TOOLS, text, _run_owner_tool)


def reset_history(uid: int) -> None:
    _history.pop(f"c:{uid}", None)
    _history.pop(f"o:{uid}", None)
