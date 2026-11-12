import asyncio
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, Response, JSONResponse
from sqlalchemy import select, func

from core.database import AsyncSessionLocal, db_config, init_models
from webhook.handler import router as webhook_router
from webapp.api import router as webapp_router
from webapp.api_audience import router as webapp_audience_router
from core.logger import logger
from core.rate_limit import rate_limit_middleware
from core.config import settings
from core.webhook_manager import refresh_webhooks
from engine.booking_reminders import loop as reminders_loop
from engine.broadcast import resume_pending
from engine.quiz import resume_pending as resume_quizzes
from engine.telegram_client import close_all_clients
from models.bots import Bot
from models.users import User
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST, REGISTRY
from telegram import MenuButtonWebApp, Update, WebAppInfo
from webapp import editor_url
from constructor.bot import build_constructor_application

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
constructor_application = None
reminder_task = None


async def _resume_broadcasts():
    try:
        resumed = await resume_pending()
        if resumed:
            logger.info("Resumed %s interrupted broadcast(s)", resumed)
    except Exception:
        logger.exception("Could not resume broadcasts")


async def _resume_quiz_timers():
    try:
        count = await resume_quizzes()
        if count:
            logger.info("Re-armed %s quiz question timer(s)", count)
    except Exception:
        logger.exception("Could not resume quiz timers")


@app.on_event("startup")
async def on_startup():
    if db_config.is_sqlite and os.environ.get("RENDER"):
        logger.warning(
            "DATABASE_URL points to SQLite on Render: all data is lost on every deploy. "
            "Use an external PostgreSQL database."
        )
    await init_models()
    global constructor_application
    constructor_application = build_constructor_application(settings.TELEGRAM_TOKEN)
    await constructor_application.initialize()
    await constructor_application.start()
    url = editor_url()
    if url:
        try:  # the blue button next to the message field opens the editor
            await constructor_application.bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(text="Muharrir", web_app=WebAppInfo(url=url))
            )
        except Exception:
            logger.warning("Could not set the editor menu button", exc_info=True)
    if settings.WEBHOOK_REFRESH_ON_START:
        # Background task: must not delay startup or crash it if Telegram is slow.
        asyncio.create_task(refresh_webhooks())
    asyncio.create_task(_resume_broadcasts())
    asyncio.create_task(_resume_quiz_timers())
    global reminder_task
    reminder_task = asyncio.create_task(reminders_loop())
    logger.info("TeleCraft Constructor API started")


@app.on_event("shutdown")
async def on_shutdown():
    if reminder_task:
        reminder_task.cancel()
    if constructor_application:
        await constructor_application.stop()
        await constructor_application.shutdown()
    await close_all_clients()
    logger.info("TeleCraft Constructor API shutting down")


async def collect_bot_stats() -> dict:
    """Collect bot statistics for the home page"""
    async with AsyncSessionLocal() as session:
        total_bots = (await session.execute(
            select(func.count(Bot.id))
        )).scalar() or 0

        active_bots = (await session.execute(
            select(func.count(Bot.id)).where(Bot.is_active == True)
        )).scalar() or 0

        webhooks_set = (await session.execute(
            select(func.count(Bot.id)).where(Bot.webhook_set == True)
        )).scalar() or 0

        total_users = (await session.execute(
            select(func.count(User.id))
        )).scalar() or 0

        recent_bots = (await session.execute(
            select(Bot).where(Bot.webhook_set == True).order_by(Bot.id.desc()).limit(10)
        )).scalars().all()

    return {
        "total_bots": total_bots,
        "active_bots": active_bots,
        "webhooks_set": webhooks_set,
        "total_users": total_users,
        "recent_bots": recent_bots,
    }


def render_home_page(stats: dict) -> str:
    """Render beautiful home page HTML"""
    base_url = settings.PUBLIC_BASE_URL.rstrip("/")

    if stats["recent_bots"]:
        bot_rows = ""
        for b in stats["recent_bots"]:
            status_badge = (
                '<span class="badge badge-ok">Hook ✓</span>'
                if b.webhook_set
                else '<span class="badge badge-warn">Hook ✗</span>'
            )
            bot_rows += f"""
            <tr>
                <td>🤖 {b.name}</td>
                <td>{status_badge}</td>
                <td>{'🟢 Ishlayapti' if b.is_active else '🔴 O‘chirilgan'}</td>
            </tr>"""
        bots_table = f"""
        <table>
            <thead><tr><th>Bot</th><th>Webhook</th><th>Holat</th></tr></thead>
            <tbody>{bot_rows}</tbody>
        </table>"""
    else:
        bots_table = '<p class="empty">📭 Hozircha webhook ulangan botlar yo‘q. Constructor bot orqali bot qo‘shing.</p>'

    return f"""<!DOCTYPE html>
<html lang="uz">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TeleCraft — Bot Constructor</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Segoe UI', Tahoma, sans-serif;
            min-height: 100vh;
            background: linear-gradient(135deg, #0f2027 0%, #203a43 50%, #2c5364 100%);
            color: #fff;
            display: flex; align-items: center; justify-content: center;
            padding: 24px;
        }}
        .card {{
            background: rgba(255,255,255,0.07);
            border: 1px solid rgba(255,255,255,0.12);
            backdrop-filter: blur(12px);
            border-radius: 18px;
            padding: 40px;
            max-width: 640px; width: 100%;
            box-shadow: 0 20px 60px rgba(0,0,0,0.4);
        }}
        .pulse {{
            width: 12px; height: 12px; border-radius: 50%;
            background: #2ecc71;
            display: inline-block; margin-right: 10px;
            box-shadow: 0 0 0 rgba(46, 204, 113, 0.7);
            animation: pulse 2s infinite;
        }}
        @keyframes pulse {{
            0%  {{ box-shadow: 0 0 0 0 rgba(46, 204, 113, 0.7); }}
            70% {{ box-shadow: 0 0 0 10px rgba(46, 204, 113, 0); }}
            100%{{ box-shadow: 0 0 0 0 rgba(46, 204, 113, 0); }}
        }}
        h1 {{ font-size: 2.2rem; margin-bottom: 6px; }}
        .version {{ color: #9fd3e0; font-size: 0.95rem; margin-bottom: 28px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 14px; margin-bottom: 28px; }}
        .stat {{
            background: rgba(255,255,255,0.08);
            border-radius: 12px; padding: 18px;
            text-align: center;
        }}
        .stat .num {{ font-size: 1.8rem; font-weight: 700; color: #7fd8ff; }}
        .stat .lbl {{ font-size: 0.82rem; color: #cfe8f3; margin-top: 4px; }}
        table {{ width: 100%; border-collapse: collapse; margin-bottom: 24px; }}
        th, td {{ padding: 10px 12px; text-align: left; font-size: 0.92rem; border-bottom: 1px solid rgba(255,255,255,0.08); }}
        th {{ color: #9fd3e0; font-weight: 600; text-transform: uppercase; font-size: 0.75rem; letter-spacing: 1px; }}
        .badge {{ padding: 4px 10px; border-radius: 10px; font-size: 0.78rem; font-weight: 600; }}
        .badge-ok {{ background: rgba(46,204,113,0.18); color: #2ecc71; }}
        .badge-warn {{ background: rgba(241,196,15,0.18); color: #f1c40f; }}
        .empty {{ color: #b9d7e4; text-align: center; padding: 20px 0; }}
        .footer {{ margin-top: 20px; font-size: 0.8rem; color: #8fb6c6; border-top: 1px solid rgba(255,255,255,0.08); padding-top: 16px; line-height: 1.7; }}
        code {{ background: rgba(255,255,255,0.1); padding: 2px 7px; border-radius: 6px; font-size: 0.8rem; }}
    </style>
</head>
<body>
    <div class="card">
        <h1><span class="pulse"></span>TeleCraft</h1>
        <div class="version">Telegram Bot Constructor — API v2.0.0 / Server ishlayapti</div>

        <div class="grid">
            <div class="stat"><div class="num">{stats['total_bots']}</div><div class="lbl">Jami botlar</div></div>
            <div class="stat"><div class="num">{stats['active_bots']}</div><div class="lbl">Aktiv</div></div>
            <div class="stat"><div class="num">{stats['webhooks_set']}</div><div class="lbl">Webhook ulangan</div></div>
            <div class="stat"><div class="num">{stats['total_users']}</div><div class="lbl">Foydalanuvchilar</div></div>
        </div>

        {bots_table}

        <div class="footer">
            📊 Metrics: <code>GET {base_url}/metrics</code><br>
            ❤️ Health: <code>GET {base_url}/health</code><br>
            🔔 Main webhook: <code>POST {base_url}/webhook</code><br>
            🤖 Child webhook: <code>POST {base_url}/webhooks/&lt;bot_token&gt;</code>
        </div>
    </div>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def home():
    """Home page - chiroyli UI, bot holatini ko'rsatadi"""
    try:
        stats = await collect_bot_stats()
        html = render_home_page(stats)
        request_counter.labels(method="GET", endpoint="/", status_code=200).inc()
        return HTMLResponse(content=html, status_code=200)
    except Exception as e:
        logger.error(f"Home page error: {e}", exc_info=True)
        request_counter.labels(method="GET", endpoint="/", status_code=500).inc()
        return HTMLResponse(
            content="<h1>⚠️ TeleCraft</h1><p>Server ishlayapti, lekin statistika olinmadi.</p>",
            status_code=200
        )


@app.head("/")
async def home_head():
    """HEAD request - kontentsiz, faqat status"""
    return Response(status_code=200, headers={"X-TeleCraft-Status": "running"})


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


@app.get("/metrics")
async def metrics():
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


@app.post("/webhook")
async def constructor_webhook(request: Request):
    """Constructor bot uchun webhook endpoint."""
    payload = await request.json()
    logger.info("Constructor bot webhook received: update_id=%s", payload.get("update_id"))
    try:
        update = Update.de_json(payload, constructor_application.bot)
        await constructor_application.process_update(update)
        return {"ok": True}
    except Exception as e:
        logger.error("Constructor webhook error: %s", e, exc_info=True)
        return JSONResponse({"ok": False, "error": "Internal server error"}, status_code=500)


app.include_router(webhook_router)
app.include_router(webapp_router)
app.include_router(webapp_audience_router)
app.mount("/app", StaticFiles(directory=os.path.join(os.path.dirname(os.path.dirname(__file__)), "webapp", "static"), html=True), name="miniapp")
