"""Nutqni matnga (STT) va matnni nutqqa (TTS) aylantirish: Muxlisa AI (muxlisa.uz).

Boshqa xizmatga o'tish uchun faqat shu fayl o'zgartiriladi:
recognize(path) -> str va speak(text, path) imzolari saqlansa bas.
Funksiyalar sinxron; bot ularni asyncio.to_thread orqali chaqiradi.

Audio formatlarni o'zgartirish uchun serverda ffmpeg o'rnatilgan bo'lishi kerak.
Manzillar va maydon nomlari .env orqali o'zgartiriladi (Muxlisa kabinetidagi hujjatga qarab).
"""
import base64
import os
import subprocess
import tempfile

import requests

API_KEY = os.getenv("MUXLISA_API_KEY", "")
STT_URL = os.getenv("MUXLISA_STT_URL", "https://service.muxlisa.uz/api/v2/stt")
TTS_URL = os.getenv("MUXLISA_TTS_URL", "https://service.muxlisa.uz/api/v2/tts")
STT_FIELD = os.getenv("MUXLISA_STT_FIELD", "audio")   # multipart fayl maydoni nomi
SPEAKER = os.getenv("MUXLISA_SPEAKER", "")             # ixtiyoriy ovoz (spiker) raqami
TIMEOUT = 60

_session = requests.Session()


def _headers() -> dict:
    if not API_KEY:
        raise RuntimeError("MUXLISA_API_KEY .env da to'ldirilmagan")
    return {"x-api-key": API_KEY}


def _ffmpeg(src: str, dst: str, *args: str) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", src, *args, dst],
        check=True, timeout=TIMEOUT, capture_output=True,
    )


def _find(data, keys: tuple[str, ...]):
    """JSON javobdan kerakli maydonni topish (ichma-ich 'data'/'result' ham hisobga olinadi)."""
    if isinstance(data, dict):
        for k in keys:
            if isinstance(data.get(k), str) and data[k].strip():
                return data[k]
        for v in data.values():
            found = _find(v, keys)
            if found:
                return found
    elif isinstance(data, list):
        for v in data:
            found = _find(v, keys)
            if found:
                return found
    return None


def recognize(path: str) -> str:
    """Telegram ovozli xabari (OGG/Opus) -> matn. Muxlisa'ga 16 kHz mono WAV yuboriladi."""
    with tempfile.TemporaryDirectory() as tmp:
        wav = os.path.join(tmp, "in.wav")
        _ffmpeg(path, wav, "-ac", "1", "-ar", "16000")
        with open(wav, "rb") as f:
            resp = _session.post(
                STT_URL, headers=_headers(),
                files={STT_FIELD: ("audio.wav", f, "audio/wav")}, timeout=TIMEOUT,
            )
    resp.raise_for_status()
    text = _find(resp.json(), ("text", "transcript", "transcription", "result"))
    return (text or "").strip()


def _tts_audio_bytes(resp: requests.Response) -> bytes:
    """TTS javobi: to'g'ridan-to'g'ri audio, yoki JSON ichida base64 / havola."""
    ctype = resp.headers.get("content-type", "")
    if not ctype.startswith("application/json"):
        return resp.content
    data = resp.json()
    b64 = _find(data, ("audio", "audio_base64", "content"))
    if b64 and not b64.startswith("http"):
        return base64.b64decode(b64)
    url = _find(data, ("url", "audio_url", "file", "link", "audio"))
    if not url:
        raise RuntimeError(f"Muxlisa TTS javobida audio topilmadi: {str(data)[:200]}")
    audio = _session.get(url, headers=_headers(), timeout=TIMEOUT)
    audio.raise_for_status()
    return audio.content


def speak(text: str, path: str) -> None:
    """Matn -> OGG/Opus fayl (Telegram ovozli xabar sifatida yuboriladi)."""
    payload = {"text": text}
    if SPEAKER:
        payload["speaker"] = int(SPEAKER) if SPEAKER.isdigit() else SPEAKER
    resp = _session.post(TTS_URL, headers=_headers(), json=payload, timeout=TIMEOUT)
    resp.raise_for_status()
    with tempfile.TemporaryDirectory() as tmp:
        raw = os.path.join(tmp, "tts.bin")
        with open(raw, "wb") as f:
            f.write(_tts_audio_bytes(resp))
        # Telegram "voice" uchun OGG/Opus kerak; ffmpeg kirish formatini o'zi aniqlaydi
        _ffmpeg(raw, path, "-ac", "1", "-c:a", "libopus", "-b:a", "32k", "-f", "ogg")
