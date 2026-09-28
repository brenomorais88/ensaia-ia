"""Env vars fake pra teste — setadas antes de qualquer import de `app.main` (que carrega
`Settings` no import do módulo). Nunca chamam a OpenAI de verdade nos testes."""

import os

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key-nao-usar-fora-de-teste")
os.environ.setdefault("VEREDITO_SERVICE_TOKEN", "test-veredito-service-token-nao-usar-fora-de-teste")
os.environ.setdefault("VOICE_TOKEN_SECRET", "test-voice-token-secret-nao-usar-fora-de-teste")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test-aws-access-key-nao-usar-fora-de-teste")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test-aws-secret-key-nao-usar-fora-de-teste")
os.environ.setdefault("ENV", "test")
