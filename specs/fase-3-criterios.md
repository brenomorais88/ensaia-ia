# Fase 3 — Avaliador multi-agente + KBs auto-retroalimentados + planejador de perguntas

> Ver plano formal (`/Users/brenomorais/.claude/plans/foamy-humming-pillow.md`, sessão
> de 2026-09-28) pro desenho completo e o porquê de cada decisão. Este documento fecha
> só a Fase A desse plano — o lado Python. Back (Fase B) e front (Fase C) dependem do
> contrato exato definido aqui.

## Objetivo

Substituir o avaliador single-node (`app/agents/evaluator.py`, fase-1) por um grafo
multi-agente que produz, além do que já existe hoje (`pontosFortes`, `pontosFracos`,
`feedbackTexto`), **6 notas de pilar** (competências agnósticas de vaga) e alimenta um
sistema de aprendizado contínuo: dois KBs (texto livre, reescritos a cada Tentativa —
um por Objetivo, um por usuário) e um histórico estruturado de perguntas já feitas,
usado por um agente planejador pra sugerir o que perguntar na próxima entrevista do
mesmo Objetivo.

## Decisões (não reabrir — já validadas com o usuário)

1. **6 pilares**: Escuta e resposta, Clareza, Exemplos concretos, Fechamento
   (originais do SPEC do front) + Estrutura da resposta, Concisão (novos). Cada um é
   um agente próprio, nota 0–10.
2. **`notaGeral` = média aritmética dos 6 pilares**, calculada em Python (nó puro,
   sem LLM) — não é mais um julgamento holístico separado.
3. **Grafo em duas camadas**:
   - Camada 1 (paralela): os 6 nós de pilar + 1 nó de texto/feedback, todos só
     dependendo do transcript + histórico — sem dependência entre si.
   - Camada 2 (sequencial, curta): agregação de `notaGeral` (paralelo ao resto da
     Camada 2) → `objetivo_kb` (precisa do `perguntas` extraído pelo nó de texto) →
     `planejador_perguntas` (precisa da lista de perguntas **já atualizada** pelo
     `objetivo_kb`) → em paralelo com esses dois, `usuario_kb` (só precisa do nó de
     texto + `kbUsuarioAnterior`, sem histórico de perguntas).
4. **Extração de perguntas sem custo extra**: o nó de texto/feedback (que já lê o
   transcript inteiro) devolve, no mesmo schema estruturado,
   `perguntas: [{pergunta, respostaResumo, qualidade}]` — uma entrada por pergunta
   feita nesta tentativa. Nenhum agente novo só pra isso.
5. **Histórico de perguntas só no `objetivo_kb`** (nunca no `usuario_kb`) — pergunta é
   sempre ligada à vaga/track, o KB de usuário fica restrito a
   comportamento/soft-skills (mesmo raciocínio de "agnóstico de vaga" das 6
   competências).
6. **KBs são sempre reescritos por completo**, nunca acrescentados — cada agente de
   KB recebe o anterior + o que aprendeu agora, devolve a versão nova inteira (evita
   crescimento sem limite).
7. **Modelo por nó, configurável** — todos os 9 nós começam em `gpt-5-nano`; a
   arquitetura não pode ter um `MODEL` fixo único compartilhado por todo o grafo
   (diferente do `evaluator.py` atual) — cada função de nó recebe seu próprio
   `ChatOpenAI`.
8. **LangSmith ativado de verdade** — `LANGSMITH_TRACING`/`LANGSMITH_API_KEY` saem do
   estado "comentado no `.env.example`" pra variáveis reais documentadas e
   referenciadas em `.env-ia.hml` (a chave em si é passo manual do usuário, fora do
   escopo do código).

## Contrato novo do `POST /veredito`

**Request** ganha 3 campos novos (todos opcionais/nuláveis — primeira Tentativa de um
Objetivo não tem nada ainda):
```json
{
  "transcript": ...,
  "historicoAnterior": [...],
  "kbObjetivoAnterior": "string ou null",
  "perguntasAnteriores": [{"pergunta": "...", "respostaResumo": "...", "qualidade": "...", "tentativaNumero": 1}] ou null,
  "kbUsuarioAnterior": "string ou null"
}
```

**Response** ganha os pilares + os campos de KB atualizados:
```json
{
  "notaGeral": 7.5,
  "pontosFortes": [...],
  "pontosFracos": [...],
  "feedbackTexto": "...",
  "notaEscutaResposta": 8.0,
  "notaClareza": 7.0,
  "notaExemplosConcretos": 6.5,
  "notaFechamento": 7.0,
  "notaEstruturaResposta": 8.0,
  "notaConcisao": 6.5,
  "kbObjetivoAtualizado": "...",
  "perguntasAtualizadas": [{"pergunta": "...", "respostaResumo": "...", "qualidade": "...", "tentativaNumero": 2}],
  "perguntasSugeridas": "...",
  "kbUsuarioAtualizado": "...",
  "inputTokensFresh": 0,
  "inputTokensCached": 0,
  "outputTokens": 0
}
```
`inputTokensFresh`/`inputTokensCached`/`outputTokens` continuam existindo, agora
somados de todos os 9 nós (não só um).

## Contrato novo da mensagem `start` do WebSocket `/interview`

Ganha 3 campos opcionais, repassados pro backend Kotlin buscar e o front incluir:
`kbObjetivo`, `perguntasSugeridas`, `kbUsuario` — todos `string | null`. O
`build_contexto_vaga` (ou equivalente) incorpora esses três no prompt de contexto do
entrevistador quando presentes.

## Critérios de aceite

- [x] Os 6 nós de pilar rodam em paralelo (mesmo `add_edge` a partir do entry point,
      sem depender uns dos outros) — testado verificando que todos os `FakeLLM`
      recebem o mesmo estado de entrada, não um encadeado no outro.
- [x] Nó de texto/feedback devolve `pontosFortes`/`pontosFracos`/`feedbackTexto`
      **e** `perguntas` (lista, uma por pergunta do transcript) no mesmo objeto
      estruturado — sem chamada de LLM adicional.
- [x] `notaGeral` é exatamente a média aritmética das 6 notas de pilar (testado com
      valores que não arredondam "bonito", pra pegar erro de arredondamento).
- [x] `objetivo_kb`: recebe `kbObjetivoAnterior=null` (primeira tentativa) → gera
      `kbObjetivoAtualizado` sem quebrar; recebe um anterior real → o prompt inclui
      tanto o anterior quanto o `perguntas` desta tentativa.
- [x] Lista de perguntas nunca duplica uma pergunta idêntica (mesmo texto exato) —
      testado mandando a mesma pergunta duas tentativas seguidas e conferindo que
      `perguntasAtualizadas` não cresce com duplicata.
- [x] `planejador_perguntas` só roda depois do `objetivo_kb` — testado com um
      `FakeLLM` do planejador que falha se receber uma lista de perguntas que não
      inclua a da tentativa atual (prova que recebeu a versão já atualizada, não a
      anterior).
- [x] `usuario_kb` roda com sucesso independente de `objetivo_kb`/`planejador` — não
      recebe nem depende da lista de perguntas.
- [x] `POST /veredito` com `kbObjetivoAnterior`/`perguntasAnteriores`/
      `kbUsuarioAnterior` ausentes (primeira tentativa de um Objetivo novo) funciona
      sem erro, devolve tudo com base vazia.
- [x] `POST /veredito` devolve o shape completo (todos os campos da seção "Contrato"
      acima) com o header de autenticação certo; 401 sem o header, como já era.
- [x] `WebSocket /interview`: mensagem `start` aceita `kbObjetivo`/
      `perguntasSugeridas`/`kbUsuario` opcionais; quando presentes, aparecem no
      contexto passado pro agente entrevistador (testado inspecionando as mensagens
      capturadas pelo `FakeLLM` do entrevistador).
- [x] `.env.example` documenta `LANGSMITH_TRACING`/`LANGSMITH_API_KEY`/
      `LANGSMITH_PROJECT` como variáveis reais (não comentadas) — a chave real fica
      pendência do usuário, fora do escopo deste PR.
- [x] `pytest` 100% verde, sem nenhuma chamada de rede real.

## Fora de escopo

- Ativar a chave real do LangSmith (`LANGSMITH_API_KEY`) — passo manual do usuário.
- Testar qual modelo (`gpt-5-nano` vs `gpt-5`/`gpt-4`) é o melhor custo×benefício por
  pilar — fica pra depois, com dado real do LangSmith em mãos.
- Qualquer coisa do lado do backend Kotlin (schema, rotas, troca de
  `VEREDITO_PROVIDER`) ou do front (páginas novas, de-mock do `/competencias`) — Fases
  B e C, documentos de critérios próprios nos respectivos repositórios.
