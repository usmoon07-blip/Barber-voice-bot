"""Nutqni matnga (STT) va matnni nutqqa (TTS) aylantirish.

Boshqa xizmatga (masalan Muxlisa AI) o'tish uchun faqat shu fayl o'zgartiriladi:
recognize(path) -> str va speak(text, path) imzolari saqlansa bas.
Funksiyalar sinxron; bot ularni asyncio.to_thread orqali chaqiradi.
"""
import os

from google.cloud import speech, texttospeech

LANG = os.getenv("VOICE_LANG", "uz-UZ")
TTS_VOICE = os.getenv("TTS_VOICE", "")  # ixtiyoriy aniq ovoz nomi

_stt: speech.SpeechClient | None = None
_tts: texttospeech.TextToSpeechClient | None = None


def recognize(path: str) -> str:
    """Telegram ovozli xabari (OGG/Opus, 60 soniyagacha) -> matn."""
    global _stt
    if _stt is None:
        _stt = speech.SpeechClient()
    with open(path, "rb") as f:
        audio = speech.RecognitionAudio(content=f.read())
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.OGG_OPUS,
        sample_rate_hertz=48000,
        language_code=LANG,
        enable_automatic_punctuation=True,
    )
    resp = _stt.recognize(config=config, audio=audio, timeout=60)
    return " ".join(r.alternatives[0].transcript for r in resp.results if r.alternatives).strip()


def speak(text: str, path: str) -> None:
    """Matn -> OGG/Opus fayl (Telegram ovozli xabar sifatida yuboriladi)."""
    global _tts
    if _tts is None:
        _tts = texttospeech.TextToSpeechClient()
    voice = texttospeech.VoiceSelectionParams(language_code=LANG, name=TTS_VOICE or None)
    audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.OGG_OPUS)
    resp = _tts.synthesize_speech(
        input=texttospeech.SynthesisInput(text=text), voice=voice, audio_config=audio_config, timeout=60
    )
    with open(path, "wb") as f:
        f.write(resp.audio_content)
