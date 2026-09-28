# Fase 1 — Agente avaliador + `POST /veredito`

> Ver `specs/plano-arquitetura.md` pro desenho completo. Esta fase fecha o lado Python
> do contrato já implementado no backend Kotlin
> (`ensa-ia-back/specs/integracao-voz-criterios.md`) — o endpoint que
> `PythonVereditoLlmClient.kt` já chama.

## Objetivo

Gerar veredito (nota, pontos fortes/fracos, feedback) a partir de um transcript, com a
MESMA qualidade do que já roda em produção hoje (`OpenAiVereditoLlmClient.kt`) — o
prompt é portado literalmente, não reinventado. Primeiro agente real do serviço
(LangGraph, um nó só por enquanto — o agente entrevistador é fase separada).

## Contrato exato (já implementado do lado Kotlin, não é negociável aqui)

- **Request**: `POST /veredito`, header `x-veredito-service-token: <segredo>`, corpo
  `{"transcript": <json>, "historicoAnterior": [{"numero": int, "notaGeral": "<string ou null>", "feedbackTexto": "<string ou null>"}]}`.
- **Response 200**: `{"notaGeral": float, "pontosFortes": [...], "pontosFracos": [...], "feedbackTexto": str, "inputTokensFresh": int, "inputTokensCached": int, "outputTokens": int}`.
- **401** se o header estiver ausente ou não bater (comparação em tempo constante).
- Modelo: `gpt-5-nano` (mesmo de hoje). Prompt: cópia literal do `SYSTEM_PROMPT` de
  `OpenAiVereditoLlmClient.kt` (linhas 27-36 do arquivo original).

## Decisões

1. **Auth simples, sem LangGraph no meio**: comparação de header em tempo constante
   (`hmac.compare_digest`), antes de qualquer chamada ao agente — 401 nem entra no
   grafo.
2. **Agente avaliador = grafo de um nó só** (`app/agents/evaluator.py`): recebe
   `transcript`+`historicoAnterior`, monta o prompt (mesmo formato de
   `buildUserContent` do Kotlin: histórico + transcript), chama `gpt-5-nano` via
   `langchain-openai` com `.with_structured_output()` (schema Pydantic espelhando
   `VereditoOutputSchema`), devolve o resultado. Tracing via LangSmith automático
   (basta as env vars `LANGSMITH_TRACING`/`LANGSMITH_API_KEY` estarem setadas — sem
   código extra).
3. **Prompt em arquivo próprio** (`app/prompts/evaluator_system.md`), não string no
   meio do código — mesma convenção do `CLAUDE.md` deste repo.
4. **Contagem de tokens**: `langchain-openai` expõe `usage_metadata` na resposta
   (`input_tokens`, `output_tokens`, `input_token_details.cache_read`) — mapeado pros
   três campos que o Kotlin espera (`inputTokensFresh = input_tokens - cache_read`).

## Critérios de aceite

- [x] `POST /veredito` sem header ou com header errado → `401`, nunca chama a OpenAI.
- [x] `POST /veredito` com header certo → chama o agente avaliador, devolve o shape
      exato que `PythonVereditoLlmClient.kt` espera. Confirmado com chamada real (não
      só mockada) via Docker — ver resultado no commit.
- [x] Agente avaliador testado com a chamada à OpenAI mockada — caso "primeira
      tentativa" (sem histórico), "com histórico anterior" e "campos nulos no
      histórico" (mesmos fallbacks do Kotlin).
- [x] Prompt idêntico (char a char) ao `SYSTEM_PROMPT` do Kotlin — teste compara as
      duas strings direto.
- [x] `pytest` 100% verde (8 testes, ~1.3s, sem nenhuma chamada de rede).

## Fora de escopo

- Agente entrevistador / WebSocket `/interview` — fase seguinte.
- Validação do token de voz (`VoiceToken.verify`) — só é usada pelo WebSocket, entra
  junto com o agente entrevistador.
