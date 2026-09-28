from typing import Any

from fastapi import FastAPI, HTTPException, Request
from langchain_openai import ChatOpenAI

from app.agents.evaluator import HistoricoTentativa, MODEL, run_evaluator
from app.auth import VEREDITO_SERVICE_TOKEN_HEADER, verify_veredito_service_token
from app.config import APP_VERSION, load_settings

app = FastAPI(title="Ensaia IA")
settings = load_settings()
llm = ChatOpenAI(model=MODEL, api_key=settings.openai_api_key)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "env": settings.env, "version": APP_VERSION}


@app.post("/veredito")
def veredito(request: Request, payload: dict[str, Any]) -> dict:
    """
    `POST /tentativas/:id/finish` do backend Kotlin chama isto via
    `PythonVereditoLlmClient` (specs/fase-1-criterios.md) — contrato exato, não
    negociável aqui: `{transcript, historicoAnterior}` -> `{notaGeral, pontosFortes,
    pontosFracos, feedbackTexto, inputTokensFresh, inputTokensCached, outputTokens}`.
    """
    provided_token = request.headers.get(VEREDITO_SERVICE_TOKEN_HEADER)
    if not verify_veredito_service_token(provided_token, settings.veredito_service_token):
        raise HTTPException(status_code=401, detail="Token de serviço inválido.")

    historico: list[HistoricoTentativa] = payload.get("historicoAnterior", [])
    result = run_evaluator(llm, payload["transcript"], historico)
    output = result["output"]

    return {
        "notaGeral": output.nota_geral,
        "pontosFortes": output.pontos_fortes,
        "pontosFracos": output.pontos_fracos,
        "feedbackTexto": output.feedback_texto,
        "inputTokensFresh": result["input_tokens_fresh"],
        "inputTokensCached": result["input_tokens_cached"],
        "outputTokens": result["output_tokens"],
    }
