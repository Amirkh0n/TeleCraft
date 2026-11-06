from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from core.database import init_models
from webhook.handler import router as webhook_router
from core.logger import get_logger, logger
from core.rate_limit import rate_limit_middleware
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from prometheus_client import REGISTRY

app = FastAPI(
    title="TeleCraft Constructor API",
    description="Telegram Bot Constructor Platform",
    version="2.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request counter
request_counter = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status_code']
)

# Request duration histogram
request_duration = Histogram(
    'http_request_duration_seconds',
    'HTTP request duration in seconds',
    ['method', 'endpoint']
)

# Register rate limiting middleware
app.middleware("http")(rate_limit_middleware)

@app.on_event("startup")
async def on_startup():
    await init_models()
    logger.info("TeleCraft Constructor API started")

@app.on_event("shutdown")
async def on_shutdown():
    logger.info("TeleCraft Constructor API shutting down")

@app.get("/")
async def root():
    request_counter.labels(method="GET", endpoint="/", status_code=200).inc()
    return {
        "status": "running",
        "version": "2.0.0",
        "message": "TeleCraft Constructor API is running"
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.get("/metrics")
async def metrics():
    request_counter.labels(method="GET", endpoint="/metrics", status_code=200).inc()
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)

app.include_router(webhook_router)

from typing import Response
from prometheus_client import CONTENT_TYPE_LATEST
