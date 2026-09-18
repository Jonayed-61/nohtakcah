from fastapi import APIRouter, HTTPException, status

from app.guardrails.directive_validator import DirectiveValidationError
from app.optimizer.solver import OptimizationError
from app.schemas.request import OptimizeEnergyRequest
from app.schemas.response import HealthResponse, OptimizeEnergyResponse
from app.services.optimization_service import OptimizationService
from app.validators.schedule_validator import ScheduleValidationError

router = APIRouter()
optimization_service = OptimizationService()


@router.get("/health", response_model=HealthResponse, status_code=status.HTTP_200_OK)
async def health_check():
    return HealthResponse(status="ok")


@router.post(
    "/optimize-energy",
    response_model=OptimizeEnergyResponse,
    status_code=status.HTTP_200_OK,
)
async def optimize_energy(request: OptimizeEnergyRequest):
    try:
        return await optimization_service.run_pipeline(request)
    except (DirectiveValidationError, ScheduleValidationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Validation failed: {exc}",
        ) from exc
    except OptimizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Optimization infeasible: {exc}",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to process the optimization request.",
        ) from exc
