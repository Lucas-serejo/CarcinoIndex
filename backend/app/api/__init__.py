from fastapi import APIRouter
from app.schemas import HealthCheckResponse

router = APIRouter()

@router.get("/health", response_model=HealthCheckResponse, summary="Verificação de integridade da API")
def health_check():
    """
    Endpoint minimalista para checagem de disponibilidade do serviço backend.
    """
    return HealthCheckResponse(
        status="ok",
        message="CarcinoIndex API operacional para suporte à pesquisa experimental."
    )
