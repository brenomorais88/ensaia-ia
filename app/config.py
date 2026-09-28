"""
Configuração via variável de ambiente — mesma disciplina do backend Kotlin
(`Env.kt`): fail-fast se uma variável obrigatória estiver ausente, nunca um default
silencioso pra segredo. `ENV`/`APP_VERSION` têm default (não são segredo, servem só
pro /health) — o resto, quando existir (chaves de API, segredos compartilhados), entra
na lista `_REQUIRED` conforme as fases seguintes precisarem.
"""

import os

APP_VERSION = "0.1.0"

_REQUIRED: list[str] = [
    "OPENAI_API_KEY",
    "VEREDITO_SERVICE_TOKEN",
    "VOICE_TOKEN_SECRET",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
]


class ConfigError(RuntimeError):
    pass


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigError(f"Variável de ambiente obrigatória ausente: {name}")
    return value


class Settings:
    def __init__(self) -> None:
        for name in _REQUIRED:
            _require(name)
        self.env = os.environ.get("ENV", "local")
        self.openai_api_key = os.environ["OPENAI_API_KEY"]
        self.veredito_service_token = os.environ["VEREDITO_SERVICE_TOKEN"]
        self.voice_token_secret = os.environ["VOICE_TOKEN_SECRET"]
        self.aws_access_key_id = os.environ["AWS_ACCESS_KEY_ID"]
        self.aws_secret_access_key = os.environ["AWS_SECRET_ACCESS_KEY"]
        self.aws_region = os.environ.get("AWS_REGION", "us-east-1")


def load_settings() -> Settings:
    return Settings()
