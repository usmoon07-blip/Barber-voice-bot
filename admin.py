"""Veb admin panel (aiohttp): kunlik jadval va yozilishni bekor qilish."""
import hmac
from datetime import timedelta
from html import escape
from urllib.parse import urlencode

from aiohttp import web

import db


def _check_key(request: web.Request) -> str:
    key = request.query.get("key", "")
    admin_key = request.app["admin_key"]
    if not admin_key or not hmac.compare_digest(key.encode(), admin_key.encode()):
        raise web.HTTPForbidden(text="403: kalit noto'g'ri")
    return key


def _day(request: web.Request) -> str:
    try:
        return db.parse_date(request.query.get("date", "")).isoformat()
    except db.BookingError:
        return db.now().date().isoformat()


def _url(path: str, **params) -> str:
    return escape(f"{path}?{urlencode(params)}")


STYLE = """
:root{--bg:#0d0d0d;--card:#181818;--line:#2a2a2a;--text:#f2f2f2;--muted:#9a9a9a;--accent:#ff5a1f}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:16px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:960px;margin:0 auto;padding:16px}
h1{font-size:1.3rem;margin:0 0 4px}
h1 span{color:var(--accent)}
.nav{display:flex;gap:8px;align-items:center;justify-content:space-between;margin:12px 0}
.nav strong{font-size:1.05rem}
a.btn,button{display:inline-block;min-height:44px;padding:10px 14px;border-radius:10px;border:1px solid var(--accent);
  background:transparent;color:var(--accent);font:inherit;font-weight:600;text-decoration:none;cursor:pointer}
button.cancel{min-height:36px;padding:6px 12px}
a.btn:hover,button:hover{background:var(--accent);color:#000}
a.btn:focus-visible,button:focus-visible{outline:3px solid #fff;outline-offset:2px}
.stats{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:12px 0}
.stat{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px}
.stat b{display:block;font-size:1.4rem;color:var(--accent)}
.stat small{color:var(--muted)}
.list{display:flex;flex-direction:column;gap:8px}
.row{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:12px;padding:12px;
  display:grid;grid-template-columns:auto 1fr auto;gap:4px 12px;align-items:center}
.row .time{font-size:1.2rem;font-weight:700}
.row .meta{color:var(--muted);font-size:.9rem}
.row.cancelled{opacity:.55;border-left-color:var(--line)}
.row.cancelled .main,.row.cancelled .time{text-decoration:line-through}
.empty{color:var(--muted);text-align:center;padding:24px}
.tag{color:var(--muted);font-size:.85rem}
@media(min-width:700px){.stats{grid-template-columns:repeat(4,1fr)}}
"""


async def admin_page(request: web.Request) -> web.Response:
    key = _check_key(request)
    day = _day(request)
    d = db.parse_date(day)
    rows = db.day_bookings(day)
    active = [r for r in rows if r["status"] == "active"]
    revenue = sum(r["price"] for r in active)
    cancelled = len(rows) - len(active)

    items = []
    for r in rows:
        is_active = r["status"] == "active"
        client = escape(r["name"] or "Noma'lum")
        if r["username"]:
            client += f' <span class="tag">@{escape(r["username"])}</span>'
        action = (
            f'<form method="post" action="{_url("/cancel", key=key, id=r["id"], date=day)}" '
            f'onsubmit="return confirm(\'Yozilishni bekor qilasizmi?\')">'
            f'<button class="cancel" type="submit">Bekor</button></form>'
            if is_active else '<span class="tag">bekor qilingan</span>'
        )
        items.append(
            f'<div class="row{"" if is_active else " cancelled"}">'
            f'<div class="time">{escape(r["time"])}</div>'
            f'<div class="main"><div>{client}</div>'
            f'<div class="meta">{escape(r["service"])} · {escape(r["master"])} · '
            f'<a href="tel:{escape(r["phone"] or "")}" style="color:inherit">{escape(r["phone"] or "")}</a> · '
            f'{escape(db.money_words(r["price"]))}</div></div>'
            f'<div>{action}</div></div>'
        )
    body = "\n".join(items) or '<div class="empty">Bu kunga yozilishlar yo\'q</div>'

    prev_day = (d - timedelta(days=1)).isoformat()
    next_day = (d + timedelta(days=1)).isoformat()
    today = db.now().date().isoformat()
    html = f"""<!doctype html>
<html lang="uz"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="20">
<title>{escape(db.CFG["business_name"])} - admin</title>
<style>{STYLE}</style></head>
<body><main>
<h1><span>{escape(db.CFG["business_name"])}</span> · jadval</h1>
<nav class="nav" aria-label="Kunlar">
  <a class="btn" href="{_url("/admin", key=key, date=prev_day)}">&larr; Oldingi</a>
  <strong>{escape(day)}, {escape(db.WEEKDAYS[d.weekday()])}</strong>
  <a class="btn" href="{_url("/admin", key=key, date=next_day)}">Keyingi &rarr;</a>
</nav>
{"" if day == today else f'<p><a class="btn" href="{_url("/admin", key=key, date=today)}">Bugun</a></p>'}
<section class="stats">
  <div class="stat"><small>Jami mijoz</small><b>{len(active)}</b></div>
  <div class="stat"><small>Tushum</small><b>{escape(db.money_words(revenue))}</b></div>
  <div class="stat"><small>Bekor qilingan</small><b>{cancelled}</b></div>
  <div class="stat"><small>Ustalar</small><b>{len(db.CFG["masters"])}</b></div>
</section>
<section class="list">{body}</section>
</main></body></html>"""
    return web.Response(text=html, content_type="text/html")


async def cancel_booking(request: web.Request) -> web.Response:
    key = _check_key(request)
    try:
        booking_id = int(request.query.get("id", ""))
    except ValueError:
        raise web.HTTPBadRequest(text="id noto'g'ri")
    db.cancel(booking_id)
    raise web.HTTPSeeOther(f"/admin?{urlencode({'key': key, 'date': _day(request)})}")


def create_app(admin_key: str) -> web.Application:
    app = web.Application()
    app["admin_key"] = admin_key
    app.router.add_get("/admin", admin_page)
    app.router.add_post("/cancel", cancel_booking)
    return app
