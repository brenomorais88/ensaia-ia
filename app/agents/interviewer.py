"""
Agente entrevistador — conduz a conversa ao vivo (fase-2-criterios.md). Prompt de
sistema estático (`app/prompts/interviewer_system.md`, comportamento/regras) +
contexto da vaga montado em runtime (mesmo espírito do `_build_user_content` do
avaliador) + histórico de turnos da sessão atual, mantido em memória só durante a
conexão do WebSocket.

Grafo de um nó só (LangGraph), mesmo padrão do avaliador — o entrevistador não precisa
de ramificação nenhuma pra decidir a próxima fala.
"""

from pathlib import Path
from typing import TypedDict

from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph

MODEL = "gpt-5-nano"  # mesma decisão de custo do avaliador (fase-1-criterios.md)
_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "interviewer_system.md"

_ESTILO_PADRAO = "Tranquilo"
_DESCRICAO_POR_ESTILO: dict[str, str] = {
    "Tranquilo": "tom acolhedor, perguntas abertas, ritmo calmo.",
    "Duro": "tom desafiador, perguntas diretas, pouco espaço pra rodeios.",
    "Técnico": "foco em profundidade técnica da vaga, perguntas específicas de conhecimento.",
    "Comportamental": "perguntas situacionais (o que a pessoa fez em uma situação real do passado).",
}


def load_system_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8").strip()


class Turno(TypedDict):
    role: str  # "user" | "assistant"
    content: str


def build_contexto_vaga(
    vaga_titulo: str,
    vaga_descricao: str | None,
    estilo_entrevistador: str | None,
    kb_objetivo: str | None = None,
    perguntas_sugeridas: str | None = None,
    kb_usuario: str | None = None,
) -> str:
    """
    `kb_objetivo`/`perguntas_sugeridas`/`kb_usuario` vêm do avaliador da tentativa
    anterior deste mesmo Objetivo (fase-3-criterios.md) — o front busca no Kotlin e
    repassa na mensagem `start` do WebSocket. Ausentes na primeira tentativa de um
    Objetivo novo, sem problema (entrevista roda só com a vaga).
    """
    estilo = estilo_entrevistador or _ESTILO_PADRAO
    estilo_descricao = _DESCRICAO_POR_ESTILO.get(estilo, _DESCRICAO_POR_ESTILO[_ESTILO_PADRAO])
    descricao = vaga_descricao or "(não informada)"
    contexto = (
        f"Vaga: {vaga_titulo}\n"
        f"Descrição da vaga: {descricao}\n"
        f"Estilo da entrevista: {estilo} — {estilo_descricao}"
    )
    if kb_objetivo:
        contexto += f"\n\nO que já se sabe sobre a pessoa nesta vaga/track (tentativas anteriores):\n{kb_objetivo}"
    if perguntas_sugeridas:
        contexto += f"\n\nSugestão do que explorar nesta entrevista:\n{perguntas_sugeridas}"
    if kb_usuario:
        contexto += f"\n\nPerfil comportamental conhecido da pessoa (de outras vagas também):\n{kb_usuario}"
    return contexto


class InterviewerState(TypedDict):
    contexto_vaga: str
    turnos: list[Turno]
    resposta: str | None


def _generate_node(state: InterviewerState, llm: ChatOpenAI) -> InterviewerState:
    messages: list[dict] = [{"role": "system", "content": load_system_prompt()}]

    messages.append({"role": "system", "content": f"Contexto da vaga:\n{state['contexto_vaga']}"})

    if not state["turnos"]:
        messages.append(
            {
                "role": "user",
                "content": "Esta é a primeira mensagem da sessão. Cumprimente brevemente e faça a primeira pergunta.",
            },
        )
    else:
        messages.extend({"role": t["role"], "content": t["content"]} for t in state["turnos"])

    result = llm.invoke(messages)
    return {**state, "resposta": result.content}


def build_graph(llm: ChatOpenAI):
    graph = StateGraph(InterviewerState)
    graph.add_node("generate", lambda state: _generate_node(state, llm))
    graph.set_entry_point("generate")
    graph.add_edge("generate", END)
    return graph.compile()


def run_interviewer(llm: ChatOpenAI, contexto_vaga: str, turnos: list[Turno]) -> str:
    app = build_graph(llm)
    result = app.invoke({"contexto_vaga": contexto_vaga, "turnos": turnos, "resposta": None})
    return result["resposta"]
