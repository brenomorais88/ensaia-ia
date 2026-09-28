"""
Agente avaliador — gera o veredito (nota, pontos fortes/fracos, feedback) a partir de
um transcript. Prompt idêntico (fase-1-criterios.md §2) ao que já roda em produção no
backend Kotlin (`OpenAiVereditoLlmClient.kt`) — portado, não reinventado.

Grafo de um nó só por enquanto (LangGraph) — o agente entrevistador (fase separada) é
que vai justificar um grafo de verdade, com mais de um nó.
"""

from pathlib import Path
from typing import TypedDict

from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

MODEL = "gpt-5-nano"  # mesmo modelo do Kotlin — decisão fase-5-criterios.md §6.9 do backend
_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "evaluator_system.md"


def load_system_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8").strip()


class HistoricoTentativa(TypedDict):
    numero: int
    notaGeral: str | None
    feedbackTexto: str | None


class VereditoOutput(BaseModel):
    """Espelha `VereditoOutputSchema` do Kotlin (`OpenAiVereditoLlmClient.kt`) — mesmos 4 campos, mesmos nomes."""

    nota_geral: float = Field(description="Nota de 0 a 10, pode ter uma casa decimal")
    pontos_fortes: list[str]
    pontos_fracos: list[str]
    feedback_texto: str


class EvaluatorState(TypedDict):
    transcript: object
    historico_anterior: list[HistoricoTentativa]
    output: VereditoOutput | None
    input_tokens_fresh: int
    input_tokens_cached: int
    output_tokens: int


def _build_user_content(transcript: object, historico: list[HistoricoTentativa]) -> str:
    """Mesmo formato de `buildUserContent` no Kotlin — histórico primeiro, transcript depois."""
    if not historico:
        historico_texto = "Nenhuma tentativa anterior neste Ensaio — esta é a primeira."
    else:
        historico_texto = "\n".join(
            f"Tentativa {t['numero']}: nota {t['notaGeral'] or 'N/A'} — {t['feedbackTexto'] or '(sem feedback)'}"
            for t in historico
        )
    return f"Histórico de tentativas anteriores:\n{historico_texto}\n\nTranscript da tentativa atual:\n{transcript}"


def _generate_node(state: EvaluatorState, llm: ChatOpenAI) -> EvaluatorState:
    structured_llm = llm.with_structured_output(VereditoOutput, include_raw=True)
    result = structured_llm.invoke(
        [
            {"role": "system", "content": load_system_prompt()},
            {"role": "user", "content": _build_user_content(state["transcript"], state["historico_anterior"])},
        ],
    )

    raw_message = result["raw"]
    usage = raw_message.usage_metadata or {}
    cached = (usage.get("input_token_details") or {}).get("cache_read", 0)

    return {
        **state,
        "output": result["parsed"],
        "input_tokens_fresh": max(usage.get("input_tokens", 0) - cached, 0),
        "input_tokens_cached": cached,
        "output_tokens": usage.get("output_tokens", 0),
    }


def build_graph(llm: ChatOpenAI):
    graph = StateGraph(EvaluatorState)
    graph.add_node("generate", lambda state: _generate_node(state, llm))
    graph.set_entry_point("generate")
    graph.add_edge("generate", END)
    return graph.compile()


def run_evaluator(llm: ChatOpenAI, transcript: object, historico_anterior: list[HistoricoTentativa]) -> EvaluatorState:
    app = build_graph(llm)
    return app.invoke(
        {
            "transcript": transcript,
            "historico_anterior": historico_anterior,
            "output": None,
            "input_tokens_fresh": 0,
            "input_tokens_cached": 0,
            "output_tokens": 0,
        },
    )
