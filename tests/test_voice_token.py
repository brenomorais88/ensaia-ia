"""
`verify_voice_token` reimplementa `VoiceToken.verify` do Kotlin (fase-2-criterios.md).
Como o Python nunca gera token (só o Kotlin faz, via `VoiceToken.mint`), o teste monta
o token à mão com o mesmo algoritmo — prova a compatibilidade cross-language sem
precisar rodar Kotlin aqui.
"""

import hashlib
import hmac
from uuid import UUID, uuid4

from app.auth import verify_voice_token

SECRET = "segredo-compartilhado-de-teste"
NOW = 1_700_000_000


def _mint(tentativa_id: UUID, user_id: UUID, secret: str, exp_epoch_seconds: int) -> str:
    payload = f"{tentativa_id}:{user_id}:{exp_epoch_seconds}"
    signature = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}:{signature}"


def test_token_valido_retorna_o_tentativa_id():
    tentativa_id = uuid4()
    token = _mint(tentativa_id, uuid4(), SECRET, NOW + 900)

    assert verify_voice_token(token, SECRET, now_epoch_seconds=NOW) == tentativa_id


def test_token_expirado_retorna_none():
    token = _mint(uuid4(), uuid4(), SECRET, NOW - 1)

    assert verify_voice_token(token, SECRET, now_epoch_seconds=NOW) is None


def test_token_no_limite_da_expiracao_ainda_e_valido():
    tentativa_id = uuid4()
    token = _mint(tentativa_id, uuid4(), SECRET, NOW)

    assert verify_voice_token(token, SECRET, now_epoch_seconds=NOW) == tentativa_id


def test_token_com_assinatura_errada_retorna_none():
    token = _mint(uuid4(), uuid4(), SECRET, NOW + 900)
    token_adulterado = token[:-1] + ("0" if token[-1] != "0" else "1")

    assert verify_voice_token(token_adulterado, SECRET, now_epoch_seconds=NOW) is None


def test_token_assinado_com_outro_segredo_retorna_none():
    token = _mint(uuid4(), uuid4(), "outro-segredo", NOW + 900)

    assert verify_voice_token(token, SECRET, now_epoch_seconds=NOW) is None


def test_token_malformado_retorna_none():
    assert verify_voice_token("nao-tem-quatro-partes", SECRET, now_epoch_seconds=NOW) is None
    assert verify_voice_token("a:b:c:d:e", SECRET, now_epoch_seconds=NOW) is None


def test_token_com_tentativa_id_invalido_retorna_none():
    payload = f"nao-e-um-uuid:{uuid4()}:{NOW + 900}"
    signature = hmac.new(SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()

    assert verify_voice_token(f"{payload}:{signature}", SECRET, now_epoch_seconds=NOW) is None


def test_token_ausente_retorna_none():
    assert verify_voice_token(None, SECRET, now_epoch_seconds=NOW) is None
    assert verify_voice_token("", SECRET, now_epoch_seconds=NOW) is None
