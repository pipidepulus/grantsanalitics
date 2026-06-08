"""
Prometheus custom metrics for Ollama migration.

Namespace: ``pipidepulus``  (avoids collisions with other services).

Exports
----
init   -- create all prometheus metrics and return a dict of handles.

Low-level helpers for services to instrument without importing internals.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


def init(namespace: str = "pipidepulus") -> dict:
    """Create (or re-use) all custom Prometheus metrics and return a dict of handles."""
    try:
        from prometheus_client import Counter, Gauge, Histogram
    except ImportError:  # pragma: no cover — tested at runtime
        logger.warning("prometheus_client not installed; observability init skipped")
        return {}

    ns = namespace
    m: dict[str, Any] = {}

    # ═══ Ollama ═══
    m["ollama_inference_duration"] = Histogram(
        name=f"{ns}_ollama_inference_duration_seconds",
        documentation="Duration of Ollama /v1/chat/completions",
        namespace=ns,
        labelnames=["model", "tool", "status"],
        buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0],
    )

    m["ollama_inference_attempts"] = Counter(
        name=f"{ns}_ollama_inference_attempts_total",
        documentation="Total Ollama /v1/chat/completions attempts",
        namespace=ns,
        labelnames=["model", "tool"],
    )

    m["ollama_inference_success"] = Counter(
        name=f"{ns}_ollama_inference_success_total",
        documentation="Successful Ollama inference responses",
        namespace=ns,
        labelnames=["model", "call_type"],
    )

    m["ollama_embedding_duration"] = Histogram(
        name=f"{ns}_ollama_embedding_duration_seconds",
        documentation="Duration of Ollama /api/embed",
        namespace=ns,
        labelnames=["model"],
        buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
    )

    m["ollama_embedding_attempts"] = Counter(
        name=f"{ns}_ollama_embedding_attempts_total",
        documentation="Total Ollama embedding attempts",
        namespace=ns,
    )

    m["ollama_embedding_error"] = Counter(
        name=f"{ns}_ollama_embedding_error_total",
        documentation="Failed Ollama embedding attempts",
        namespace=ns,
    )

    m["ollama_model_fallback"] = Counter(
        name=f"{ns}_ollama_model_fallback_total",
        documentation="Times Ollama model fallback was activated",
        namespace=ns,
        labelnames=["from_model", "to_model"],
    )

    m["ollama_request_duration"] = Histogram(
        name=f"{ns}_ollama_request_duration_seconds",
        documentation="Latency of Ollama HTTP requests",
        namespace=ns,
        labelnames=["endpoint"],
        buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
    )

    # ═══ Vector Store ═══
    m["vectorstore_query_duration"] = Histogram(
        name=f"{ns}_vectorstore_query_duration_seconds",
        documentation="Duration of ChromaDB/pgvector vector queries",
        namespace=ns,
        labelnames=["store"],
        buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
    )

    m["vectorstore_query"] = Counter(
        name=f"{ns}_vectorstore_query_total",
        documentation="Total vector queries by store",
        namespace=ns,
        labelnames=["store"],
    )

    m["vectorstore_upload_duration"] = Histogram(
        name=f"{ns}_vectorstore_upload_duration_seconds",
        documentation="Upload pipeline duration (chunk + embed + insert)",
        namespace=ns,
        labelnames=["store"],
        buckets=[0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0],
    )

    m["vectorstore_upload"] = Counter(
        name=f"{ns}_vectorstore_upload_total",
        documentation="Total documents indexed via upload",
        namespace=ns,
        labelnames=["store", "status"],
    )

    m["vectorstore_upload_error"] = Counter(
        name=f"{ns}_vectorstore_upload_error_total",
        documentation="Failed document uploads",
        namespace=ns,
        labelnames=["store"],
    )

    # ═══ Agent ═══
    m["agent_tool_calls"] = Counter(
        name=f"{ns}_agent_tool_calls_total",
        documentation="Tool calls by the AI agent",
        namespace=ns,
        labelnames=["tool"],
    )

    m["agent_tool_duration"] = Counter(
        name=f"{ns}_agent_tool_duration_seconds",
        documentation="Duration of tool execution calls",
        namespace=ns,
        labelnames=["tool"],
    )

    m["agent_streaming_duration"] = Histogram(
        name=f"{ns}_agent_streaming_duration_seconds",
        documentation="Total streaming request latency",
        namespace=ns,
        labelnames=["model"],
        buckets=[1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0],
    )

    # ═══ Model Health ═══
    m["ollama_model_available"] = Gauge(
        name=f"{ns}_ollama_model_available",
        documentation="Whether a local model is available (1) or not (0)",
        namespace=ns,
        labelnames=["model"],
    )

    return m


# ══════════════════════════════ Low-Level Helpers ═══════════════════════════


def track_inference(metrics: dict, model: str, call_type: str, success: bool = True) -> None:
    """Record Ollama inference counters (no latency)."""
    if not metrics or "ollama_inference_attempts" not in metrics:
        return
    if "ollama_inference_attempts" in metrics:
        metrics["ollama_inference_attempts"].labels(model=model, tool=call_type).inc(1)
    if success:
        if "ollama_inference_success" in metrics:
            metrics["ollama_inference_success"].labels(model=model, call_type=call_type).inc(1)


def track_inference_with_latency(metrics: dict, model: str, call_type: str, elapsed_s: float, success: bool = True) -> None:
    """Record Ollama inference with latency histogram + counters."""
    track_inference(metrics, model, call_type, success)
    if not metrics or "ollama_inference_duration" not in metrics:
        return
    status = "success" if success else "error"
    metrics["ollama_inference_duration"].labels(model=model, tool=call_type, status=status).observe(elapsed_s)


def track_embedding(metrics: dict, model: str, elapsed_s: float = 0.0, error: bool = False) -> None:
    """Record an Ollama embedding attempt (optionally with latency)."""
    if not metrics:
        return
    if "ollama_embedding_attempts" in metrics:
        metrics["ollama_embedding_attempts"].inc(1)
    if error:
        if "ollama_embedding_error" in metrics:
            metrics["ollama_embedding_error"].inc(1)
        return
    if "ollama_embedding_duration" in metrics and elapsed_s > 0:
        metrics["ollama_embedding_duration"].labels(model=model).observe(elapsed_s)


def track_vector_query(metrics: dict, store: str, success: bool = True) -> None:
    """Record vector store query."""
    if not metrics or "vectorstore_query" not in metrics:
        return
    metrics["vectorstore_query"].labels(store=store).inc(1)


def track_vector_upload(metrics: dict, store: str, success: bool = True) -> None:
    """Record vector store upload completion."""
    if not metrics or "vectorstore_upload" not in metrics:
        return
    status = "success" if success else "error"
    metrics["vectorstore_upload"].labels(store=store, status=status).inc(1)
    if not success and "vectorstore_upload_error" in metrics:
        metrics["vectorstore_upload_error"].labels(store=store).inc(1)


def track_tool_call(metrics: dict, tool: str, duration_s: float = 0.0) -> None:
    """Record agent tool call."""
    if not metrics or "agent_tool_calls" not in metrics:
        return
    metrics["agent_tool_calls"].labels(tool=tool).inc(1)
    if duration_s > 0 and "agent_tool_duration" in metrics:
        metrics["agent_tool_duration"].labels(tool=tool).inc(duration_s)


def track_streaming(metrics: dict, model: str, duration_s: float) -> None:
    """Record agent streaming_latency."""
    if not metrics or "agent_streaming_duration" not in metrics:
        return
    metrics["agent_streaming_duration"].labels(model=model).observe(duration_s)


def track_request_duration(metrics: dict, endpoint: str, duration_s: float) -> None:
    """Record generic Ollama HTTP request latency."""
    if not metrics or "ollama_request_duration" not in metrics:
        return
    metrics["ollama_request_duration"].labels(endpoint=endpoint).observe(duration_s)


def set_model_gauge(metrics: dict, model_name: str, available: bool) -> None:
    """Update model availability gauge."""
    if not metrics or "ollama_model_available" not in metrics:
        return
    gauge = metrics["ollama_model_available"]
    if hasattr(gauge, "labels"):
        gauge.labels(model=model_name).set(1 if available else 0)


def record_fallback(metrics: dict, from_model: str, to_model: str) -> None:
    """Record that model fallback was activated."""
    if not metrics or "ollama_model_fallback" not in metrics:
        return
    metrics["ollama_model_fallback"].labels(from_model=from_model, to_model=to_model).inc(1)


def track_vector_query_with_latency(metrics: dict, store: str, elapsed_s: float, success: bool = True) -> None:
    """Record vector store query with latency."""
    track_vector_query(metrics, store, success)
    if not metrics or "vectorstore_query_duration" not in metrics:
        return
    if success and elapsed_s > 0:
        metrics["vectorstore_query_duration"].labels(store=store).observe(elapsed_s)


def track_vector_upload_with_latency(metrics: dict, store: str, elapsed_s: float, success: bool = True) -> None:
    """Record vector store upload with latency."""
    track_vector_upload(metrics, store, success)
    if not metrics or "vectorstore_upload_duration" not in metrics:
        return
    if success and elapsed_s > 0:
        metrics["vectorstore_upload_duration"].labels(store=store).observe(elapsed_s)
