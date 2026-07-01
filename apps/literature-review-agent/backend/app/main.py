from fastapi import FastAPI

from .config import settings
from .db import init_db

app = FastAPI(title=settings.app_name)


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
