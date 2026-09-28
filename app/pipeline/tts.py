"""
TTS (text-to-speech) do pipeline em cascata (plano-arquitetura.md) — Amazon Polly
Standard, mais barato que a TTS da OpenAI (decisão medida com preço real, ver
plano-arquitetura.md). Voz `Camila` (pt-BR, feminina, Standard — sem custo Neural).
"""

import boto3

VOICE_ID = "Camila"
OUTPUT_FORMAT = "mp3"
MIME_TYPE = "audio/mpeg"


def build_client(access_key_id: str, secret_access_key: str, region: str):
    return boto3.client(
        "polly",
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name=region,
    )


def synthesize(client, text: str) -> bytes:
    response = client.synthesize_speech(
        Text=text,
        OutputFormat=OUTPUT_FORMAT,
        VoiceId=VOICE_ID,
        Engine="standard",
        LanguageCode="pt-BR",
    )
    return response["AudioStream"].read()
