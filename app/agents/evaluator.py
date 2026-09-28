"""
Agente avaliador — grafo multi-nó (fase-3-criterios.md). Duas camadas:

1. Paralela: 6 nós de pilar (uma competência cada, agnóstica de vaga) + 1 nó de
   texto/feedback (pontos fortes/fracos, feedback, e a extração das perguntas feitas
   nesta tentativa — sem chamada de LLM extra pra isso).
2. Sequencial, só do lado do Objetivo: agregação de `nota_geral` (paralela ao resto
   desta camada) → `objetivo_kb` (reescreve o KB da vaga/track + funde a lista de
   perguntas, sem duplicata) → `planejador_perguntas` (só roda depois, precisa da
   lista já atualizada). Em paralelo com esses dois: `usuario_kb` (comportamental,
   agnóstico de vaga, sem histórico de perguntas).

Cada nó tem seu próprio modelo (todos `gpt-5-nano` por ora, mas a arquitetura não tem
um `MODEL` único compartilhado — ver `NODE_MODELS`).
"""

from pathlib import Path
from typing import Annotated, TypedDict

from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

NODE_MODELS: dict[str, str] = {
    "escuta_resposta": "gpt-5-nano",
    "clareza": "gpt-5-nano",
    "exemplos_concretos": "gpt-5-nano",
    "fechamento": "gpt-5-nano",
    "estrutura_resposta": "gpt-5-nano",
    "concisao": "gpt-5-nano",
    "texto_feedback": "gpt-5-nano",
    "objetivo_kb": "gpt-5-nano",
    "planejador_perguntas": "gpt-5-nano",
    "usuario_kb": "gpt-5-nano",
}

_PILARES: dict[str, str] = {
    "escuta_resposta": "pilar_escuta_resposta.md",
    "clareza": "pilar_clareza.md",
    "exemplos_concretos": "pilar_exemplos_concretos.md",
    "fechamento": "pilar_fechamento.md",
    "estrutura_resposta": "pilar_estrutura_resposta.md",
    "concisao": "pilar_concisao.md",
}


def build_llms(api_key: str) -> dict[str, ChatOpenAI]:
    return {name: ChatOpenAI(model=model, api_key=api_key) for name, model in NODE_MODELS.items()}


def _load_prompt(filename: str) -> str:
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8").strip()


def load_system_prompt() -> str:
    """Prompt do nó de texto/feedback — nome mantido por compatibilidade com o teste existente."""
    return _load_prompt("evaluator_system.md")


class HistoricoTentativa(TypedDict):
    numero: int
    notaGeral: str | None
    feedbackTexto: str | None


class PerguntaRespondida(TypedDict):
    pergunta: str
    respostaResumo: str
    qualidade: str


class PilarOutput(BaseModel):
    nota: float = Field(description="Nota de 0 a 10, pode ter uma casa decimal")


class PerguntaRespondidaSchema(BaseModel):
    pergunta: str
    resposta_resumo: str
    qualidade: str


class TextoFeedbackOutput(BaseModel):
    """Espelha o que `PythonVereditoLlmClient` (Kotlin) espera pra pontos_fortes/pontos_fracos/feedback_texto, mais a extração de perguntas."""

    pontos_fortes: list[str]
    pontos_fracos: list[str]
    feedback_texto: str
    perguntas: list[PerguntaRespondidaSchema]


class ObjetivoKbOutput(BaseModel):
    kb_atualizado: str


class PlanejadorOutput(BaseModel):
    perguntas_sugeridas: str


class UsuarioKbOutput(BaseModel):
    kb_atualizado: str


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


def _usage_from_raw(raw) -> dict:
    usage = raw.usage_metadata or {}
    cached = (usage.get("input_token_details") or {}).get("cache_read", 0)
    return {
        "input_tokens_fresh": max(usage.get("input_tokens", 0) - cached, 0),
        "input_tokens_cached": cached,
        "output_tokens": usage.get("output_tokens", 0),
    }


def _merge_perguntas(
    anteriores: list[PerguntaRespondida], novas: list[PerguntaRespondidaSchema]
) -> list[PerguntaRespondida]:
    """Funde a lista sem duplicar pergunta idêntica (mesmo texto exato) — garantido em
    código, não deixado a critério do LLM (fase-3-criterios.md)."""
    vistas = {p["pergunta"] for p in anteriores}
    merged: list[PerguntaRespondida] = list(anteriores)
    for p in novas:
        if p.pergunta not in vistas:
            merged.append({"pergunta": p.pergunta, "respostaResumo": p.resposta_resumo, "qualidade": p.qualidade})
            vistas.add(p.pergunta)
    return merged


class EvaluatorState(TypedDict):
    transcript: object
    historico_anterior: list[HistoricoTentativa]
    kb_objetivo_anterior: str | None
    perguntas_anteriores: list[PerguntaRespondida]
    kb_usuario_anterior: str | None

    nota_escuta_resposta: float
    nota_clareza: float
    nota_exemplos_concretos: float
    nota_fechamento: float
    nota_estrutura_resposta: float
    nota_concisao: float
    nota_geral: float

    pontos_fortes: list[str]
    pontos_fracos: list[str]
    feedback_texto: str
    perguntas_desta_tentativa: list[PerguntaRespondidaSchema]

    kb_objetivo_atualizado: str
    perguntas_atualizadas: list[PerguntaRespondida]
    perguntas_sugeridas: str
    kb_usuario_atualizado: str

    usages: Annotated[list[dict], lambda a, b: a + b]


def _pilar_node(state: EvaluatorState, llm, prompt_filename: str, state_key: str) -> dict:
    structured_llm = llm.with_structured_output(PilarOutput, include_raw=True)
    result = structured_llm.invoke(
        [
            {"role": "system", "content": _load_prompt(prompt_filename)},
            {"role": "user", "content": _build_user_content(state["transcript"], state["historico_anterior"])},
        ],
    )
    return {state_key: result["parsed"].nota, "usages": [_usage_from_raw(result["raw"])]}


def _texto_feedback_node(state: EvaluatorState, llm) -> dict:
    structured_llm = llm.with_structured_output(TextoFeedbackOutput, include_raw=True)
    result = structured_llm.invoke(
        [
            {"role": "system", "content": load_system_prompt()},
            {"role": "user", "content": _build_user_content(state["transcript"], state["historico_anterior"])},
        ],
    )
    parsed = result["parsed"]
    return {
        "pontos_fortes": parsed.pontos_fortes,
        "pontos_fracos": parsed.pontos_fracos,
        "feedback_texto": parsed.feedback_texto,
        "perguntas_desta_tentativa": parsed.perguntas,
        "usages": [_usage_from_raw(result["raw"])],
    }


def _agregacao_node(state: EvaluatorState) -> dict:
    pilares = [
        state["nota_escuta_resposta"],
        state["nota_clareza"],
        state["nota_exemplos_concretos"],
        state["nota_fechamento"],
        state["nota_estrutura_resposta"],
        state["nota_concisao"],
    ]
    return {"nota_geral": sum(pilares) / len(pilares)}


def _objetivo_kb_node(state: EvaluatorState, llm) -> dict:
    anterior = state["kb_objetivo_anterior"] or "(nenhum ainda — esta é a primeira tentativa desta vaga/track.)"
    resumo_tentativa = (
        f"Pontos fortes: {'; '.join(state['pontos_fortes']) or '(nenhum)'}\n"
        f"Pontos fracos: {'; '.join(state['pontos_fracos']) or '(nenhum)'}\n"
        f"Feedback: {state['feedback_texto']}"
    )
    structured_llm = llm.with_structured_output(ObjetivoKbOutput, include_raw=True)
    result = structured_llm.invoke(
        [
            {"role": "system", "content": _load_prompt("objetivo_kb_writer.md")},
            {
                "role": "user",
                "content": f"Base de conhecimento anterior:\n{anterior}\n\nTentativa mais recente:\n{resumo_tentativa}",
            },
        ],
    )
    perguntas_atualizadas = _merge_perguntas(state["perguntas_anteriores"], state["perguntas_desta_tentativa"])
    return {
        "kb_objetivo_atualizado": result["parsed"].kb_atualizado,
        "perguntas_atualizadas": perguntas_atualizadas,
        "usages": [_usage_from_raw(result["raw"])],
    }


def _planejador_perguntas_node(state: EvaluatorState, llm) -> dict:
    perguntas = state["perguntas_atualizadas"]
    if not perguntas:
        return {"perguntas_sugeridas": ""}

    lista = "\n".join(
        f"- \"{p['pergunta']}\" — resposta: {p['respostaResumo']} (qualidade: {p['qualidade']})" for p in perguntas
    )
    structured_llm = llm.with_structured_output(PlanejadorOutput, include_raw=True)
    result = structured_llm.invoke(
        [
            {"role": "system", "content": _load_prompt("planejador_perguntas.md")},
            {"role": "user", "content": f"Perguntas já feitas nesta vaga/track, com qualidade da resposta:\n{lista}"},
        ],
    )
    return {"perguntas_sugeridas": result["parsed"].perguntas_sugeridas, "usages": [_usage_from_raw(result["raw"])]}


def _usuario_kb_node(state: EvaluatorState, llm) -> dict:
    anterior = state["kb_usuario_anterior"] or "(nenhum ainda.)"
    resumo_tentativa = (
        f"Pontos fortes: {'; '.join(state['pontos_fortes']) or '(nenhum)'}\n"
        f"Pontos fracos: {'; '.join(state['pontos_fracos']) or '(nenhum)'}\n"
        f"Feedback: {state['feedback_texto']}"
    )
    structured_llm = llm.with_structured_output(UsuarioKbOutput, include_raw=True)
    result = structured_llm.invoke(
        [
            {"role": "system", "content": _load_prompt("usuario_kb_writer.md")},
            {
                "role": "user",
                "content": f"Base de conhecimento anterior:\n{anterior}\n\nTentativa mais recente:\n{resumo_tentativa}",
            },
        ],
    )
    return {"kb_usuario_atualizado": result["parsed"].kb_atualizado, "usages": [_usage_from_raw(result["raw"])]}


def build_graph(llms: dict[str, ChatOpenAI]):
    graph = StateGraph(EvaluatorState)

    for nome, prompt_filename in _PILARES.items():
        state_key = f"nota_{nome}"
        graph.add_node(
            nome,
            lambda state, _llm=llms[nome], _pf=prompt_filename, _sk=state_key: _pilar_node(state, _llm, _pf, _sk),
        )

    graph.add_node("texto_feedback", lambda state: _texto_feedback_node(state, llms["texto_feedback"]))
    graph.add_node("agregacao", _agregacao_node)
    graph.add_node("objetivo_kb", lambda state: _objetivo_kb_node(state, llms["objetivo_kb"]))
    graph.add_node("planejador_perguntas", lambda state: _planejador_perguntas_node(state, llms["planejador_perguntas"]))
    graph.add_node("usuario_kb", lambda state: _usuario_kb_node(state, llms["usuario_kb"]))

    for nome in _PILARES:
        graph.set_entry_point(nome)
        graph.add_edge(nome, "agregacao")
    graph.set_entry_point("texto_feedback")

    graph.add_edge("agregacao", END)
    graph.add_edge("texto_feedback", "objetivo_kb")
    graph.add_edge("texto_feedback", "usuario_kb")
    graph.add_edge("objetivo_kb", "planejador_perguntas")
    graph.add_edge("planejador_perguntas", END)
    graph.add_edge("usuario_kb", END)

    return graph.compile()


def run_evaluator(
    llms: dict[str, ChatOpenAI],
    transcript: object,
    historico_anterior: list[HistoricoTentativa],
    kb_objetivo_anterior: str | None = None,
    perguntas_anteriores: list[PerguntaRespondida] | None = None,
    kb_usuario_anterior: str | None = None,
) -> EvaluatorState:
    app = build_graph(llms)
    result = app.invoke(
        {
            "transcript": transcript,
            "historico_anterior": historico_anterior,
            "kb_objetivo_anterior": kb_objetivo_anterior,
            "perguntas_anteriores": perguntas_anteriores or [],
            "kb_usuario_anterior": kb_usuario_anterior,
            "usages": [],
        },
    )
    return result
