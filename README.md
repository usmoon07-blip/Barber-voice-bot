# Barbershop ovozli yozilish boti

Mijoz Telegramda ovozli xabar yuboradi, bot ovozda javob beradi va vaqt band qiladi.
Ega botga ovoz yoki matn bilan yozib kunlik hisobot oladi. Admin panelda kunlik jadval ko'rinadi.

```
main.py      ishga tushirish (bot + admin panel bitta jarayonda)
config.json  biznes sozlamalari (har mijoz uchun shu fayl o'zgaradi)
bot.py       Telegram handlerlar
ai.py        Claude, vositalar, system promptlar
voice.py     STT va TTS (boshqa xizmatga o'tish uchun faqat shu fayl o'zgaradi)
db.py        SQLite va yozilish mantiqi
admin.py     veb admin panel
```

## 1. O'rnatish

Python 3.11+ kerak.

```bash
git clone <repo-url> barber-bot && cd barber-bot
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## 2. Kalitlarni tayyorlash va `.env` to'ldirish

```bash
cp .env.example .env
nano .env
```

| O'zgaruvchi | Qayerdan olinadi |
|---|---|
| `BOT_TOKEN` | Telegramda @BotFather -> `/newbot` |
| `OWNER_ID` | Ega Telegram ID raqami (@userinfobot ga yozing) |
| `ADMIN_KEY` | Uzun tasodifiy satr: `openssl rand -hex 16` |
| `ANTHROPIC_API_KEY` | https://console.anthropic.com -> API Keys |
| `GOOGLE_APPLICATION_CREDENTIALS` | Google Cloud service account JSON fayli yo'li |
| `PUBLIC_URL` | Ixtiyoriy. Admin panel manzili, masalan `http://123.45.67.89:8080`. Berilsa, egaga keladigan xabarda havola bo'ladi |
| `PORT` | Admin panel porti, standart `8080` |

Google Cloud: loyihada **Cloud Speech-to-Text API** va **Cloud Text-to-Speech API** ni yoqing,
service account yarating, JSON kalitini yuklab oling va serverga qo'ying (masalan `/opt/barber-bot/google-key.json`).
Til `uz-UZ`. Agar Google TTS'da o'zbekcha ovoz bo'lmasa yoki boshqa ovoz kerak bo'lsa, `.env` ga `TTS_VOICE=<ovoz nomi>`
qo'shish mumkin yoki `voice.py` ni Muxlisa AI kabi xizmatga almashtiring (`recognize(path) -> str` va `speak(text, path)` imzolari saqlansin).

Ega botga bir marta `/start` yozishi kerak, aks holda bot egaga xabar yubora olmaydi.

## 3. Sozlamalar (`config.json`)

Barbershop nomi, manzil, ish vaqti (`open_hour`, `close_hour`), qadam (`step_minutes`), ustalar va
xizmatlar (narx so'mda, davomiylik daqiqada) shu faylda. O'zgartirgandan keyin botni qayta ishga tushiring, kodga tegish shart emas.

## 4. Lokal ishga tushirish

```bash
. .venv/bin/activate
python main.py
```

- Bot: Telegramda botga ovozli xabar yuboring.
- Admin panel: `http://localhost:8080/admin?key=ADMIN_KEY` (`&date=YYYY-MM-DD` bilan boshqa kun).
- Ega: "bugungi hisobot", "ertaga nechta mijoz bor", "kecha qancha ishladik" deb ovoz yoki matn yuboradi.
- `/test` (faqat ega): mijoz rejimiga o'tish, yana `/test` - qaytish.

Baza `bookings.db` fayli loyiha papkasida avtomatik yaratiladi.

## 5. VPS'da doimiy ishlatish (systemd)

Eng arzon VPS (1 vCPU, 1 GB RAM, Ubuntu 22.04/24.04) yetarli.

```bash
# serverda
sudo apt update && sudo apt install -y python3 python3-venv git
sudo useradd -r -m -d /opt/barber-bot barber
sudo -u barber git clone <repo-url> /opt/barber-bot/app
cd /opt/barber-bot/app
sudo -u barber python3 -m venv .venv
sudo -u barber .venv/bin/pip install -r requirements.txt
sudo -u barber cp .env.example .env && sudo -u barber nano .env
# Google JSON kalitini /opt/barber-bot/google-key.json ga qo'ying:
sudo chown barber:barber /opt/barber-bot/google-key.json && sudo chmod 600 /opt/barber-bot/google-key.json .env
```

`/etc/systemd/system/barber-bot.service` faylini yarating:

```ini
[Unit]
Description=Barbershop ovozli yozilish boti
After=network-online.target
Wants=network-online.target

[Service]
User=barber
WorkingDirectory=/opt/barber-bot/app
ExecStart=/opt/barber-bot/app/.venv/bin/python main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now barber-bot
sudo systemctl status barber-bot
journalctl -u barber-bot -f        # loglar
sudo ufw allow 8080/tcp            # admin panel tashqaridan ochilishi uchun (firewall bo'lsa)
```

Yangilash: `cd /opt/barber-bot/app && sudo -u barber git pull && sudo systemctl restart barber-bot`.

Zaxira nusxa: `bookings.db` faylini vaqti-vaqti bilan nusxalab qo'ying.

Xavfsizlik: admin panel kaliti URL'da yuradi, shuning uchun imkon bo'lsa domen va HTTPS (masalan Caddy yoki nginx orqali) ishlating
va `PUBLIC_URL` ni `https://...` qilib qo'ying.
