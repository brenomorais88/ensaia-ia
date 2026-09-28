from fastapi import FastAPI

from app.config import APP_VERSION, load_settings

app = FastAPI(title="Ensaia IA")
settings = load_settings()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "env": settings.env, "version": APP_VERSION}
