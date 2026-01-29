from fastapi import FastAPI
from core.database import init_models
from webhook.handler import router as webhook_router

app = FastAPI()


@app.on_event("startup")
async def on_startup():
    await init_models()


app.include_router(webhook_router)


@app.get("/")
async def root():
    return {"status": "Constructor API is running"}
