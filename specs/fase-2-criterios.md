# Fase 2 — Agente entrevistador + `WebSocket /interview`

> Ver `specs/plano-arquitetura.md` pro desenho completo. Esta fase fecha a Etapa 1 do
> plano: o motor de entrevista ao vivo, turno a turno, no serviço Python. A Etapa 3
> (frontend real — `getUserMedia`, WebSocket no browser) continua fora de escopo aqui.

## Contexto herdado (não é negociável aqui)

- `POST /tentativas/:id/voice-token` (já implementado no Kotlin,
  `integracao-voz-criterios.md`) devolve **só** `{token, wsUrl}` — nenhum dado da vaga
  vai embutido no token. O token (`VoiceToken.kt`) é `"$tentativaId:$userId:$exp:$hmac"`,
  HMAC-SHA256 com `VOICE_TOKEN_SECRET` compartilhado.
- `Ensaio` tem `vagaTitulo` (obrigatório), `vagaDescricao` (opcional),
  `estiloEntrevistador` (opcional, um de `Tranquilo`/`Duro`/`Técnico`/`Comportamental`).
  Não existe banco de perguntas, seniority, idioma ou contagem de perguntas em nenhum
  dos dois repos — a entrevista é conduzida livremente pelo agente a partir desses 3
  campos.

## Decisão fechada nesta fase: como o contexto da vaga chega no Python

Como o voice-token não carrega contexto, e o Python não deve consultar o Kotlin a cada
sessão (arquitetura já decidida), **o front manda o contexto como a primeira mensagem
do WebSocket**, logo após a conexão ser aceita — ele já tem esses dados (usa pra
renderizar a própria tela). Ver contrato abaixo.

## Autenticação no handshake

- Token vai como query string: `wss://.../interview?token=<token>`.
- Servidor valida ANTES de aceitar a conexão (`websocket.accept()`): reimplementa
  `VoiceToken.verify` — payload `"$tentativaId:$userId:$exp"`, HMAC-SHA256 com
  `VOICE_TOKEN_SECRET`, comparação em tempo constante (`hmac.compare_digest`),
  confere expiração. Token ausente, malformado, com assinatura errada ou expirado →
  fecha o WebSocket com código `4401` sem aceitar (nunca chama a OpenAI/Polly).
- Diferente do `VoiceToken.kt` (que só usa a verificação em teste, pra provar que
  `mint` funciona), aqui a verificação é real e roda em toda conexão.

## Contrato do WebSocket (JSON em toda mensagem, sem frames binários)

**Cliente → servidor:**
- `{"tipo": "start", "vagaTitulo": str, "vagaDescricao": str | null, "estiloEntrevistador": str | null}`
  — primeira mensagem, obrigatória. `estiloEntrevistador` ausente/null vira `"Tranquilo"`.
- `{"tipo": "audio", "audioBase64": str, "mimeType": str}` — um turno de fala do
  usuário (arquivo completo, ex. webm/opus gravado via `MediaRecorder`), em base64.
- `{"tipo": "end"}` — encerra a sessão por decisão do usuário/front (o Python nunca
  decide sozinho terminar a entrevista).

**Servidor → cliente:**
- `{"tipo": "pergunta", "textoUsuario": str | null, "textoAssistente": str, "audioBase64": str, "mimeType": "audio/mpeg"}`
  — enviada uma vez logo após `start` (abertura, `textoUsuario` null) e uma vez depois
  de cada `audio` (`textoUsuario` = transcrição do áudio recebido). O front acumula
  `textoUsuario`/`textoAssistente` de cada mensagem pra montar o transcript completo
  que vai pro `POST /tentativas/:id/finish` (contrato desse endpoint não muda).
- `{"tipo": "erro", "mensagem": str}` — falha ao transcrever/gerar/sintetizar; conexão
  continua aberta (front decide se tenta de novo ou encerra).
- `{"tipo": "encerrado"}` — resposta ao `end`, servidor fecha a conexão em seguida.

## Pipeline por turno

1. Decodifica `audioBase64` → bytes.
2. STT: Whisper (`openai.audio.transcriptions`, modelo `whisper-1`) → texto.
3. Agente entrevistador (LangGraph, grafo de um nó — mesmo padrão do avaliador) decide
   a próxima fala, a partir do prompt de sistema (`app/prompts/interviewer_system.md`,
   estático) + contexto da vaga (`vagaTitulo`/`vagaDescricao`/`estiloEntrevistador`,
   montado em runtime, mesmo espírito do `_build_user_content` do avaliador) + o
   histórico de turnos da conversa atual (em memória, só dura a conexão).
4. TTS: Amazon Polly Standard (voz `Camila`, pt-BR) → áudio (`audio/mpeg`).
5. Modelo: `gpt-5-nano` (mesmo do avaliador, mesma decisão de custo).

## Critérios de aceite

- [x] `verify_voice_token`: token válido → retorna `tentativaId` (UUID). Token com
      assinatura errada, expirado, malformado (não 4 partes), ou `tentativaId`/`exp`
      não parseáveis → retorna `None`. Mesmo algoritmo do `VoiceToken.kt`, testado com
      um token gerado por uma reimplementação do `mint` no próprio teste (prova
      compatibilidade cross-language).
- [x] `WebSocket /interview` sem token, com token inválido ou expirado → fecha com
      código `4401` antes de aceitar, nunca instancia STT/LLM/TTS.
- [x] Agente entrevistador testado com LLM mockado (mesmo padrão `FakeLLM` do
      avaliador): (a) turno de abertura (sem histórico) gera saudação + primeira
      pergunta a partir da vaga; (b) turno seguinte recebe o histórico da conversa +
      novo texto do usuário e gera a próxima fala; (c) `estiloEntrevistador` nulo cai
      pro default `"Tranquilo"`; (d) prompt de sistema (arquivo) nunca é reescrito em
      runtime, só o contexto é concatenado.
- [x] Teste de integração do WebSocket (STT/TTS/LLM totalmente mockados) cobrindo o
      fluxo completo: conectar com token válido → enviar `start` → receber `pergunta`
      de abertura → enviar `audio` → receber `pergunta` de acompanhamento → enviar
      `end` → receber `encerrado` → conexão fecha.
- [x] Falha do STT ou do LLM num turno → cliente recebe `{"tipo": "erro", ...}`, a
      conexão NÃO cai (fica pronta pro próximo turno).
- [x] `pytest` 100% verde, sem nenhuma chamada de rede real (STT/TTS/LLM mockados nos
      testes automatizados).

## Fora de escopo

- Frontend real (Etapa 3 do plano): `getUserMedia`, gravação de áudio no browser,
  consumo do WebSocket a partir do Next.js. Aqui o cliente do WebSocket é só o teste
  automatizado.
- O agente decidir sozinho quando a entrevista termina — quem encerra é sempre o
  front, mandando `end`.
- Deploy/validação com credenciais reais de AWS Polly — feito manualmente depois que
  o IAM da AWS existir (fica registrado como pendência separada, não bloqueia esta
  fase); os testes automatizados não dependem disso.
- Persistir qualquer coisa em banco — o Python continua sem acesso a banco nenhum.
