# Fase 0 — Bootstrap: esqueleto do serviço + CI/CD

> Ver `specs/plano-arquitetura.md` pro desenho completo. Esta fase entrega só o
> esqueleto rodando (health check) com o mesmo pipeline de CI/CD dos outros dois
> repos — nenhum agente, nenhuma lógica de IA ainda.

## Objetivo

Ter o serviço FastAPI rodando localmente e em HML (mesma EC2, container novo, mesma
rede Docker `ensaia-hml-net`), com CI/CD completo (`feature/*` → `develop` → `main`),
antes de escrever qualquer lógica de agente.

## Critérios de aceite

- [ ] `GET /health` responde `200` com `{"status": "ok", "env": "<ENV>", "version": "<VERSION>"}`
      — mesmo formato do backend Kotlin (`env`/`version` vêm de variável de ambiente,
      nunca hardcoded).
- [ ] `pytest` roda localmente e no CI, cobrindo pelo menos o health check.
- [ ] `Dockerfile` builda uma imagem que roda o serviço via `uvicorn`.
- [ ] `.github/workflows/build-test.yml` (reusável): checkout, setup Python 3.13,
      instala dependências, roda `pytest`, sobe artefato de resultado em falha — mesmo
      padrão de log detalhado do back.
- [ ] `.github/workflows/feature-to-develop.yml` e `develop-deploy.yml`: mesmo fluxo
      do back (versionamento semântico por tag, skip de rebuild se a imagem já existe,
      deploy via SSH), adaptado pra este serviço — container `ensaia-voz`, porta
      `8081`, mesma rede `ensaia-hml-net`, `--memory=256m --cpus=0.5`, env-file
      `/home/ubuntu/ensaia/.env-voz.hml`.
- [ ] Deploy real em HML validado: `curl https://voz-hml.ensaia.ia.br/health` responde
      200 (depende de configurar o bloco Nginx + registro DNS na EC2 — passo manual
      guiado, como sempre).

## Fora de escopo desta fase

- Qualquer agente, prompt, STT/TTS, WebSocket — fases seguintes.
- Autenticação (`voice-token`, `VEREDITO_SERVICE_TOKEN`) — fase seguinte, junto com os
  endpoints que precisam dela.
