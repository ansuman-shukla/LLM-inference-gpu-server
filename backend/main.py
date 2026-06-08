"""Application entrypoint."""

from fastapi import FastAPI

from backend.api.routes.health import router as health_router

app = FastAPI(title="GPU Inference Backend")
app.include_router(health_router)
