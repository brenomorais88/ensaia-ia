from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.main as main_module
from app.main import app

client = TestClient(app)


def test_veredito_sem_header_retorna_401():
    response = client.post("/veredito", json={"transcript": "x", "historicoAnterior": []})
    assert response.status_code == 401


def test_veredito_com_header_errado_retorna_401():
    response = client.post(
        "/veredito",
        json={"transcript": "x", "historicoAnterior": []},
        headers={"x-veredito-service-token": "token-errado"},
    )
    assert response.status_code == 401


def test_veredito_com_header_certo_devolve_o_shape_esperado(monkeypatch):
    fake_output = SimpleNamespace(
        nota_geral=7.5,
        pontos_fortes=["a"],
        pontos_fracos=["b"],
        feedback_texto="ok",
    )

    def fake_run_evaluator(llm, transcript, historico_anterior):
        return {
            "output": fake_output,
            "input_tokens_fresh": 100,
            "input_tokens_cached": 10,
            "output_tokens": 50,
        }

    monkeypatch.setattr(main_module, "run_evaluator", fake_run_evaluator)

    response = client.post(
        "/veredito",
        json={"transcript": "x", "historicoAnterior": []},
        headers={"x-veredito-service-token": main_module.settings.veredito_service_token},
    )
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "notaGeral": 7.5,
        "pontosFortes": ["a"],
        "pontosFracos": ["b"],
        "feedbackTexto": "ok",
        "inputTokensFresh": 100,
        "inputTokensCached": 10,
        "outputTokens": 50,
    }
