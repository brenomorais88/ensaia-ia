# Ensaia IA — serviço de voz e avaliação

Serviço Python separado do backend (`ensa-ia-back`, Kotlin) e do front
(`ensa-ia-front`, Next.js). Conduz a entrevista de voz ao vivo (STT → LLM → TTS,
turno a turno) e gera o veredito (nota, pontos fortes/fracos, feedback) — dois agentes
orquestrados por LangGraph. Ver `specs/plano-arquitetura.md` pro desenho completo e o
motivo de cada decisão (por que Python, por que cascata em vez de voz-a-voz unificada,
como a autenticação entre os três serviços funciona).

## Fluxo de trabalho (SDD)

Mesma disciplina dos outros dois repos: nunca implementar sem antes ter os critérios de
aceite escritos e confirmados.
1. Escrever/confirmar critérios de aceite da fase (arquivo em `specs/fase-N-criterios.md`)
2. Implementar contra esses critérios
3. Escrever testes (`pytest`) que provam os critérios
4. Marcar cada item concluído em `specs/tarefas.md` conforme progride

## Convenções

- Segredos sempre em variável de ambiente, nunca hardcoded (`.env`, nunca commitado —
  ver `.env.example`).
- Prompts vivem em arquivos próprios (`app/prompts/*.md`), nunca como string solta no
  meio do código — são conteúdo versionado, revisável por diff.
- Commits só em branches `feature/*`, PR manual pra `develop`, depois pra `main` —
  mesmo fluxo GitFlow dos outros dois repos.
