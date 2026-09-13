import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from services.api_gateway.routers import alerts, auth, monitors
from services.common.rabbitmq import close_rabbitmq
from services.common.redis_client import close_redis
from services.common.ssrf import SSRFValidationError


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    yield
    await close_redis()
    await close_rabbitmq()


app = FastAPI(
    title="Uptime Guardian API Gateway",
    description="Distributed Uptime Monitoring System API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(SSRFValidationError)
async def ssrf_exception_handler(request: Request, exc: SSRFValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": str(exc)},
    )


@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "ok", "service": "api-gateway"}


@app.get("/", include_in_schema=False)
async def serve_dashboard():
    dashboard_path = os.path.join(
        os.path.dirname(__file__), "..", "dashboard", "index.html"
    )
    if os.path.exists(dashboard_path):
        return FileResponse(dashboard_path)
    return {"message": "Uptime Guardian API Gateway"}


app.include_router(auth.router, prefix="/api/v1")
app.include_router(monitors.router, prefix="/api/v1")
app.include_router(alerts.router, prefix="/api/v1")
