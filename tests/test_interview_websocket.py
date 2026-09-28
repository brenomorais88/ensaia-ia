"""
Teste de integração do `WebSocket /interview` (fase-2-criterios.md) — STT, TTS e o
agente entrevistador totalmente mockados (monkeypatch nos mesmos pontos que
`test_veredito_endpoint.py` já usa pro `run_evaluator`), sem nenhuma chamada de rede.
Prova o fluxo real: handshake com token, `start`, turnos de `audio`, `end`.
"""

import base64
import hashlib
import hmac
import time
from uuid import UUID, uuid4

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

import app.main as main_module
from app.main import app

client = TestClient(app)


def _mint(tentativa_id: UUID, user_id: UUID, secret: str, exp_epoch_seconds: int) -> str:
    payload = f"{tentativa_id}:{user_id}:{exp_epoch_seconds}"
    signature = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}:{signature}"


def _valid_token() -> str:
    return _mint(uuid4(), uuid4(), main_module.settings.voice_token_secret, int(time.time()) + 900)


def fake_synthesize(client, text):
    return b"audio-fake-bytes"


def fake_run_interviewer(llm, contexto_vaga, turnos):
    if not turnos:
        return "Oi! Me conta sobre sua experiência."
    return "Legal, e sobre desafios técnicos?"


def test_websocket_sem_token_fecha_com_4401():
    with pytest.raises(WebSocketDisconnect) as exc_info, client.websocket_connect("/interview"):
        pass
    assert exc_info.value.code == 4401


def test_websocket_com_token_invalido_fecha_com_4401():
    with pytest.raises(WebSocketDisconnect) as exc_info, client.websocket_connect("/interview?token=invalido"):
        pass
    assert exc_info.value.code == 4401


def test_websocket_fluxo_completo_com_pipeline_mockado(monkeypatch):
    monkeypatch.setattr(main_module.stt, "transcribe", lambda c, audio, mime: "Trabalhei 3 anos com Django.")
    monkeypatch.setattr(main_module.tts, "synthesize", fake_synthesize)
    monkeypatch.setattr(main_module, "run_interviewer", fake_run_interviewer)

    token = _valid_token()
    with client.websocket_connect(f"/interview?token={token}") as ws:
        ws.send_json({"tipo": "start", "vagaTitulo": "Engenheiro", "vagaDescricao": None, "estiloEntrevistador": None})

        abertura = ws.receive_json()
        assert abertura["tipo"] == "pergunta"
        assert abertura["textoUsuario"] is None
        assert abertura["textoAssistente"] == "Oi! Me conta sobre sua experiência."
        assert abertura["mimeType"] == "audio/mpeg"
        assert base64.b64decode(abertura["audioBase64"]) == b"audio-fake-bytes"

        ws.send_json({"tipo": "audio", "audioBase64": base64.b64encode(b"som").decode("ascii"), "mimeType": "audio/webm"})

        seguimento = ws.receive_json()
        assert seguimento["tipo"] == "pergunta"
        assert seguimento["textoUsuario"] == "Trabalhei 3 anos com Django."
        assert seguimento["textoAssistente"] == "Legal, e sobre desafios técnicos?"

        ws.send_json({"tipo": "end"})
        assert ws.receive_json() == {"tipo": "encerrado"}


def test_websocket_erro_no_turno_nao_derruba_a_conexao(monkeypatch):
    chamadas = {"n": 0}

    def transcribe_falha_na_primeira(client, audio, mime):
        chamadas["n"] += 1
        if chamadas["n"] == 1:
            raise RuntimeError("Whisper indisponível")
        return "texto ok"

    monkeypatch.setattr(main_module.stt, "transcribe", transcribe_falha_na_primeira)
    monkeypatch.setattr(main_module.tts, "synthesize", fake_synthesize)
    monkeypatch.setattr(main_module, "run_interviewer", fake_run_interviewer)

    token = _valid_token()
    with client.websocket_connect(f"/interview?token={token}") as ws:
        ws.send_json({"tipo": "start", "vagaTitulo": "Engenheiro", "vagaDescricao": None, "estiloEntrevistador": None})
        ws.receive_json()  # abertura

        audio_msg = {"tipo": "audio", "audioBase64": base64.b64encode(b"som").decode("ascii"), "mimeType": "audio/webm"}

        ws.send_json(audio_msg)
        erro = ws.receive_json()
        assert erro["tipo"] == "erro"
        assert "Whisper indisponível" in erro["mensagem"]

        ws.send_json(audio_msg)
        ok = ws.receive_json()
        assert ok["tipo"] == "pergunta"
        assert ok["textoUsuario"] == "texto ok"
