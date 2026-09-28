"""
Configuração via variável de ambiente — mesma disciplina do backend Kotlin
(`Env.kt`): fail-fast se uma variável obrigatória estiver ausente, nunca um default
silencioso pra segredo. `ENV`/`APP_VERSION` têm default (não são segredo, servem só
pro /health) — o resto, quando existir (chaves de API, segredos compartilhados), entra
na lista `_REQUIRED` conforme as fases seguintes precisarem.
"""

import os

APP_VERSION = "0.1.0"

_REQUIRED: list[str] = []


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


def load_settings() -> Settings:
    return Settings()
