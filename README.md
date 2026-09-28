# ensaia-ia

Serviço de voz e avaliação do Ensa.ia — Python, separado do backend (Kotlin) e do
front (Next.js). Ver `specs/plano-arquitetura.md` pro desenho completo.

## Rodando localmente

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8081
```

Abra `http://localhost:8081/health`.

## Testes

```bash
pytest
```

## Docker

```bash
docker build -t ensaia-ia .
docker run -p 8081:8081 -e ENV=local ensaia-ia
```
