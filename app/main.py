from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.config import settings

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    docs_url="/docs",
    redoc_url=None,
)

app.include_router(router)

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def dashboard():
    return FileResponse(STATIC_DIR / "index.html")

STRUCTURAL_ERRORS = {
    "json_invalid", "missing", "model_type", "dict_type", "list_type",
    "string_type", "int_type", "float_type", "bool_type", "int_parsing",
    "float_parsing", "extra_forbidden", "too_short", "too_long",
}


@app.exception_handler(RequestValidationError)
async def request_validation_handler(request: Request, exc: RequestValidationError):
    structural = any(error["type"] in STRUCTURAL_ERRORS for error in exc.errors())
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST if structural else status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": (
                "Malformed or structurally invalid request."
                if structural else "Semantically invalid request."
            )
        },
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Unable to process the optimization request."},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=True)
