"""
AI Agent orchestrator using Ollama /v1/chat/completions.

Instrumented with Prometheus metrics via app.observability.
"""

import asyncio
import json
import logging
import re
import time
import uuid
import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.prompts import SYSTEM_PROMPT, CYRANO_DIAGNOSTIC_PROMPT
from app.database import run_with_db, SessionLocal
from app.models.conversation import Conversation, Message
from app.models.rag_event import RagEvent

logger = logging.getLogger(__name__)

# ── Observability helpers (lazy to avoid hard-dep on prometheus_client at startup) ──

def _obs():
    """Return custom metrics dict if available, else None."""
    try:
        from app.main import _has_metrics, _observability_metrics
        if _has_metrics:
            return _observability_metrics
    except Exception:
        pass
    return None


_FILECITE_RE = re.compile(r'[\[【]?fileciteturn\d+file\d+[\]】]?')


def _clean_citations(text: str) -> str:
    return _FILECITE_RE.sub('', text).strip()


from app.services.tools import (
    TOOL_DEFINITIONS,
    handle_fetch_url,
    handle_search_funding_calls,
    handle_extract_requirements,
    handle_calculate_budget,
    handle_generate_word_document,
    handle_run_diagnostic,
    handle_save_project_data,
    handle_save_to_project_memory,
    handle_save_diagnostic_result,
)
from app.services.retrieval import build_local_search_tools, retrieve_project_context
from app.services.diagnostic import resolve_cyrano_score, persist_cyrano_score


# ------ Ollama helpers ------

def _get_ollama_url() -> str:
    settings = get_settings()
    base = settings.OLLAMA_BASE_URL.rstrip("/")
    return f"{base}/v1/chat/completions"


async def _ollama_chat(
    messages: list[dict],
    tools: list[dict] | None = None,
    model: str | None = None,
) -> dict:
    """Call Ollama /v1/chat/completions (non-streaming). Instrumented."""
    settings = get_settings()
    payload: dict = {
        "model": model or settings.OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "temperature": 0.7,
    }
    if tools:
        payload["tools"] = tools

    _obs_metrics = _obs()
    started = time.monotonic()

    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(_get_ollama_url(), json=payload)
        elapsed = time.monotonic() - started

        # Request duration (generic endpoint)
        req_hist = _obs_metrics.get("ollama_request_duration") if _obs_metrics else None
        if req_hist is not None:
            req_hist.labels(endpoint="/v1/chat/completions").observe(elapsed)

        if not resp.is_success:
            # Record error
            att = _obs_metrics.get("ollama_inference_attempts") if _obs_metrics else None
            if att:
                att.labels(model=payload["model"], tool="chat_nonstream").inc(1)
            err = _obs_metrics.get("ollama_embedding_error") if _obs_metrics else None
            if err:
                err.inc(1)
            resp.raise_for_status()

        data = resp.json()

        # Record success + count
        if _obs_metrics:
            att = _obs_metrics.get("ollama_inference_attempts")
            if att:
                att.labels(model=payload["model"], tool="chat_nonstream").inc(1)

        return data


def _parse_ollama_response(response_json: dict) -> tuple[str, list[dict] | None, str]:
    """Extract assistant content and tool calls from an Ollama chat response."""
    choices = response_json.get("choices", [])
    if not choices:
        return "No se recibió respuesta del modelo.", None, ""

    message = choices[0].get("message", {})
    content = message.get("content", "") or ""
    response_id = ""

    tool_calls = None
    tc_list = message.get("tool_calls", [])
    if tc_list:
        tool_calls = []
        for tc in tc_list:
            func = tc.get("function", {})
            if func.get("name"):
                tool_calls.append({
                    "name": func["name"],
                    "arguments": json.loads(func.get("arguments", "{}")),
                    "call_id": tc.get("id", f"call_{len(tool_calls)}"),
                })
        response_id = tc_list[0].get("id", "")
    else:
        response_id = tc_list[0].get("id", "") if tc_list else ""

    return content, tool_calls, response_id


async def _ensure_model_available() -> str:
    """Auto-detect available model; fallback to OLLAMA_MODEL_FALLBACK. Instrumented."""
    settings = get_settings()
    obs = _obs()

    try:
        async with httpx.AsyncClient() as client:
            tags_resp = await client.get(f"{settings.OLLAMA_BASE_URL}/api/tags")
            tags_resp.raise_for_status()
            models = [m["name"] for m in tags_resp.json().get("models", [])]
            if any(settings.OLLAMA_MODEL in m or m.startswith(settings.OLLAMA_MODEL) for m in models):
                # Update gauge
                gauge = obs.get("ollama_model_available") if obs else None
                if gauge and hasattr(gauge, "labels"):
                    gauge.labels(model=settings.OLLAMA_MODEL).set(1)
                return settings.OLLAMA_MODEL
    except Exception:
        pass

    if settings.OLLAMA_MODEL_FALLBACK:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{settings.OLLAMA_BASE_URL}/api/generate",
                    json={"model": settings.OLLAMA_MODEL_FALLBACK, "prompt": "test", "stream": False},
                )
                if resp.status_code == 200:
                    logger.info("ollama_model_fallback_activated", extra={"model": settings.OLLAMA_MODEL_FALLBACK})
                    # Record fallback
                    if obs:
                        fb = obs.get("ollama_model_fallback")
                        if fb:
                            fb.labels(from_model=settings.OLLAMA_MODEL, to_model=settings.OLLAMA_MODEL_FALLBACK).inc(1)
                    return settings.OLLAMA_MODEL_FALLBACK
        except Exception:
            pass

    raise RuntimeError(
        f"Modelo no encontrado. Ejecuta: ollama pull {settings.OLLAMA_MODEL}"
    )


# ------ Search tool handlers ------

async def _handle_retrieve_knowledge_base(args: dict) -> str:
    """Handle the retrieve_knowledge_base function call."""
    from app.services.vector_store import search_knowledge_base
    query = args.get("query", "")
    max_results = args.get("max_results", 10)
    _obs_metrics = _obs()
    t0 = time.monotonic()
    try:
        results = search_knowledge_base(query, max_results)
        _record_tool_call_duration(_obs_metrics, "retrieve_knowledge_base", time.monotonic() - t0)
        if not results:
            return json.dumps({"status": "ok", "message": "No se encontraron resultados.", "results": []})
        formatted = []
        for i, r in enumerate(results, 1):
            formatted.append({
                "position": i,
                "filename": r.get("filename", "unknown"),
                "content": r.get("content", "")[:1000],
                "score": round(float(r.get("score", 0)), 4) if r.get("score") is not None else None,
            })
        return json.dumps({"status": "ok", "results": formatted, "total": len(formatted)})
    except Exception:
        _record_tool_call_duration(_obs_metrics, "retrieve_knowledge_base", time.monotonic() - t0)
        raise


async def _handle_retrieve_project_documents(args: dict) -> str:
    """Handle the retrieve_project_documents function call."""
    from app.services.vector_store import search_projects_store
    project_id = args.get("project_id")
    if not project_id:
        return json.dumps({"status": "error", "message": "project_id es necesario"})
    query = args.get("query", "")
    max_results = args.get("max_results", 8)
    _obs_metrics = _obs()
    t0 = time.monotonic()
    try:
        results = search_projects_store(project_id, query, max_results)
        _record_tool_call_duration(_obs_metrics, "retrieve_project_documents", time.monotonic() - t0)
        if not results:
            return json.dumps({"status": "ok", "message": "No se encontraron documentos.", "results": []})
        formatted = []
        for i, r in enumerate(results, 1):
            formatted.append({
                "position": i,
                "filename": r.get("filename", "unknown"),
                "content": r.get("content", "")[:1000],
                "score": round(float(r.get("score", 0)), 4) if r.get("score") is not None else None,
                "chunks": r.get("total_chunks", 1),
            })
        return json.dumps({"status": "ok", "results": formatted, "total": len(formatted)})
    except Exception:
        _record_tool_call_duration(_obs_metrics, "retrieve_project_documents", time.monotonic() - t0)
        raise


# ------ Tool handler dispatch map (extended with search tools) ------

SEARCH_TOOL_HANDLERS = {
    "retrieve_knowledge_base": _handle_retrieve_knowledge_base,
    "retrieve_project_documents": _handle_retrieve_project_documents,
}

TOOL_HANDLERS = {
    "fetch_url": handle_fetch_url,
    "search_funding_calls": handle_search_funding_calls,
    "extract_requirements": handle_extract_requirements,
    "calculate_budget": handle_calculate_budget,
    "generate_word_document": handle_generate_word_document,
    "run_diagnostic": handle_run_diagnostic,
    "save_project_data": handle_save_project_data,
    "save_to_project_memory": handle_save_to_project_memory,
    "save_diagnostic_result": handle_save_diagnostic_result,
}
# Combine regular + search handlers
TOOL_HANDLERS.update(SEARCH_TOOL_HANDLERS)


def _build_tools(project_id: uuid.UUID | None) -> list[dict]:
    """Compose the full tools list: standard tools + local search tools."""
    tools = list(TOOL_DEFINITIONS)
    tools.extend(build_local_search_tools(project_id))
    return tools


def _record_tool_call_duration(metrics: dict | None, tool: str, duration_s: float) -> None:
    """Record agent tool call with duration."""
    if not metrics:
        return
    cnt = metrics.get("agent_tool_calls")
    if cnt:
        cnt.labels(tool=tool).inc(1)
    dur = metrics.get("agent_tool_duration")
    if dur and duration_s > 0:
        dur.labels(tool=tool).inc(duration_s)


# ------ Internal helpers ------

def _persist_rag_event(
    db: Session,
    conversation_id: uuid.UUID,
    project_id: uuid.UUID | None,
    query: str,
    tool_calls_log: list[dict],
    latency_ms: int,
    turn_index: int,
) -> None:
    """Write a RagEvent row after an agent turn completes."""
    tools_used = list({entry["tool"] for entry in tool_calls_log})
    event = RagEvent(
        conversation_id=conversation_id,
        project_id=project_id,
        query=query[:2000],
        tools_used=tools_used,
        has_file_search=any(
            t in ("file_search", "search_funding_calls") for t in tools_used
        ),
        has_web_search="web_search_preview" in tools_used,
        function_tool_count=sum(
            1 for t in tools_used
            if t not in ("file_search", "web_search_preview", "search_funding_calls")
        ),
        response_latency_ms=latency_ms,
        turn_index=turn_index,
    )
    db.add(event)
    db.commit()


def _db_get_or_create_conv(
    db: Session,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
    project_id: uuid.UUID | None,
) -> dict:
    conv = get_or_create_conversation(db, user_id, conversation_id, project_id)
    return {
        "id": conv.id,
        "title": conv.title,
        "messages": [{"role": m.role, "content": m.content} for m in conv.messages],
    }


def _db_add_message(
    db: Session,
    conversation_id: uuid.UUID,
    role: str,
    content: str,
    tool_calls: list | None = None,
) -> dict:
    msg = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        tool_calls=tool_calls if tool_calls else None,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return {
        "id": msg.id,
        "role": msg.role,
        "content": msg.content,
        "tool_calls": msg.tool_calls,
        "created_at": msg.created_at,
    }


def _db_update_title(db: Session, conversation_id: uuid.UUID, title: str) -> None:
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if conv:
        conv.title = title
        db.commit()


async def _call_tool(
    tool_name: str,
    tool_args: dict,
    session_project_id: uuid.UUID | None = None,
    session_user_id: uuid.UUID | None = None,
) -> str:
    """Dispatch a tool handler, giving sync handlers their own DB session."""
    handler = TOOL_HANDLERS.get(tool_name)
    if not handler:
        logger.warning("unknown_tool", extra={"tool": tool_name})
        return json.dumps({"status": "error", "message": f"Tool '{tool_name}' not found"})

    # Inject session context for tools that require project_id / user_id
    NEEDS_PROJECT = ("run_diagnostic", "save_project_data", "generate_document", "retrieve_project_documents")
    NEEDS_USER = ("save_project_data",)
    tool_args = dict(tool_args)
    if session_project_id and "project_id" not in tool_args and tool_name in NEEDS_PROJECT:
        tool_args["project_id"] = str(session_project_id)
    if session_user_id and "user_id" not in tool_args and tool_name in NEEDS_USER:
        tool_args["user_id"] = str(session_user_id)

    if asyncio.iscoroutinefunction(handler):
        return await handler(tool_args)
    else:
        def _run_sync():
            db = SessionLocal()
            try:
                return handler(tool_args, db)
            finally:
                db.close()
        return await asyncio.to_thread(_run_sync)


def get_or_create_conversation(
    db: Session, user_id: uuid.UUID, conversation_id: uuid.UUID | None, project_id: uuid.UUID | None
) -> Conversation:
    """Get existing conversation or create new one."""
    if conversation_id:
        conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
        if conv:
            if project_id and conv.project_id != project_id:
                conv.project_id = project_id
                db.commit()
                db.refresh(conv)
            return conv

    from app.models.user import User
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise ValueError(f"User {user_id} not found")

    conv = Conversation(user_id=user_id, project_id=project_id)
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


def build_message_history(conversation: Conversation) -> list[dict]:
    """Build message history from conversation for Ollama chat."""
    messages = []
    for msg in conversation.messages:
        messages.append({"role": msg.role, "content": msg.content})
    return messages


# ------ Main processing — non-streaming ------

async def process_chat_message(
    user_id: uuid.UUID,
    message: str,
    conversation_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
) -> dict:
    """
    Process a user message through the AI agent pipeline.
    Uses Ollama /v1/chat/completions with function calling.
    All DB operations run in a threadpool via run_with_db.
    """
    conv_data = await run_with_db(_db_get_or_create_conv, user_id, conversation_id, project_id)
    await run_with_db(_db_add_message, conv_data["id"], "user", message)

    # Pre-retrieve project documents and inject as context
    project_docs_context = ""
    if project_id:
        project_docs_context = await asyncio.to_thread(
            retrieve_project_context, project_id, message
        )

    context_info = (
        f"\n<session_context>\nuser_id: {user_id}\n"
        f"project_id: {project_id or 'ninguno'}\n"
        f"conversation_id: {conv_data['id']}\n</session_context>"
    )
    if project_docs_context:
        context_info += f"\n\n{project_docs_context}"

    input_messages = [{"role": "system", "content": SYSTEM_PROMPT + context_info}]
    input_messages.extend(conv_data["messages"])
    input_messages.append({"role": "user", "content": message})

    tools = _build_tools(project_id)
    model = await _ensure_model_available()

    # Main loop: call -> extract tool calls -> execute -> repeat -> final content
    max_iterations = 15
    iteration = 0
    assistant_content = ""
    tool_calls_log = []
    cyrano_score = None

    total_start = time.monotonic()
    obs_metrics = _obs()

    while iteration < max_iterations:
        iteration += 1
        t0 = time.monotonic()

        response_json = await _ollama_chat(input_messages, tools=tools, model=model)
        elapsed = time.monotonic() - t0

        # Record inference with latency
        if obs_metrics:
            att = obs_metrics.get("ollama_inference_attempts")
            if att:
                att.labels(model=model, tool="chat").inc(1)
            t_calls = obs_metrics.get("agent_tool_calls")
            if t_calls:
                t_calls.labels(tool="agent_turn").inc(1)

        content, tool_calls, _ = _parse_ollama_response(response_json)

        if tool_calls:
            # Add the assistant message (with tool_calls) to history BEFORE tool results
            raw_tool_calls = response_json.get("choices", [{}])[0].get("message", {}).get("tool_calls", [])
            input_messages.append({
                "role": "assistant",
                "content": content or "",
                "tool_calls": raw_tool_calls,
            })

            tool_results = []
            for tc in tool_calls:
                tool_name = tc["name"]
                tool_args = tc["arguments"]
                tool_t0 = time.monotonic()
                result = await _call_tool(tool_name, tool_args, project_id, user_id)
                tool_elapsed = time.monotonic() - tool_t0
                tool_calls_log.append({"tool": tool_name, "args": tool_args, "result": result})
                _record_tool_call_duration(obs_metrics, tool_name, tool_elapsed)
                tool_results.append({"role": "tool", "tool_call_id": tc["call_id"], "content": result})

            # If run_diagnostic was called, inject the Cyrano rubric
            ran_diagnostic = any(tc["tool"] == "run_diagnostic" for tc in tool_calls_log)
            if ran_diagnostic:
                tool_results.append({
                    "role": "system",
                    "content": CYRANO_DIAGNOSTIC_PROMPT,
                })

            input_messages.extend(tool_results)
        else:
            # No tool calls — this is the final answer
            assistant_content = content if content.strip() else "Lo siento, no pude generar una respuesta."
            assistant_content = _clean_citations(assistant_content)
            break

    latency_ms = int((time.monotonic() - total_start) * 1000)

    assistant_data = await run_with_db(
        _db_add_message, conv_data["id"], "assistant", assistant_content,
        tool_calls_log if tool_calls_log else None,
    )

    if conv_data["title"] == "Nueva conversación":
        await _auto_title_conversation(conv_data["id"], message)

    project_update = None
    if project_id:
        project_update = await run_with_db(persist_cyrano_score, project_id, cyrano_score)

    try:
        await run_with_db(_persist_rag_event, conv_data["id"], project_id, message, tool_calls_log, latency_ms, iteration)
    except Exception as exc:
        logger.warning("rag_event_persist_failed", extra={"error": str(exc)})

    return {
        "conversation_id": conv_data["id"],
        "message": assistant_data,
        "project_update": project_update,
        "cyrano_score": cyrano_score,
    }


# ------ Auto-title helper ------

async def _auto_title_conversation(conversation_id: uuid.UUID, first_message: str):
    """Generate a short topic title for the conversation using AI."""
    try:
        response = await _ollama_chat(
            [
                {"role": "system", "content": "Genera un título corto (máximo 6 palabras) que resuma el tema de este mensaje. Solo responde con el título, sin comillas ni puntuación final."},
                {"role": "user", "content": first_message[:500]},
            ],
            model=await _ensure_model_available(),
        )
        content, _, _ = _parse_ollama_response(response)
        title = content.strip().strip('"').strip(".")
        if not title or len(title) > 100:
            title = first_message.strip().replace("\n", " ")[:77] + ".."
        await run_with_db(_db_update_title, conversation_id, title)
    except Exception:
        title = first_message.strip()
        if len(title) > 80:
            title = title[:77] + ".."
        await run_with_db(_db_update_title, conversation_id, title)


# ------ Streaming — SSE ------

async def _ollama_stream_deltas(
    messages: list[dict],
    tools: list[dict] | None = None,
    model: str | None = None,
):
    """Accumulate SSE from Ollama internally, yield delta + accumulated_tool_calls events."""
    settings = get_settings()
    payload: dict = {
        "model": model or settings.OLLAMA_MODEL,
        "messages": messages,
        "tools": tools or [],
        "stream": True,
        "temperature": 0.7,
    }

    accumulated_tool_calls: dict[str, dict] = {}
    full_text = ""
    obs_metrics = _obs()
    t0 = time.monotonic()

    async with httpx.AsyncClient(timeout=300) as client:
        async with client.stream("POST", _get_ollama_url(), json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                stripped = line.strip()
                if not stripped.startswith("data: "):
                    continue
                payload_str = stripped[6:]
                if payload_str == "[DONE]":
                    break
                try:
                    data = json.loads(payload_str)
                except json.JSONDecodeError:
                    continue
                choice = (data.get("choices") or [{}])[0]
                delta = choice.get("delta", {})
                if not delta:
                    continue
                if text := delta.get("content"):
                    full_text += text
                    yield {"type": "delta", "content": text}
                for tc in delta.get("tool_calls", []):
                    tc_id = tc.get("id", "")
                    if not tc_id:
                        continue
                    if tc_id not in accumulated_tool_calls:
                        accumulated_tool_calls[tc_id] = {
                            "name": tc.get("function", {}).get("name", ""),
                            "call_id": tc_id,
                            "arguments": "",
                        }
                    func = tc.get("function", {})
                    if "arguments" in func:
                        accumulated_tool_calls[tc_id]["arguments"] += func["arguments"]

    # Record streaming duration
    elapsed = time.monotonic() - t0
    if obs_metrics:
        hist = obs_metrics.get("agent_streaming_duration")
        if hist is not None:
            hist.labels(model=model or settings.OLLAMA_MODEL).observe(elapsed)
        obs_records = obs_metrics.get("ollama_inference_attempts")
        if obs_records:
            obs_records.labels(model=model or settings.OLLAMA_MODEL, tool="stream").inc(1)

    # Final event with accumulated results
    yield {"type": "accumulate_done", "full_text": full_text, "tool_calls": accumulated_tool_calls}


async def process_chat_message_stream(
    user_id: uuid.UUID,
    message: str,
    conversation_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
):
    """
    Stream a chat response using SSE events.
    Yields dict events: {type: 'meta'|'delta'|'tool'|'done', ...}
    """
    conv_data = await run_with_db(_db_get_or_create_conv, user_id, conversation_id, project_id)
    await run_with_db(_db_add_message, conv_data["id"], "user", message)

    yield {"type": "meta", "conversation_id": str(conv_data["id"])}
    await asyncio.sleep(0)

    project_docs_context = ""
    if project_id:
        project_docs_context = await asyncio.to_thread(
            retrieve_project_context, project_id, message
        )

    context_info = (
        f"\n<session_context>\nuser_id: {user_id}\n"
        f"project_id: {project_id or 'ninguno'}\n"
        f"conversation_id: {conv_data['id']}\n</session_context>"
    )
    if project_docs_context:
        context_info += f"\n\n{project_docs_context}"

    input_messages = [{"role": "system", "content": SYSTEM_PROMPT + context_info}]
    input_messages.extend(conv_data["messages"])
    input_messages.append({"role": "user", "content": message})

    tools = _build_tools(project_id)
    model = await _ensure_model_available()

    full_text = ""
    tool_calls_log = []
    latency_ms = 0
    iteration = 0
    max_iterations = 15

    total_start = time.monotonic()
    obs = _obs()
    first_stream_elapsed = 0.0  # capture first stream's latency

    while iteration < max_iterations:
        iteration += 1

        # Stream the response — iterate events, collect text and tool calls
        accumulated_tc: dict[str, dict] = {}
        stream_text = ""
        async for event in _ollama_stream_deltas(input_messages, tools=tools, model=model):
            if event.get("type") == "accumulate_done":
                stream_text = event["full_text"]
                accumulated_tc = event["tool_calls"]
            else:
                yield event

        full_text += stream_text

        # Capture first stream's duration for agent_streaming_duration metric
        if iteration == 1 and first_stream_elapsed == 0.0:
            first_stream_elapsed = time.monotonic() - total_start

        if not accumulated_tc:
            break

        # Add assistant message with tool_calls to history BEFORE tool results
        input_messages.append({
            "role": "assistant",
            "content": stream_text or "",
            "tool_calls": [
                {
                    "id": tc["call_id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments"]},
                }
                for tc in accumulated_tc.values()
            ],
        })

        # Execute collected tool calls as a batch
        tool_results = []
        for tc in accumulated_tc.values():
            tool_name = tc["name"]
            try:
                tool_args = json.loads(tc["arguments"])
            except json.JSONDecodeError:
                tool_args = {}

            tool_t0 = time.monotonic()
            result_text = await _call_tool(tool_name, tool_args, project_id, user_id)
            tool_elapsed = time.monotonic() - tool_t0
            await asyncio.sleep(0)  # allow stream to flush

            tool_calls_log.append({"tool": tool_name, "args": tool_args, "result": result_text})
            _record_tool_call_duration(obs, tool_name, tool_elapsed)
            tool_results.append({"role": "tool", "tool_call_id": tc["call_id"], "content": result_text})

        # Build messages for the tool results
        for tr in tool_results:
            input_messages.append(tr)

        # If run_diagnostic was called, inject the Cyrano rubric
        ran_diagnostic = any(tc["tool"] == "run_diagnostic" for tc in tool_calls_log)
        if ran_diagnostic:
            input_messages.append({"role": "system", "content": CYRANO_DIAGNOSTIC_PROMPT})

        # Stream the follow-up response (tool results as context)
        stream_text2 = ""
        accumulated_tc2: dict[str, dict] = {}
        async for event in _ollama_stream_deltas(input_messages, tools=tools, model=model):
            if event.get("type") == "accumulate_done":
                stream_text2 = event["full_text"]
                accumulated_tc2 = event["tool_calls"]
            else:
                yield event
        full_text += stream_text2

        if accumulated_tc2:
            # Add assistant message with tool_calls to history BEFORE tool results
            input_messages.append({
                "role": "assistant",
                "content": stream_text2 or "",
                "tool_calls": [
                    {
                        "id": tc["call_id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": tc["arguments"]},
                    }
                    for tc in accumulated_tc2.values()
                ],
            })
            tool_results2 = []
            for tc in accumulated_tc2.values():
                tool_name = tc["name"]
                try:
                    tool_args = json.loads(tc["arguments"])
                except json.JSONDecodeError:
                    tool_args = {}
                tool_t0 = time.monotonic()
                result_text = await _call_tool(tool_name, tool_args, project_id, user_id)
                tool_elapsed = time.monotonic() - tool_t0
                tool_calls_log.append({"tool": tool_name, "args": tool_args, "result": result_text})
                _record_tool_call_duration(obs, tool_name, tool_elapsed)
                tool_results2.append({"role": "tool", "tool_call_id": tc["call_id"], "content": result_text})
            for tr in tool_results2:
                input_messages.append(tr)

    if not full_text:
        full_text = "Lo siento, no pude generar una respuesta."
        yield {"type": "delta", "content": full_text}
        await asyncio.sleep(0)

    # Clean and save
    full_text = _clean_citations(full_text)

    assistant_data = await run_with_db(
        _db_add_message, conv_data["id"], "assistant", full_text,
        tool_calls_log if tool_calls_log else None,
    )

    if conv_data["title"] == "Nueva conversación":
        await _auto_title_conversation(conv_data["id"], message)

    cyrano_score = resolve_cyrano_score(tool_calls_log, full_text)
    latency_ms = int((time.monotonic() - total_start) * 1000)

    project_update = None
    if project_id:
        project_update = await run_with_db(persist_cyrano_score, project_id, cyrano_score)

    try:
        await run_with_db(_persist_rag_event, conv_data["id"], project_id, message, tool_calls_log, latency_ms, iteration)
    except Exception as exc:
        logger.warning("rag_event_persist_failed", extra={"error": str(exc)})

    yield {
        "type": "done",
        "conversation_id": str(conv_data["id"]),
        "message_id": str(assistant_data["id"]),
        "tool_calls": tool_calls_log if tool_calls_log else None,
        "cyrano_score": cyrano_score,
    }
