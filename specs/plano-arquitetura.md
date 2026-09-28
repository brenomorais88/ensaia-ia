# Motor de entrevista por voz — serviço Python separado + integração

## Contexto

`/entrevista` e `/relatorio` são 100% mockados hoje — timer falso, transcrição fixa,
nota fabricada por fórmula (`+0.6` sobre a última, sempre). O plano original era usar a
Realtime API da OpenAI (voz-a-voz unificada, testada num spike descartável,
`ensa-ia-voz-spikeV2`), mas o custo por sessão (~US$0,71/15min, medido com dado real do
spike) motivou reconsiderar. Depois de comparar arquiteturas e custos reais (ver decisões
abaixo), decidimos por uma **cascata turno-a-turno** (STT → LLM → TTS) rodando num
**serviço Python novo e separado**, com dois agentes orquestrados por **LangGraph**
(entrevistador + avaliador) e observabilidade via **LangSmith**.

O objetivo final: alguém cria uma Tentativa, faz a entrevista de voz de verdade (turno a
turno, apertar-pra-falar), e ao final recebe um veredito real gerado por IA — substituindo
inteiramente o fluxo mockado, sem inventar dado nenhum.

## Decisões já fechadas nesta conversa (não reabrir)

- **Pipeline híbrido**: Whisper (STT, OpenAI) + LLM de texto (`gpt-4o-mini` ou
  `gpt-5-nano`, OpenAI) + Amazon Polly Standard (TTS) — mais barato que Realtime e que
  TTS da OpenAI, medido com preços reais (~US$0,076/sessão de 15min vs ~US$0,71 da
  Realtime).
- **Turno a turno**, não voz fluida com interrupção — usuário aperta pra falar, solta
  quando termina. Sem VAD automático, sem lidar com sobreposição de fala.
- **LangGraph** (grátis, MIT) pra orquestrar os agentes; **LangSmith** (tier grátis,
  5k traces/mês) pra observabilidade.
- **Dois agentes**: entrevistador (conduz a conversa ao vivo) e avaliador (gera o
  veredito — migra a lógica de `OpenAiVereditoLlmClient.kt`, ver Etapa 2).
- **Front fala direto com o serviço Python** pra tudo que é ao vivo (áudio) — nunca
  com a OpenAI diretamente (chave nunca vai pro browser), e sem o hop desnecessário
  pelo Kotlin nessa parte.
- **Mesma EC2 de HML**, container novo, com `--memory`/`--cpus` explícitos pra não
  disputar recurso com Kotlin/Postgres. Instância própria fica pra quando existir PROD.
- **Repositório novo, Python** (`ensa-ia-voz` — nome a confirmar), FastAPI.

## Achado-chave da investigação: como conectar os 3 serviços sem expor segredo nenhum

O front hoje trata o access token como **opaco** — nunca decodifica JWT, só reenvia
via cookie httpOnly através do proxy (`/api/backend/[...path]`). Isso significa que o
front **não pode simplesmente abrir um WebSocket direto pro Python** com o token de
sessão normal (ele é httpOnly, invisível a qualquer JS, de propósito).

A solução, que já reaproveita um padrão que os specs de vocês já cogitavam pro "token
efêmero" da Realtime API — só que emitido pelo próprio Kotlin em vez da OpenAI:

1. Front chama um **endpoint novo no Kotlin**, autenticado normalmente (mesmo
   `ACCESS_AUTH` de sempre): `POST /tentativas/:id/voice-token`. Kotlin verifica
   ownership da Tentativa (mesmo padrão de `TentativaRoutes.kt`), confere que o status
   é `criada`, gera um **token efêmero de curta duração** (HMAC simples,
   `tentativaId + userId + exp`, sem precisar do `JwtService` completo) assinado com um
   segredo compartilhado só entre Kotlin e Python, marca a Tentativa como
   `em_andamento` (o enum já reserva esse status — `tentativa_status`, `V1__initial_schema.sql` —
   inalcançável hoje, exatamente reservado pra isso), devolve `{ token, wsUrl }`.
2. Front abre o WebSocket **direto no Python**, apresentando esse token no handshake.
   Python valida a assinatura HMAC + expiração + `tentativaId` — sem precisar checar
   nada com o Kotlin a cada mensagem.
3. Ao final da entrevista, o **front** (não o Python) chama
   `POST /tentativas/:id/finish` — **rota que já existe, contrato que não muda em
   nada** (`FinishTentativaRequest{transcript, durationMs, usageEvents}`). O
   transcript vem do que o Python foi devolvendo turno a turno pelo WebSocket.

Isso mantém o modelo de autenticação de usuário inteiramente no Kotlin (nada novo pro
front aprender) e isola a comunicação nova (Kotlin↔Python, Python↔browser) atrás de um
segredo compartilhado simples, no mesmo espírito do padrão já existente
`INTERNAL_JOBS_TOKEN` (`InternalRoutes.kt`) — só que na direção oposta (Kotlin chamando
pra fora, não sendo chamado).

## Etapa 1 — Serviço Python novo (`ensa-ia-voz`)

Estrutura (mesmo padrão SDD dos outros dois repos — `specs/*-criterios.md` antes de
implementar):

```
app/
├── agents/
│   ├── interviewer.py       # LangGraph: conduz a entrevista ao vivo
│   ├── evaluator.py         # LangGraph: gera veredito (porta o prompt de OpenAiVereditoLlmClient.kt)
│   └── graph.py             # define os nós/grafo
├── prompts/
│   ├── interviewer_system.md
│   └── evaluator_system.md  # começa com o SYSTEM_PROMPT exato já em produção (ver abaixo)
├── pipeline/
│   ├── stt.py                # Whisper
│   ├── tts.py                # Polly Standard
├── auth/
│   └── voice_token.py       # valida o HMAC emitido pelo Kotlin
├── main.py                  # FastAPI: WebSocket /interview, POST /veredito
└── config.py                 # env vars (OPENAI_API_KEY, AWS creds, VOICE_TOKEN_SECRET, VEREDITO_SERVICE_TOKEN)
```

- **Prompt do avaliador**: começa como cópia literal do `SYSTEM_PROMPT` de
  `OpenAiVereditoLlmClient.kt` (linhas 25-36) — mesmo texto, mesmo contrato de saída
  (`nota_geral`, `pontos_fortes`, `pontos_fracos`, `feedback_texto`), pra não regredir
  qualidade no dia 1. Refinar depois é iteração, não parte deste plano.
- **Modelo**: `gpt-5-nano`, mesmo de hoje (já validado/medido em produção).
- **Endpoint `POST /veredito`**: recebe `{transcript, historicoAnterior}` (mesmo shape
  de `VereditoGenerationInput` em `VereditoLlmClient.kt`), devolve
  `{notaGeral, pontosFortes, pontosFracos, feedbackTexto, inputTokensFresh,
  inputTokensCached, outputTokens}` — o **mesmo shape de `VereditoLlmResult`** que já
  existe. Autenticado por header de segredo compartilhado (`VEREDITO_SERVICE_TOKEN`),
  comparação em tempo constante — mesmo padrão de `InternalRoutes.kt`.
- **WebSocket `/interview`**: recebe o token efêmero no handshake, conduz o turno a
  turno (recebe áudio → Whisper → agente entrevistador (LangGraph) decide a próxima
  fala → Polly → devolve áudio), acumulando o transcript.
- **CI/CD**: mesmo padrão do back (`build-test.yml` reusável adaptado pra Python —
  `pytest` no lugar de `./gradlew test`; `develop-deploy.yml` adaptado — mesmo
  script de deploy SSH, container novo `ensaia-voz` (nome a confirmar), **mesma rede
  Docker `ensaia-hml-net`** (pra resolver `ensaia-api`/`ensaia-hml-db` por nome se
  precisar), `--memory=256m --cpus=0.5` (ajustar depois de medir uso real), porta
  nova (ex: `8081`), novo subdomínio `voz-hml.ensaia.ia.br` com bloco Nginx **com
  suporte a WebSocket** (`proxy_http_version 1.1`, headers `Upgrade`/`Connection` —
  configuração que o bloco atual do Kotlin não tem, por não precisar).

## Etapa 2 — Backend Kotlin (mudança mínima, cirúrgica)

Graças à interface já existente `VereditoLlmClient` (`VereditoLlmClient.kt`), a
migração do avaliador **não exige tocar em `VereditoService.kt`** — toda a lógica de
idempotência, transação, ownership e persistência que já funciona e está testada
continua exatamente igual. Só troca **quem implementa a interface**:

- Novo: `PythonVereditoLlmClient` (implementa `VereditoLlmClient`) — chama
  `POST {VOICE_SERVICE_URL}/veredito` no serviço Python em vez de chamar a OpenAI
  direto. Mesmo formato de entrada/saída que `OpenAiVereditoLlmClient` já produz, então
  `VereditoService` não percebe diferença.
- `OpenAiVereditoLlmClient.kt` pode ser deletado depois que o novo cliente estiver
  validado (não precisa deletar no mesmo PR — dá pra rodar os dois em paralelo por um
  tempo se quiser comparar qualidade).
- **Novo endpoint**: `POST /tentativas/:id/voice-token` — ownership check (mesmo
  padrão de `requireAuthenticatedUserId` + verificação de dono em `TentativaRoutes.kt`),
  valida status `criada`, marca `em_andamento`, emite o token HMAC, devolve
  `{token, wsUrl}`.
- **Novas env vars** (seguindo o padrão exato de `Env.kt`/`AppEnv`): `VOICE_SERVICE_URL`,
  `VOICE_TOKEN_SECRET` (compartilhado com o Python), `VEREDITO_SERVICE_TOKEN`
  (compartilhado com o Python, direção oposta).
- **Nenhuma migration nova** — `tentativa_status` já tem `em_andamento` desde a V1.

## Etapa 3 — Frontend

1. **Corrigir gap de segurança encontrado na investigação**: `(session)/layout.tsx`
   hoje não tem NENHUM gate de sessão (diferente de `(app)/layout.tsx`, que tem
   `hasSessionCookie()` + `getMeServer()`). Antes de expor uma entrevista de verdade
   ali, adicionar o mesmo gate.
2. **`/entrevista/[tentativaId]`**: vira Client Component de verdade —
   `getUserMedia` (permissão de microfone), botão de apertar-pra-falar, chama
   `POST /tentativas/:id/voice-token` (via `backendServerFetch`, igual toda rota
   autenticada hoje), abre WebSocket direto pro Python com o token recebido, toca o
   áudio de resposta, acumula transcript. Ao encerrar, chama
   `POST /tentativas/:id/finish` (já existente, real, mesmo formato de sempre).
3. **`/relatorio/[tentativaId]`**: passa a buscar `GET /tentativas/:id/veredito`
   (rota real, já existe) em vez do mock. **Decisão de escopo**: a tela hoje mostra
   `competencias`, `momentos`, `destaquePositivo`, `proximoGanho` — nenhum desses
   campos existe em `VereditoResponse` real (só `notaGeral`, `pontosFortes`,
   `pontosFracos`, `feedbackTexto`). Pra v1, a tela mostra só o que é real; os campos
   mais ricos ficam como evolução futura do schema do agente avaliador (extensão
   pequena, não bloqueia esta entrega). `/competencias` (agregado entre Tentativas)
   continua fora de escopo, como já combinado antes.
4. Remove a dependência de `obterContextoTentativa`/mock nessas duas páginas.

## Fora de escopo deste plano

- PROD (aguardando Fase 9 do back).
- Fine-tuning do agente avaliador/entrevistador — iteração futura, pipeline já
  desenhado pra suportar sem mudança estrutural.
- `/competencias` e os campos ricos do veredito (momentos, próximo ganho).
- Self-hosted STT/TTS — só faz sentido em volume alto.
- Migrar pra Bedrock/Azure — sem vantagem de custo identificada.

## Verificação

- Testes Python (`pytest`) cobrindo o agente avaliador contra os prompts/transcripts já
  usados nos testes Kotlin existentes (`VereditoRouteTest`, `CostCalculatorTest`) —
  mesma entrada, conferir que a saída não regride.
- `./gradlew test` no back continua 100% verde (mudança é aditiva/substitutiva atrás
  da interface, não deveria quebrar nada existente).
- Fluxo ponta a ponta manual: criar Tentativa → pedir voice-token → conversa real via
  microfone → encerrar → conferir veredito real em `/relatorio`, comparando com o
  transcript de fato dito.
- Confirmar no `docker stats` da EC2 de HML que o container novo não empurra os outros
  dois pra swap/OOM sob uso normal.
