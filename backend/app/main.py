from fastapi import FastAPI
from app.api import router as api_router

app = FastAPI(
    title="CarcinoIndex API",
    description="API de suporte à validação experimental da pipeline de IA para avaliação da Carcinomatose Peritoneal.",
    version="0.1.0",
)

# Inclui as rotas da API (atualmente contendo apenas /health)
app.include_router(api_router)
