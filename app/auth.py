"""Autenticação servidor-servidor pro `POST /veredito` — mesmo padrão do
`INTERNAL_JOBS_TOKEN`/`ASAAS_WEBHOOK_TOKEN` do backend Kotlin: segredo compartilhado
simples, comparado em tempo constante, nunca autenticação de usuário."""

import hashlib
import hmac
from uuid import UUID

VEREDITO_SERVICE_TOKEN_HEADER = "x-veredito-service-token"


def verify_veredito_service_token(provided: str | None, expected: str) -> bool:
    if provided is None:
        return False
    return hmac.compare_digest(provided, expected)


def verify_voice_token(token: str | None, secret: str, now_epoch_seconds: int) -> UUID | None:
    """
    Reimplementação exata de `VoiceToken.verify` (`ensa-ia-back`,
    `security/VoiceToken.kt`) — token efêmero pro handshake do `WebSocket /interview`
    (fase-2-criterios.md). Formato: `"$tentativaId:$userId:$expEpochSeconds:$hmacHex"`.
    """
    if not token:
        return None

    parts = token.split(":")
    if len(parts) != 4:
        return None

    tentativa_id_raw, user_id_raw, exp_raw, signature_raw = parts
    payload = f"{tentativa_id_raw}:{user_id_raw}:{exp_raw}"
    expected_signature = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected_signature, signature_raw):
        return None

    if not exp_raw.isdigit():
        return None
    if now_epoch_seconds > int(exp_raw):
        return None

    try:
        return UUID(tentativa_id_raw)
    except ValueError:
        return None
