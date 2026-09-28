"""
Testa `run_interviewer`/`build_contexto_vaga` de ponta a ponta (passando pelo LangGraph
de verdade), sem chamar a OpenAI — `FakeLLM` imita só a fatia da interface do
`ChatOpenAI` usada aqui (`.invoke(messages) -> objeto com .content`), mesmo espírito do
`FakeLLM` usado pro agente avaliador.
"""

from types import SimpleNamespace

from app.agents.interviewer import build_contexto_vaga, load_system_prompt, run_interviewer


class FakeLLM:
    def __init__(self, respostas: list[str]):
        self._respostas = iter(respostas)
        self.captured_messages: list[list[dict]] = []

    def invoke(self, messages: list[dict]):
        self.captured_messages.append(messages)
        return SimpleNamespace(content=next(self._respostas))


def test_turno_de_abertura_usa_o_prompt_estatico_e_o_contexto_da_vaga():
    llm = FakeLLM(["Oi! Me conta sobre sua experiência com Python."])
    contexto = build_contexto_vaga("Engenheiro de Software", "Time de backend Python", "Técnico")

    resposta = run_interviewer(llm, contexto, turnos=[])

    assert resposta == "Oi! Me conta sobre sua experiência com Python."
    mensagens = llm.captured_messages[0]
    assert mensagens[0] == {"role": "system", "content": load_system_prompt()}
    conteudos = [m["content"] for m in mensagens]
    assert any("Engenheiro de Software" in c for c in conteudos)
    assert any("primeira mensagem da sessão" in c for c in conteudos)


def test_turno_seguinte_inclui_o_historico_da_conversa_e_nao_repete_a_instrucao_de_abertura():
    llm = FakeLLM(["Legal, e como você lidou com o prazo apertado?"])
    contexto = build_contexto_vaga("Engenheiro de Software", None, None)
    turnos = [
        {"role": "assistant", "content": "Oi! Me conta sobre sua experiência com Python."},
        {"role": "user", "content": "Trabalhei 3 anos com Django."},
    ]

    resposta = run_interviewer(llm, contexto, turnos)

    assert resposta == "Legal, e como você lidou com o prazo apertado?"
    mensagens = llm.captured_messages[0]
    assert {"role": "assistant", "content": "Oi! Me conta sobre sua experiência com Python."} in mensagens
    assert {"role": "user", "content": "Trabalhei 3 anos com Django."} in mensagens
    assert not any("primeira mensagem da sessão" in m["content"] for m in mensagens)


def test_estilo_nulo_cai_pro_default_tranquilo():
    contexto = build_contexto_vaga("Cargo X", "Descrição", None)
    assert "Tranquilo" in contexto


def test_descricao_nula_mostra_texto_de_fallback():
    contexto = build_contexto_vaga("Cargo X", None, "Duro")
    assert "(não informada)" in contexto
    assert "Duro" in contexto
