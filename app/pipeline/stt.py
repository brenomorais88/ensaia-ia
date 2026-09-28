"""
STT (speech-to-text) do pipeline em cascata (plano-arquitetura.md) — Whisper via API
da OpenAI. Um turno = um arquivo de áudio completo (apertar-pra-falar, sem streaming
parcial), então basta o endpoint síncrono de transcrição.
"""

from io import BytesIO

from openai import OpenAI

_EXTENSION_BY_MIME_TYPE: dict[str, str] = {
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mp4": "mp4",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
}


def build_client(api_key: str) -> OpenAI:
    return OpenAI(api_key=api_key)


def transcribe(client: OpenAI, audio_bytes: bytes, mime_type: str) -> str:
    extension = _EXTENSION_BY_MIME_TYPE.get(mime_type, "webm")
    audio_file = BytesIO(audio_bytes)
    audio_file.name = f"turno.{extension}"

    result = client.audio.transcriptions.create(model="whisper-1", file=audio_file)
    return result.text
