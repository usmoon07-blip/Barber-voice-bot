"""SQLite bazasi, config.json va vaqt/yozilish mantiqi."""
import json
import os
import re
import sqlite3
import threading
from datetime import date as Date, datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Tashkent")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.getenv("CONFIG_PATH", os.path.join(BASE_DIR, "config.json"))
DB_PATH = os.getenv("DB_PATH", os.path.join(BASE_DIR, "bookings.db"))

WEEKDAYS = ["dushanba", "seshanba", "chorshanba", "payshanba", "juma", "shanba", "yakshanba"]

_lock = threading.Lock()  # yozilishni tekshirish + saqlash bitta atomik amal bo'lsin


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


CFG = load_config()


class BookingError(Exception):
    """Mijozga/Claude'ga tushunarli sabab bilan rad etish."""


def now() -> datetime:
    return datetime.now(TZ)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created TEXT NOT NULL,
                uid INTEGER,
                name TEXT,
                username TEXT,
                service TEXT NOT NULL,
                master TEXT NOT NULL,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                minutes INTEGER NOT NULL,
                price INTEGER NOT NULL,
                phone TEXT,
                status TEXT NOT NULL DEFAULT 'active'
            )"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_bookings_date ON bookings(date, status)")


# ---------- yordamchi funksiyalar ----------

def money_words(amount: int) -> str:
    """80000 -> '80 ming so'm', 1250000 -> '1,25 million so'm'."""
    if amount >= 1_000_000:
        txt = f"{amount / 1_000_000:.2f}".rstrip("0").rstrip(".").replace(".", ",")
        return f"{txt} million so'm"
    if amount >= 1000:
        txt = f"{amount / 1000:.1f}".rstrip("0").rstrip(".").replace(".", ",")
        return f"{txt} ming so'm"
    return f"{amount} so'm"


def parse_date(value: str) -> Date:
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except ValueError:
        raise BookingError("Sana YYYY-MM-DD formatida bo'lishi kerak")


def _to_min(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _fmt(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def parse_time(value: str) -> str:
    m = re.fullmatch(r"\s*(\d{1,2})[:.](\d{2})\s*", str(value))
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise BookingError("Vaqt HH:MM formatida bo'lishi kerak")
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def get_service(name: str) -> tuple[str, dict]:
    key = str(name or "").strip().lower()
    for sname, info in CFG["services"].items():
        if sname.lower() == key:
            return sname, info
    raise BookingError("Bunday xizmat yo'q. Mavjud xizmatlar: " + ", ".join(CFG["services"]))


def get_master(name: str | None) -> str | None:
    if not name or not str(name).strip():
        return None
    key = str(name).strip().lower()
    for m in CFG["masters"]:
        if m.lower() == key:
            return m
    raise BookingError("Bunday usta yo'q. Ustalar: " + ", ".join(CFG["masters"]))


def normalize_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", str(phone or ""))
    if len(digits) == 9:
        digits = "998" + digits
    if len(digits) == 12 and digits.startswith("998"):
        return "+" + digits
    raise BookingError("Telefon raqami noto'g'ri. 9 xonali raqam kerak, masalan 90 123 45 67")


def _grid(minutes: int) -> list[int]:
    """Ish vaqtidagi barcha boshlanish vaqtlari (daqiqada), xizmat yopilishgacha tugashi kerak."""
    start, end, step = CFG["open_hour"] * 60, CFG["close_hour"] * 60, CFG["step_minutes"]
    return list(range(start, end - minutes + 1, step))


def _busy(conn, day: str) -> dict[str, list[tuple[int, int]]]:
    """Har bir usta uchun band oraliqlar [boshlanish, tugash)."""
    busy = {m: [] for m in CFG["masters"]}
    rows = conn.execute(
        "SELECT master, time, minutes FROM bookings WHERE date=? AND status='active'", (day,)
    ).fetchall()
    for r in rows:
        s = _to_min(r["time"])
        busy.setdefault(r["master"], []).append((s, s + r["minutes"]))
    return busy


def _is_free(intervals, start: int, minutes: int) -> bool:
    end = start + minutes
    return all(end <= s or start >= e for s, e in intervals)


def _min_start(day: Date) -> int:
    """Bugun bo'lsa, o'tib ketgan vaqtlarni chiqarib tashlash uchun chegara."""
    today = now()
    if day < today.date():
        raise BookingError("Bu sana o'tib ketgan")
    if day == today.date():
        return today.hour * 60 + today.minute + 1
    return 0


# ---------- asosiy amallar ----------

def free_slots(day_str: str, service: str, master: str | None = None) -> dict:
    day = parse_date(day_str)
    sname, info = get_service(service)
    mname = get_master(master)
    min_start = _min_start(day)
    masters = [mname] if mname else CFG["masters"]
    with _conn() as conn:
        busy = _busy(conn, day.isoformat())
    free = {}
    for m in masters:
        free[m] = [
            _fmt(t) for t in _grid(info["min"])
            if t >= min_start and _is_free(busy.get(m, []), t, info["min"])
        ]
    return {
        "date": day.isoformat(),
        "weekday": WEEKDAYS[day.weekday()],
        "service": sname,
        "minutes": info["min"],
        "price": info["price"],
        "free_by_master": free,
    }


def book(*, uid, name, username, service, master, day_str, time_str, phone) -> dict:
    day = parse_date(day_str)
    sname, info = get_service(service)
    mname = get_master(master)
    t = parse_time(time_str)
    phone = normalize_phone(phone)
    start = _to_min(t)
    if start not in _grid(info["min"]):
        raise BookingError(
            f"Bu vaqtda yozib bo'lmaydi: ish vaqti {CFG['open_hour']}:00-{CFG['close_hour']}:00, "
            f"vaqtlar har {CFG['step_minutes']} daqiqada"
        )
    with _lock, _conn() as conn:
        conn.execute("BEGIN IMMEDIATE")  # boshqa jarayonlar ham parallel yozmasin
        if start < _min_start(day):
            raise BookingError("Bu vaqt o'tib ketgan")
        busy = _busy(conn, day.isoformat())
        candidates = [mname] if mname else CFG["masters"]
        free = [m for m in candidates if _is_free(busy.get(m, []), start, info["min"])]
        if not free:
            raise BookingError("Bu vaqt band. Boshqa vaqt yoki ustani tanlang")
        # usta aytilmagan bo'lsa, o'sha kuni eng kam band ustani tanlaymiz
        chosen = min(free, key=lambda m: len(busy.get(m, [])))
        cur = conn.execute(
            """INSERT INTO bookings(created, uid, name, username, service, master, date, time,
                                    minutes, price, phone, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?, 'active')""",
            (now().isoformat(timespec="seconds"), uid, name, username, sname, chosen,
             day.isoformat(), t, info["min"], info["price"], phone),
        )
        booking_id = cur.lastrowid
    return {
        "id": booking_id, "name": name, "username": username, "service": sname,
        "master": chosen, "date": day.isoformat(), "time": t,
        "minutes": info["min"], "price": info["price"], "phone": phone,
    }


def cancel(booking_id: int) -> bool:
    with _lock, _conn() as conn:
        cur = conn.execute(
            "UPDATE bookings SET status='cancelled' WHERE id=? AND status='active'", (booking_id,)
        )
        return cur.rowcount > 0


def day_bookings(day_str: str) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM bookings WHERE date=? ORDER BY time, master, id", (day_str,)
        ).fetchall()
    return [dict(r) for r in rows]


def daily_report(day_str: str) -> dict:
    day = parse_date(day_str)
    rows = day_bookings(day.isoformat())
    active = [r for r in rows if r["status"] == "active"]
    cancelled = [r for r in rows if r["status"] == "cancelled"]
    by_master = {}
    for m in CFG["masters"]:
        mine = [r for r in active if r["master"] == m]
        rev = sum(r["price"] for r in mine)
        by_master[m] = {"clients": len(mine), "revenue": rev, "revenue_text": money_words(rev)}
    revenue = sum(r["price"] for r in active)
    capacity = len(CFG["masters"]) * (CFG["close_hour"] - CFG["open_hour"]) * 60
    used = sum(r["minutes"] for r in active)
    return {
        "date": day.isoformat(),
        "weekday": WEEKDAYS[day.weekday()],
        "bookings_count": len(active),
        "expected_revenue": revenue,
        "expected_revenue_text": money_words(revenue),
        "occupancy_percent": round(used * 100 / capacity) if capacity else 0,
        "cancelled_count": len(cancelled),
        "by_master": by_master,
        "schedule": [
            {"time": r["time"], "master": r["master"], "service": r["service"],
             "client": r["name"], "price_text": money_words(r["price"])}
            for r in active
        ],
    }
