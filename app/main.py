import base64
import time
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from langchain_openai import ChatOpenAI

from app.agents.evaluator import HistoricoTentativa, PerguntaRespondida, build_llms, run_evaluator
from app.agents.interviewer import MODEL as INTERVIEWER_MODEL, Turno, build_contexto_vaga, run_interviewer
from app.auth import VEREDITO_SERVICE_TOKEN_HEADER, verify_veredito_service_token, verify_voice_token
from app.config import APP_VERSION, load_settings
from app.pipeline import stt, tts

app = FastAPI(title="Ensaia IA")
settings = load_settings()
llm = ChatOpenAI(model=INTERVIEWER_MODEL, api_key=settings.openai_api_key)
evaluator_llms = build_llms(settings.openai_api_key)
openai_client = stt.build_client(settings.openai_api_key)
polly_client = tts.build_client(settings.aws_access_key_id, settings.aws_secret_access_key, settings.aws_region)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "env": settings.env, "version": APP_VERSION}


@app.post("/veredito")
def veredito(request: Request, payload: dict[str, Any]) -> dict:
    """
    `POST /tentativas/:id/finish` do backend Kotlin chama isto via
    `PythonVereditoLlmClient` (fase-3-criterios.md) — contrato:
    `{transcript, historicoAnterior, kbObjetivoAnterior?, perguntasAnteriores?,
    kbUsuarioAnterior?}` -> `{notaGeral, pontosFortes, pontosFracos, feedbackTexto,
    notaEscutaResposta, notaClareza, notaExemplosConcretos, notaFechamento,
    notaEstruturaResposta, notaConcisao, kbObjetivoAtualizado, perguntasAtualizadas,
    perguntasSugeridas, kbUsuarioAtualizado, inputTokensFresh, inputTokensCached,
    outputTokens}`.
    """
    provided_token = request.headers.get(VEREDITO_SERVICE_TOKEN_HEADER)
    if not verify_veredito_service_token(provided_token, settings.veredito_service_token):
        raise HTTPException(status_code=401, detail="Token de serviço inválido.")

    historico: list[HistoricoTentativa] = payload.get("historicoAnterior", [])
    perguntas_anteriores: list[PerguntaRespondida] = payload.get("perguntasAnteriores") or []
    result = run_evaluator(
        evaluator_llms,
        payload["transcript"],
        historico,
        kb_objetivo_anterior=payload.get("kbObjetivoAnterior"),
        perguntas_anteriores=perguntas_anteriores,
        kb_usuario_anterior=payload.get("kbUsuarioAnterior"),
    )

    tokens = {"input_tokens_fresh": 0, "input_tokens_cached": 0, "output_tokens": 0}
    for usage in result["usages"]:
        for key in tokens:
            tokens[key] += usage.get(key, 0)

    return {
        "notaGeral": result["nota_geral"],
        "pontosFortes": result["pontos_fortes"],
        "pontosFracos": result["pontos_fracos"],
        "feedbackTexto": result["feedback_texto"],
        "notaEscutaResposta": result["nota_escuta_resposta"],
        "notaClareza": result["nota_clareza"],
        "notaExemplosConcretos": result["nota_exemplos_concretos"],
        "notaFechamento": result["nota_fechamento"],
        "notaEstruturaResposta": result["nota_estrutura_resposta"],
        "notaConcisao": result["nota_concisao"],
        "kbObjetivoAtualizado": result["kb_objetivo_atualizado"],
        "perguntasAtualizadas": result["perguntas_atualizadas"],
        "perguntasSugeridas": result["perguntas_sugeridas"],
        "kbUsuarioAtualizado": result["kb_usuario_atualizado"],
        "inputTokensFresh": tokens["input_tokens_fresh"],
        "inputTokensCached": tokens["input_tokens_cached"],
        "outputTokens": tokens["output_tokens"],
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
        start["vagaTitulo"],
        start.get("vagaDescricao"),
        start.get("estiloEntrevistador"),
        kb_objetivo=start.get("kbObjetivo"),
        perguntas_sugeridas=start.get("perguntasSugeridas"),
        kb_usuario=start.get("kbUsuario"),
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
