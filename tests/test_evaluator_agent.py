"""
Testa o grafo multi-nó do avaliador (fase-3-criterios.md) de ponta a ponta, passando
pelo LangGraph de verdade, com um `FakeLLM` por nó — mesmo espírito do `FakeLLM`
usado pro avaliador single-node antigo e pro agente entrevistador.
"""

from types import SimpleNamespace

import pytest

from app.agents.evaluator import (
    ObjetivoKbOutput,
    PerguntaRespondidaSchema,
    PilarOutput,
    PlanejadorOutput,
    TextoFeedbackOutput,
    UsuarioKbOutput,
    run_evaluator,
)

_NOTAS_PADRAO = {
    "escuta_resposta": 7.3,
    "clareza": 8.1,
    "exemplos_concretos": 6.2,
    "fechamento": 9.4,
    "estrutura_resposta": 5.5,
    "concisao": 10.0,
}
_USAGE_PADRAO = {"input_tokens": 10, "output_tokens": 5, "input_token_details": {"cache_read": 0}}


class _FakeStructuredLLM:
    def __init__(self, parsed, usage, captured, on_invoke):
        self._parsed = parsed
        self._usage = usage
        self._captured = captured
        self._on_invoke = on_invoke

    def invoke(self, messages):
        self._captured.append(messages)
        if self._on_invoke:
            self._on_invoke(messages)
        return {"raw": SimpleNamespace(usage_metadata=self._usage), "parsed": self._parsed}


class FakeLLM:
    def __init__(self, parsed, usage=None, on_invoke=None):
        self.captured_messages: list[list[dict]] = []
        self._parsed = parsed
        self._usage = usage or _USAGE_PADRAO
        self._on_invoke = on_invoke

    def with_structured_output(self, schema, include_raw=True):
        return _FakeStructuredLLM(self._parsed, self._usage, self.captured_messages, self._on_invoke)


def _make_llms(
    notas: dict[str, float] | None = None,
    perguntas_desta_tentativa: list[PerguntaRespondidaSchema] | None = None,
    planejador_on_invoke=None,
) -> dict[str, FakeLLM]:
    notas = notas if notas is not None else _NOTAS_PADRAO
    if perguntas_desta_tentativa is None:
        perguntas_desta_tentativa = [
            PerguntaRespondidaSchema(pergunta="Fale de um desafio", resposta_resumo="resumo", qualidade="forte"),
        ]

    llms: dict[str, FakeLLM] = {nome: FakeLLM(PilarOutput(nota=nota)) for nome, nota in notas.items()}
    llms["texto_feedback"] = FakeLLM(
        TextoFeedbackOutput(
            pontos_fortes=["a"],
            pontos_fracos=["b"],
            feedback_texto="ok",
            perguntas=perguntas_desta_tentativa,
        ),
    )
    llms["objetivo_kb"] = FakeLLM(ObjetivoKbOutput(kb_atualizado="kb objetivo novo"))
    llms["planejador_perguntas"] = FakeLLM(
        PlanejadorOutput(perguntas_sugeridas="sugestao"), on_invoke=planejador_on_invoke,
    )
    llms["usuario_kb"] = FakeLLM(UsuarioKbOutput(kb_atualizado="kb usuario novo"))
    return llms


def test_nota_geral_e_a_media_exata_dos_6_pilares():
    llms = _make_llms()
    result = run_evaluator(llms, transcript="transcript de teste", historico_anterior=[])
    assert result["nota_geral"] == pytest.approx(sum(_NOTAS_PADRAO.values()) / 6)


def test_texto_feedback_devolve_pontos_fortes_fracos_e_feedback():
    llms = _make_llms()
    result = run_evaluator(llms, transcript="t", historico_anterior=[])
    assert result["pontos_fortes"] == ["a"]
    assert result["pontos_fracos"] == ["b"]
    assert result["feedback_texto"] == "ok"


def test_primeira_tentativa_sem_nenhum_kb_anterior_funciona():
    llms = _make_llms()
    result = run_evaluator(llms, transcript="t", historico_anterior=[])
    assert result["kb_objetivo_atualizado"] == "kb objetivo novo"
    assert result["kb_usuario_atualizado"] == "kb usuario novo"
    assert result["perguntas_sugeridas"] == "sugestao"
    # sem KB anterior, o prompt do objetivo_kb avisa que é a primeira tentativa
    objetivo_kb_prompt = llms["objetivo_kb"].captured_messages[0][1]["content"]
    assert "primeira tentativa" in objetivo_kb_prompt


def test_perguntas_atualizadas_nao_duplica_pergunta_identica():
    anteriores = [{"pergunta": "Fale de um desafio", "respostaResumo": "resumo antigo", "qualidade": "media"}]
    novas = [PerguntaRespondidaSchema(pergunta="Fale de um desafio", resposta_resumo="resumo novo", qualidade="forte")]
    llms = _make_llms(perguntas_desta_tentativa=novas)

    result = run_evaluator(llms, transcript="t", historico_anterior=[], perguntas_anteriores=anteriores)

    assert len(result["perguntas_atualizadas"]) == 1
    assert result["perguntas_atualizadas"][0]["respostaResumo"] == "resumo antigo"


def test_perguntas_atualizadas_acrescenta_pergunta_nova_sem_remover_a_anterior():
    anteriores = [{"pergunta": "Pergunta antiga", "respostaResumo": "r1", "qualidade": "forte"}]
    novas = [PerguntaRespondidaSchema(pergunta="Pergunta nova", resposta_resumo="r2", qualidade="fraca")]
    llms = _make_llms(perguntas_desta_tentativa=novas)

    result = run_evaluator(llms, transcript="t", historico_anterior=[], perguntas_anteriores=anteriores)

    perguntas = {p["pergunta"] for p in result["perguntas_atualizadas"]}
    assert perguntas == {"Pergunta antiga", "Pergunta nova"}


def test_planejador_so_roda_depois_do_objetivo_kb_com_a_lista_ja_atualizada():
    recebido = {}

    def capturar(messages):
        recebido["conteudo"] = messages[1]["content"]

    novas = [PerguntaRespondidaSchema(pergunta="Pergunta desta tentativa", resposta_resumo="r", qualidade="fraca")]
    llms = _make_llms(perguntas_desta_tentativa=novas, planejador_on_invoke=capturar)

    run_evaluator(llms, transcript="t", historico_anterior=[], perguntas_anteriores=[])

    assert "Pergunta desta tentativa" in recebido["conteudo"]


def test_planejador_devolve_vazio_sem_nenhuma_pergunta_anterior_ou_desta_tentativa():
    llms = _make_llms(perguntas_desta_tentativa=[])
    result = run_evaluator(llms, transcript="t", historico_anterior=[], perguntas_anteriores=[])
    assert result["perguntas_sugeridas"] == ""
    # curto-circuito em Python — nunca chamou o LLM do planejador
    assert llms["planejador_perguntas"].captured_messages == []


def test_usuario_kb_nao_recebe_perguntas_nem_depende_do_objetivo_kb():
    novas = [PerguntaRespondidaSchema(pergunta="Pergunta bem específica de tecnologia X", resposta_resumo="r", qualidade="forte")]
    llms = _make_llms(perguntas_desta_tentativa=novas)

    result = run_evaluator(llms, transcript="t", historico_anterior=[])

    assert result["kb_usuario_atualizado"] == "kb usuario novo"
    usuario_kb_prompt = llms["usuario_kb"].captured_messages[0][1]["content"]
    assert "Pergunta bem específica de tecnologia X" not in usuario_kb_prompt
