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

# ── Rate limiter ───────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title=settings.APP_NAME,
    description="Plataforma AI para generación de proyectos de alto impacto para convocatorias de financiamiento",
    version="1.0.0",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── Prometheus metrics (framework-level) ───────────────
try:
    from prometheus_fastapi_instrumentator import Instrumentator
    Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
except ImportError:
    logger.warning("prometheus_fastapi_instrumentator not installed; /metrics disabled")

# ───┈ Custom Prometheus metrics (Ollama, Vector Store, Agent) ┈────────
_observability_metrics: dict = {}
_has_metrics = False
try:
    from app.observability import init as init_observability
    _observability_metrics = init_observability()
    _has_metrics = "ollama_inference_duration" in _observability_metrics
except (ImportError, Exception) as exc:
    logger.warning("observability init failed", extra={"error": str(exc)})


# ─── Health: deep Ollama check ┈───────────────────────────
from app.health_ollama import check_deep_health as _check_ollama_deep


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

    # --- Ollama (light + deep) ---
    checks["ollama"] = {"status": "error", "detail": "not checked"}
    try:
        import httpx
        with httpx.Client(timeout=5) as client:
            r = client.get(f"{settings.OLLAMA_BASE_URL}/api/tags")
            r.raise_for_status()
            models = r.json().get("models", [])
            available = [m["name"] for m in models] if models else []
            checks["ollama"] = {
                "status": "ok" if available else "warning",
                "detail": "reachable",
                "models": available[:10],
            }
    except Exception as e:
        checks["ollama"]["status"] = "error"
        checks["ollama"]["detail"] = f"Ollama not reachable: {e}"
        all_ok = False

    # Deep Ollama check (model availability + functional tests)
    if _has_metrics:
        try:
            import httpx
            async def _do_deep_check():
                async with httpx.AsyncClient(timeout=35) as c:
                    result = {
                        "status": "error",
                        "detail": "not checked",
                        "models": [],
                        "model_availability": {},
                        "inference_test": False,
                        "embedding_test": False,
                    }
                    # connectivity
                    try:
                        resp = await c.get(f"{settings.OLLAMA_BASE_URL}/api/tags")
                        resp.raise_for_status()
                        tags = resp.json().get("models", [])
                        result["models"] = [m.get("name", "") for m in tags][:10]
                        result["detail"] = "reachable"
                    except Exception as exc:
                        result["detail"] = f"Ollama unreachable: {exc}"
                        return result

                    # model availability
                    for name in [settings.OLLAMA_MODEL, settings.OLLAMA_EMBEDDING_MODEL]:
                        found = any(name == m.get("name", "") or m.get("name", "").startswith(name) for m in tags)
                        result["model_availability"][name] = found
                        gauge = _observability_metrics.get("ollama_model_available")
                        if gauge and hasattr(gauge, "labels"):
                            gauge.labels(model=name).set(1 if found else 0)

                    # inference test
                    if result["model_availability"].get(settings.OLLAMA_MODEL):
                        try:
                            resp = await c.post(
                                f"{settings.OLLAMA_BASE_URL}/v1/chat/completions",
                                json={
                                    "model": settings.OLLAMA_MODEL,
                                    "messages": [{"role": "user", "content": "ok"}],
                                    "max_tokens": 1,
                                },
                            )
                            resp.raise_for_status()
                            result["inference_test"] = True
                        except Exception as exc:
                            result["detail"] = f"Inference test failed: {exc}"
                    # embedding test
                    if result["model_availability"].get(settings.OLLAMA_EMBEDDING_MODEL):
                        try:
                            resp = await c.post(
                                f"{settings.OLLAMA_BASE_URL}/api/embed",
                                json={"model": settings.OLLAMA_EMBEDDING_MODEL, "input": "ok"},
                            )
                            resp.raise_for_status()
                            result["embedding_test"] = True
                        except Exception as exc:
                            result["detail"] = f"Embedding test failed: {exc}"

                    all_models_ok = all(
                        result["model_availability"].get(m, False)
                        for m in [settings.OLLAMA_MODEL, settings.OLLAMA_EMBEDDING_MODEL]
                    )
                    result["status"] = "ok" if all_models_ok else "warning"
                    return result

            # Run deep check in a thread since this is a sync endpoint
            import asyncio
            deep = asyncio.new_event_loop().run_until_complete(_do_deep_check())
            checks["ollama_deep"] = deep
            if deep["status"] != "ok":
                all_ok = False
        except Exception as e:
            logger.warning("health_check: deep Ollama check failed", extra={"error": str(e)})

    # --- ChromaDB ---
    checks["chromadb"] = {"status": "ok"}
    try:
        import chromadb
        ch_client = chromadb.PersistentClient(settings.CHROMA_DB_PATH)
        ch_client.heartbeat()
        checks["chromadb"] = {"status": "ok"}
    except Exception as e:
        checks["chromadb"] = {"status": "error", "detail": str(e)}
        all_ok = False

    # --- pgvector ---
    checks["pgvector"] = {"status": "ok"}
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT * FROM pg_extension WHERE extname = 'vector'"))
        checks["pgvector"] = {"status": "ok"}
    except Exception as e:
        checks["pgvector"] = {"status": "error", "detail": str(e)}
        all_ok = False

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
