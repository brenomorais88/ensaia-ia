import base64
import time
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from langchain_openai import ChatOpenAI

from app.agents.evaluator import HistoricoTentativa, MODEL, run_evaluator
from app.agents.interviewer import Turno, build_contexto_vaga, run_interviewer
from app.auth import VEREDITO_SERVICE_TOKEN_HEADER, verify_veredito_service_token, verify_voice_token
from app.config import APP_VERSION, load_settings
from app.pipeline import stt, tts

app = FastAPI(title="Ensaia IA")
settings = load_settings()
llm = ChatOpenAI(model=MODEL, api_key=settings.openai_api_key)
openai_client = stt.build_client(settings.openai_api_key)
polly_client = tts.build_client(settings.aws_access_key_id, settings.aws_secret_access_key, settings.aws_region)


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


async def _send_pergunta(websocket: WebSocket, texto_usuario: str | None, resposta: str) -> None:
    audio = tts.synthesize(polly_client, resposta)
    await websocket.send_json(
        {
            "tipo": "pergunta",
            "textoUsuario": texto_usuario,
            "textoAssistente": resposta,
            "audioBase64": base64.b64encode(audio).decode("ascii"),
            "mimeType": tts.MIME_TYPE,
        },
    )


@app.websocket("/interview")
async def interview(websocket: WebSocket) -> None:
    """
    Entrevista ao vivo, turno a turno (fase-2-criterios.md). Token efêmero (emitido
    pelo Kotlin em `POST /tentativas/:id/voice-token`) vem na query string do
    handshake — validado ANTES de aceitar a conexão, nunca chama STT/LLM/TTS se
    inválido/expirado.
    """
    token = websocket.query_params.get("token")
    if verify_voice_token(token, settings.voice_token_secret, int(time.time())) is None:
        await websocket.close(code=4401)
        return

    await websocket.accept()

    try:
        start = await websocket.receive_json()
    except WebSocketDisconnect:
        return

    if start.get("tipo") != "start":
        await websocket.close(code=4400)
        return

    contexto_vaga = build_contexto_vaga(
        start["vagaTitulo"], start.get("vagaDescricao"), start.get("estiloEntrevistador"),
    )
    turnos: list[Turno] = []

    try:
        resposta = run_interviewer(llm, contexto_vaga, turnos)
        turnos.append({"role": "assistant", "content": resposta})
        await _send_pergunta(websocket, texto_usuario=None, resposta=resposta)
    except Exception as exc:  # qualquer falha vira mensagem de erro pro cliente, conexão continua
        await websocket.send_json({"tipo": "erro", "mensagem": str(exc)})

    while True:
        try:
            message = await websocket.receive_json()
        except WebSocketDisconnect:
            return

        tipo = message.get("tipo")

        if tipo == "end":
            await websocket.send_json({"tipo": "encerrado"})
            await websocket.close()
            return

        if tipo != "audio":
            await websocket.send_json({"tipo": "erro", "mensagem": f"Tipo de mensagem desconhecido: {tipo}"})
            continue

        try:
            audio_bytes = base64.b64decode(message["audioBase64"])
            texto_usuario = stt.transcribe(openai_client, audio_bytes, message.get("mimeType", "audio/webm"))
            # só grava em `turnos` depois que os dois passos derem certo — senão um turno
            # do usuário fica preso no histórico sem nunca ter sido enviado ao cliente.
            resposta = run_interviewer(llm, contexto_vaga, [*turnos, {"role": "user", "content": texto_usuario}])
            turnos.append({"role": "user", "content": texto_usuario})
            turnos.append({"role": "assistant", "content": resposta})
            await _send_pergunta(websocket, texto_usuario=texto_usuario, resposta=resposta)
        except Exception as exc:  # mesma razão do try acima
            await websocket.send_json({"tipo": "erro", "mensagem": str(exc)})
