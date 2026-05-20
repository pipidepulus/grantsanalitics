import logging
import time
import uuid as _uuid

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import text

from app.config import get_settings
from app.database import SessionLocal
from app.logging_config import configure_logging, request_id_ctx
from app.api.routes import users, projects, documents, calls, chat

configure_logging()
logger = logging.getLogger(__name__)

settings = get_settings()

# ── Rate limiter ──────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title=settings.APP_NAME,
    description="Plataforma AI para generación de proyectos de alto impacto para convocatorias de financiamiento",
    version="1.0.0",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── Prometheus metrics ────────────────────────────────────────────────────────
try:
    from prometheus_fastapi_instrumentator import Instrumentator
    Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
except ImportError:
    logger.warning("prometheus_fastapi_instrumentator not installed; /metrics disabled")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next) -> Response:
    """Attach OWASP-recommended security headers to every response."""
    response: Response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("X-XSS-Protection", "1; mode=block")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy",
        "geolocation=(), microphone=(), camera=()",
    )
    return response


@app.middleware("http")
async def request_id_and_logging(request: Request, call_next) -> Response:
    """Attach a unique request ID to every request and emit structured access logs."""
    req_id = request.headers.get("X-Request-Id") or str(_uuid.uuid4())
    token = request_id_ctx.set(req_id)
    start = time.monotonic()
    try:
        response: Response = await call_next(request)
    finally:
        elapsed_ms = round((time.monotonic() - start) * 1000, 1)
        logger.info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": getattr(response, "status_code", 0),
                "duration_ms": elapsed_ms,
            },
        )
        request_id_ctx.reset(token)
    response.headers["X-Request-Id"] = req_id
    return response


app.include_router(users.router, prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(documents.router, prefix="/api")
app.include_router(calls.router, prefix="/api")
app.include_router(chat.router, prefix="/api")


@app.get("/api/health")
def health_check():
    """Deep health check: verifies DB connectivity and key configuration.

    Returns HTTP 200 when all checks pass, HTTP 503 when any critical
    dependency is unreachable.  Safe to use as a container/load-balancer
    liveness probe.
    """
    checks: dict[str, dict] = {}
    all_ok = True

    # --- Database ---
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        checks["database"] = {"status": "ok"}
    except Exception as exc:
        checks["database"] = {"status": "error", "detail": str(exc)}
        all_ok = False
        logger.error("health_check: database unreachable", exc_info=exc)

    # --- OpenAI key configured ---
    if settings.OPENAI_API_KEY:
        checks["openai"] = {"status": "ok"}
    else:
        checks["openai"] = {"status": "error", "detail": "OPENAI_API_KEY not configured"}
        all_ok = False
        logger.error("health_check: OPENAI_API_KEY is not set")

    # --- Vector stores configured ---
    vs_missing = [
        name
        for name, val in [
            ("OPENAI_VECTOR_STORE_ID", settings.OPENAI_VECTOR_STORE_ID),
            ("OPENAI_PROJECTS_VECTOR_STORE_ID", settings.OPENAI_PROJECTS_VECTOR_STORE_ID),
        ]
        if not val
    ]
    if vs_missing:
        checks["vector_stores"] = {
            "status": "error",
            "detail": f"Missing: {', '.join(vs_missing)}",
        }
        all_ok = False
        logger.error("health_check: missing vector store IDs: %s", vs_missing)
    else:
        checks["vector_stores"] = {"status": "ok"}

    status_code = 200 if all_ok else 503
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=status_code,
        content={
            "status": "healthy" if all_ok else "degraded",
            "app": settings.APP_NAME,
            "checks": checks,
        },
    )
