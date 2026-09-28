from fastapi.testclient import TestClient

import app.main as main_module
from app.main import app

client = TestClient(app)

_FAKE_RESULT = {
    "nota_geral": 7.5,
    "pontos_fortes": ["a"],
    "pontos_fracos": ["b"],
    "feedback_texto": "ok",
    "nota_escuta_resposta": 8.0,
    "nota_clareza": 7.0,
    "nota_exemplos_concretos": 6.5,
    "nota_fechamento": 8.5,
    "nota_estrutura_resposta": 7.0,
    "nota_concisao": 8.0,
    "kb_objetivo_atualizado": "kb objetivo",
    "perguntas_atualizadas": [{"pergunta": "p1", "respostaResumo": "r1", "qualidade": "forte"}],
    "perguntas_sugeridas": "sugestao",
    "kb_usuario_atualizado": "kb usuario",
    "usages": [
        {"input_tokens_fresh": 60, "input_tokens_cached": 5, "output_tokens": 20},
        {"input_tokens_fresh": 40, "input_tokens_cached": 5, "output_tokens": 30},
    ],
}


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
    def fake_run_evaluator(llms, transcript, historico_anterior, **kwargs):
        return _FAKE_RESULT

    monkeypatch.setattr(main_module, "run_evaluator", fake_run_evaluator)

    response = client.post(
        "/veredito",
        json={"transcript": "x", "historicoAnterior": []},
        headers={"x-veredito-service-token": main_module.settings.veredito_service_token},
    )
    assert response.status_code == 200
    assert response.json() == {
        "notaGeral": 7.5,
        "pontosFortes": ["a"],
        "pontosFracos": ["b"],
        "feedbackTexto": "ok",
        "notaEscutaResposta": 8.0,
        "notaClareza": 7.0,
        "notaExemplosConcretos": 6.5,
        "notaFechamento": 8.5,
        "notaEstruturaResposta": 7.0,
        "notaConcisao": 8.0,
        "kbObjetivoAtualizado": "kb objetivo",
        "perguntasAtualizadas": [{"pergunta": "p1", "respostaResumo": "r1", "qualidade": "forte"}],
        "perguntasSugeridas": "sugestao",
        "kbUsuarioAtualizado": "kb usuario",
        # somados dos 2 nós de exemplo em `_FAKE_RESULT["usages"]`
        "inputTokensFresh": 100,
        "inputTokensCached": 10,
        "outputTokens": 50,
    }


def test_veredito_repassa_kbs_e_perguntas_anteriores_pro_avaliador(monkeypatch):
    recebido = {}

    def fake_run_evaluator(llms, transcript, historico_anterior, **kwargs):
        recebido.update(kwargs)
        return _FAKE_RESULT

    monkeypatch.setattr(main_module, "run_evaluator", fake_run_evaluator)

    client.post(
        "/veredito",
        json={
            "transcript": "x",
            "historicoAnterior": [],
            "kbObjetivoAnterior": "kb antigo",
            "perguntasAnteriores": [{"pergunta": "p0", "respostaResumo": "r0", "qualidade": "media"}],
            "kbUsuarioAnterior": "kb usuario antigo",
        },
        headers={"x-veredito-service-token": main_module.settings.veredito_service_token},
    )

    assert recebido["kb_objetivo_anterior"] == "kb antigo"
    assert recebido["perguntas_anteriores"] == [{"pergunta": "p0", "respostaResumo": "r0", "qualidade": "media"}]
    assert recebido["kb_usuario_anterior"] == "kb usuario antigo"


def test_veredito_sem_kbs_anteriores_funciona_primeira_tentativa(monkeypatch):
    recebido = {}

    def fake_run_evaluator(llms, transcript, historico_anterior, **kwargs):
        recebido.update(kwargs)
        return _FAKE_RESULT

    monkeypatch.setattr(main_module, "run_evaluator", fake_run_evaluator)

    response = client.post(
        "/veredito",
        json={"transcript": "x", "historicoAnterior": []},
        headers={"x-veredito-service-token": main_module.settings.veredito_service_token},
    )

    assert response.status_code == 200
    assert recebido["kb_objetivo_anterior"] is None
    assert recebido["perguntas_anteriores"] == []
    assert recebido["kb_usuario_anterior"] is None
