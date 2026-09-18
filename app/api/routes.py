from fastapi import APIRouter, status

from app.schemas.request import OptimizeEnergyRequest
from app.schemas.response import HealthResponse, OptimizeEnergyResponse


router = APIRouter()


@router.get("/health", response_model=HealthResponse, status_code=status.HTTP_200_OK)
async def health_check():
    return HealthResponse(status="ok")


@router.post(
    "/optimize-energy",
    response_model=OptimizeEnergyResponse,
    status_code=status.HTTP_200_OK,
)
async def optimize_energy(request: OptimizeEnergyRequest):
    # Pipeline orchestration will be wired in Part 4.
    pass
