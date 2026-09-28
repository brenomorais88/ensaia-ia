"""
Testa `run_evaluator`/`build_graph` de ponta a ponta (passando pelo LangGraph de
verdade), sem chamar a OpenAI de verdade — `FakeLLM` imita só a fatia da interface do
`ChatOpenAI` que o código usa (`with_structured_output(...).invoke(...)`), mesmo
espírito do `MockEngine` usado no lado Kotlin pra testar `PythonVereditoLlmClient`.
"""

from types import SimpleNamespace

from app.agents.evaluator import VereditoOutput, run_evaluator


class _FakeStructuredLLM:
    def __init__(self, parsed: VereditoOutput, usage_metadata: dict, captured: list):
        self._parsed = parsed
        self._usage = usage_metadata
        self._captured = captured

    def invoke(self, messages):
        self._captured.append(messages)
        return {"raw": SimpleNamespace(usage_metadata=self._usage), "parsed": self._parsed}


class FakeLLM:
    def __init__(self, parsed: VereditoOutput, usage_metadata: dict):
        self.captured_messages: list = []
        self._parsed = parsed
        self._usage = usage_metadata

    def with_structured_output(self, schema, include_raw=True):
        return _FakeStructuredLLM(self._parsed, self._usage, self.captured_messages)


def test_primeira_tentativa_sem_historico_usa_texto_padrao_e_extrai_tokens_frescos():
    output = VereditoOutput(nota_geral=7.5, pontos_fortes=["a"], pontos_fracos=["b"], feedback_texto="ok")
    usage = {"input_tokens": 100, "output_tokens": 50, "input_token_details": {"cache_read": 0}}
    llm = FakeLLM(output, usage)

    result = run_evaluator(llm, transcript="transcript de teste", historico_anterior=[])

    assert result["output"] == output
    assert result["input_tokens_fresh"] == 100
    assert result["input_tokens_cached"] == 0
    assert result["output_tokens"] == 50

    user_message = llm.captured_messages[0][1]["content"]
    assert "Nenhuma tentativa anterior neste Ensaio — esta é a primeira." in user_message
    assert "transcript de teste" in user_message


def test_com_historico_anterior_monta_o_texto_de_evolucao_e_desconta_tokens_cacheados():
    output = VereditoOutput(nota_geral=8.0, pontos_fortes=[], pontos_fracos=[], feedback_texto="melhorou")
    usage = {"input_tokens": 300, "output_tokens": 80, "input_token_details": {"cache_read": 120}}
    llm = FakeLLM(output, usage)

    historico = [{"numero": 1, "notaGeral": "6.0", "feedbackTexto": "faltou estrutura"}]
    result = run_evaluator(llm, transcript="segunda tentativa", historico_anterior=historico)

    assert result["input_tokens_fresh"] == 180  # 300 - 120
    assert result["input_tokens_cached"] == 120

    user_message = llm.captured_messages[0][1]["content"]
    assert "Tentativa 1: nota 6.0 — faltou estrutura" in user_message


def test_historico_com_campos_nulos_usa_os_mesmos_textos_de_fallback_do_kotlin():
    output = VereditoOutput(nota_geral=5.0, pontos_fortes=[], pontos_fracos=[], feedback_texto="x")
    llm = FakeLLM(output, {"input_tokens": 10, "output_tokens": 5, "input_token_details": {"cache_read": 0}})

    historico = [{"numero": 2, "notaGeral": None, "feedbackTexto": None}]
    run_evaluator(llm, transcript="t", historico_anterior=historico)

    user_message = llm.captured_messages[0][1]["content"]
    assert "Tentativa 2: nota N/A — (sem feedback)" in user_message
