"""Autenticação servidor-servidor pro `POST /veredito` — mesmo padrão do
`INTERNAL_JOBS_TOKEN`/`ASAAS_WEBHOOK_TOKEN` do backend Kotlin: segredo compartilhado
simples, comparado em tempo constante, nunca autenticação de usuário."""

import hmac

VEREDITO_SERVICE_TOKEN_HEADER = "x-veredito-service-token"


def verify_veredito_service_token(provided: str | None, expected: str) -> bool:
    if provided is None:
        return False
    return hmac.compare_digest(provided, expected)
