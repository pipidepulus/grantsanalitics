"""
AI Agent orchestrator using OpenAI Responses API.

This module is responsible only for conversation orchestration:
- managing the turn loop (tool-call → response → tool-call …)
- persisting messages to the database
- delegating retrieval configuration to ``services.retrieval``
- delegating score extraction/persistence to ``services.diagnostic``
- delegating all tool execution to ``services.tools``
"""

import asyncio
import json
import logging
import re
import time
import uuid
from openai import AsyncOpenAI
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.prompts import SYSTEM_PROMPT, CYRANO_DIAGNOSTIC_PROMPT
from app.database import run_with_db, SessionLocal
from app.models.conversation import Conversation, Message
from app.models.rag_event import RagEvent
from app.services.diagnostic import resolve_cyrano_score, persist_cyrano_score
from app.services.retrieval import build_file_search_tools, retrieve_project_context

logger = logging.getLogger(__name__)

# OpenAI Responses API emits inline file citations like:
# fileciteturn0file2  or  【fileciteturn0file2】  or  [fileciteturn0file2]
# Strip them so they don't appear in the rendered output.
_FILECITE_RE = re.compile(r'[\[【]?fileciteturn\d+file\d+[\]】]?')


def _clean_citations(text: str) -> str:
    return _FILECITE_RE.sub('', text).strip()

from app.services.tools import (
    TOOL_DEFINITIONS,
    handle_search_funding_calls,
    handle_extract_requirements,
    handle_calculate_budget,
    handle_generate_word_document,
    handle_run_diagnostic,
    handle_save_project_data,
    handle_save_to_project_memory,
    handle_save_diagnostic_result,
)

settings = get_settings()
client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


def _build_tools(project_id: uuid.UUID | None) -> list[dict]:
    """Compose the full tools list for a Responses API call.

    File-search entries are built by retrieval.build_file_search_tools
    which enforces per-project vector store isolation.  Web search is
    always appended last.
    """
    tools = list(TOOL_DEFINITIONS)
    tools.extend(build_file_search_tools(project_id))
    tools.append({"type": "web_search_preview"})
    return tools

# Tool handler dispatch map
TOOL_HANDLERS = {
    "search_funding_calls": handle_search_funding_calls,  # async def — no db needed
    "extract_requirements": handle_extract_requirements,
    "calculate_budget": handle_calculate_budget,
    "generate_word_document": handle_generate_word_document,
    "run_diagnostic": handle_run_diagnostic,
    "save_project_data": handle_save_project_data,
    "save_to_project_memory": handle_save_to_project_memory,
    "save_diagnostic_result": handle_save_diagnostic_result,
}


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
        query=query[:2000],   # guard against huge queries
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


# ---------------------------------------------------------------------------
# Primitive DB helpers — each accepts (db, *args) and returns plain dicts.
# Called via run_with_db so they run in a threadpool with their own session.
# ---------------------------------------------------------------------------

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

    # Inject session context for tools that require project_id / user_id when the
    # model forgets to include them in its function call arguments.
    NEEDS_PROJECT = ("run_diagnostic", "save_project_data", "generate_document")
    NEEDS_USER = ("save_project_data",)
    tool_args = dict(tool_args)
    if session_project_id and "project_id" not in tool_args and tool_name in NEEDS_PROJECT:
        tool_args["project_id"] = str(session_project_id)
    if session_user_id and "user_id" not in tool_args and tool_name in NEEDS_USER:
        tool_args["user_id"] = str(session_user_id)

    if asyncio.iscoroutinefunction(handler):
        # Async handlers (e.g. handle_search_funding_calls) manage their own resources.
        return await handler(tool_args)
    else:
        # Sync handlers take (args, db); run them in a threadpool with a fresh session.
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
            # Sync project_id if it was set/changed after conversation creation
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
    """Build message history from conversation for OpenAI Responses API."""
    messages = []
    for msg in conversation.messages:
        messages.append({"role": msg.role, "content": msg.content})
    return messages


async def process_chat_message(
    user_id: uuid.UUID,
    message: str,
    conversation_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
) -> dict:
    """
    Process a user message through the AI agent pipeline.
    Uses OpenAI Responses API with function calling and file_search.
    All DB operations run in a threadpool via run_with_db to avoid
    blocking the event loop.
    """
    # Get/create conversation (returns primitives only)
    conv_data = await run_with_db(_db_get_or_create_conv, user_id, conversation_id, project_id)

    # Save user message
    await run_with_db(_db_add_message, conv_data["id"], "user", message)

    # Pre-retrieve project documents and inject as context.
    # The Responses API file_search filter is unreliable with vector-store
    # attributes, so we use a direct filtered search and inject the results.
    project_docs_context = ""
    if project_id:
        project_docs_context = await asyncio.to_thread(
            retrieve_project_context, project_id, message
        )

    # Build input for Responses API
    context_info = (
        f"\n<session_context>\nuser_id: {user_id}\n"
        f"project_id: {project_id or 'ninguno'}\n"
        f"conversation_id: {conv_data['id']}\n</session_context>"
    )
    if project_docs_context:
        context_info += f"\n\n{project_docs_context}"

    input_messages = [{"role": "system", "content": SYSTEM_PROMPT + context_info}]
    input_messages.extend(conv_data["messages"])  # existing history
    input_messages.append({"role": "user", "content": message})  # current turn

    # Build tools with project-scoped file_search when project is active
    tools = _build_tools(project_id)

    # Call OpenAI Responses API
    t0 = time.monotonic()
    response = await client.responses.create(
        model=settings.OPENAI_MODEL,
        input=input_messages,
        tools=tools,
    )

    # Process response — handle tool calls iteratively
    assistant_content, tool_calls_log, cyrano_score = await _process_response(
        response, project_id, tools
    )
    latency_ms = int((time.monotonic() - t0) * 1000)

    # Save assistant message
    assistant_data = await run_with_db(
        _db_add_message, conv_data["id"], "assistant", assistant_content,
        tool_calls_log if tool_calls_log else None,
    )

    # Auto-title conversation from first user message if still default
    if conv_data["title"] == "Nueva conversación":
        await _auto_title_conversation(conv_data["id"], message)

    project_update = None
    if project_id:
        project_update = await run_with_db(persist_cyrano_score, project_id, cyrano_score)

    # RAG event for grounding audit
    try:
        await run_with_db(
            _persist_rag_event,
            conv_data["id"], project_id, message, tool_calls_log, latency_ms, 1,
        )
    except Exception as exc:
        logger.warning("rag_event_persist_failed", extra={"error": str(exc)})

    return {
        "conversation_id": conv_data["id"],
        "message": assistant_data,
        "project_update": project_update,
        "cyrano_score": cyrano_score,
    }


async def _process_response(
    response,
    project_id: uuid.UUID | None,
    tools: list[dict],
):
    """Process the Responses API response, handling tool calls in a loop."""
    tool_calls_log = []
    cyrano_score = None
    max_iterations = 15
    iteration = 0

    while iteration < max_iterations:
        iteration += 1

        # Check if there are function calls to handle
        function_calls = [item for item in response.output if item.type == "function_call"]

        if not function_calls:
            break

        # Process each function call
        tool_results = []
        ran_diagnostic = False
        for fc in function_calls:
            tool_name = fc.name
            try:
                tool_args = json.loads(fc.arguments)
            except json.JSONDecodeError:
                tool_args = {}

            logger.info("tool_call", extra={"tool": tool_name})
            result = await _call_tool(tool_name, tool_args, project_id, user_id)

            tool_calls_log.append({
                "tool": tool_name,
                "args": tool_args,
                "result": result,
            })

            tool_results.append({
                "type": "function_call_output",
                "call_id": fc.call_id,
                "output": result,
            })

            if tool_name == "run_diagnostic":
                ran_diagnostic = True

        # If run_diagnostic was called, inject the Cyrano rubric as a system
        # instruction so the LLM evaluates with the correct criteria and weights.
        if ran_diagnostic:
            tool_results.append({
                "type": "message",
                "role": "system",
                "content": CYRANO_DIAGNOSTIC_PROMPT,
            })

        # Continue the conversation with the same tool config
        response = await client.responses.create(
            model=settings.OPENAI_MODEL,
            previous_response_id=response.id,
            input=tool_results,
            tools=tools,
        )

    # Extract final text content
    text_parts = []
    for item in response.output:
        if item.type == "message":
            for content in item.content:
                if content.type == "output_text":
                    text_parts.append(content.text)

    assistant_content = "\n".join(text_parts) if text_parts else "Lo siento, no pude generar una respuesta."
    assistant_content = _clean_citations(assistant_content)

    cyrano_score = resolve_cyrano_score(tool_calls_log, assistant_content)
    return assistant_content, tool_calls_log, cyrano_score




async def _auto_title_conversation(conversation_id: uuid.UUID, first_message: str):
    """Generate a short topic title for the conversation using AI."""
    try:
        response = await client.responses.create(
            model=settings.OPENAI_MODEL,
            input=[
                {
                    "role": "system",
                    "content": "Genera un título corto (máximo 6 palabras) que resuma el tema de este mensaje. Solo responde con el título, sin comillas ni puntuación final."
                },
                {"role": "user", "content": first_message[:500]},
            ],
        )
        title = response.output_text.strip().strip('"').strip(".")
        if not title or len(title) > 100:
            title = first_message.strip().replace("\n", " ")[:77] + "..."
    except Exception:
        title = first_message.strip().replace("\n", " ")
        if len(title) > 80:
            title = title[:77] + "..."
    await run_with_db(_db_update_title, conversation_id, title)


async def process_chat_message_stream(
    user_id: uuid.UUID,
    message: str,
    conversation_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
):
    """
    Stream a chat response using SSE events.
    Yields dict events: {type: 'meta'|'delta'|'tool'|'done', ...}
    All DB operations run in a threadpool via run_with_db.
    """
    conv_data = await run_with_db(_db_get_or_create_conv, user_id, conversation_id, project_id)

    # Save user message
    await run_with_db(_db_add_message, conv_data["id"], "user", message)

    # Emit conversation ID immediately
    yield {"type": "meta", "conversation_id": str(conv_data["id"])}
    await asyncio.sleep(0)

    # Pre-retrieve project documents and inject as context.
    project_docs_context = ""
    if project_id:
        project_docs_context = await asyncio.to_thread(
            retrieve_project_context, project_id, message
        )

    # Build input for Responses API
    context_info = (
        f"\n<session_context>\nuser_id: {user_id}\n"
        f"project_id: {project_id or 'ninguno'}\n"
        f"conversation_id: {conv_data['id']}\n</session_context>"
    )
    if project_docs_context:
        context_info += f"\n\n{project_docs_context}"

    input_messages = [{"role": "system", "content": SYSTEM_PROMPT + context_info}]
    input_messages.extend(conv_data["messages"])  # existing history
    input_messages.append({"role": "user", "content": message})  # current turn

    # Build tools with project-scoped file_search when project is active
    tools = _build_tools(project_id)

    t0 = time.monotonic()
    tool_calls_log = []
    full_text = ""
    iteration = 0
    max_iterations = 15

    # current_input for the first call is the full message history;
    # for subsequent calls it holds the tool-call output items.
    current_input: list[dict] = input_messages
    previous_response_id: str | None = None

    while iteration < max_iterations:
        iteration += 1
        accumulated_fcs: dict[str, dict] = {}  # call_id -> {name, call_id, args}

        call_kwargs: dict = {
            "model": settings.OPENAI_MODEL,
            "input": current_input,
            "tools": tools,
            "stream": True,
        }
        if previous_response_id:
            call_kwargs["previous_response_id"] = previous_response_id

        stream = await client.responses.create(**call_kwargs)

        async for event in stream:
            et = getattr(event, "type", None)

            if et == "response.output_item.added":
                item = event.item
                if getattr(item, "type", None) == "function_call":
                    accumulated_fcs[item.call_id] = {
                        "name": item.name,
                        "call_id": item.call_id,
                        "args": "",
                    }
                    yield {"type": "tool", "name": item.name, "status": "running"}
                    await asyncio.sleep(0)

            elif et == "response.function_call_arguments.delta":
                cid = getattr(event, "call_id", None)
                if cid and cid in accumulated_fcs:
                    accumulated_fcs[cid]["args"] += event.delta

            elif et == "response.output_text.delta":
                full_text += event.delta
                yield {"type": "delta", "content": event.delta}
                await asyncio.sleep(0)

            elif et == "response.completed":
                previous_response_id = event.response.id

        # No tool calls this turn → final response already streamed
        if not accumulated_fcs:
            break

        # Execute collected tool calls
        tool_results = []
        for fc in accumulated_fcs.values():
            tool_name = fc["name"]
            try:
                tool_args = json.loads(fc["args"])
            except json.JSONDecodeError:
                tool_args = {}

            result = await _call_tool(tool_name, tool_args, project_id, user_id)
            await asyncio.sleep(0)

            tool_results.append({
                "type": "function_call_output",
                "call_id": fc["call_id"],
                "output": result,
            })

        current_input = tool_results

    if not full_text:
        full_text = "Lo siento, no pude generar una respuesta."
        yield {"type": "delta", "content": full_text}
        await asyncio.sleep(0)

    full_text = _clean_citations(full_text)

    # Save assistant message
    assistant_data = await run_with_db(
        _db_add_message, conv_data["id"], "assistant", full_text,
        tool_calls_log if tool_calls_log else None,
    )

    # Auto-title
    if conv_data["title"] == "Nueva conversación":
        await _auto_title_conversation(conv_data["id"], message)

    cyrano_score = resolve_cyrano_score(tool_calls_log, full_text)
    latency_ms = int((time.monotonic() - t0) * 1000)

    project_update = None
    if project_id:
        project_update = await run_with_db(persist_cyrano_score, project_id, cyrano_score)

    # RAG event for grounding audit
    try:
        await run_with_db(
            _persist_rag_event,
            conv_data["id"], project_id, message, tool_calls_log, latency_ms, iteration,
        )
    except Exception as exc:
        logger.warning("rag_event_persist_failed", extra={"error": str(exc)})

    yield {
        "type": "done",
        "conversation_id": str(conv_data["id"]),
        "message_id": str(assistant_data["id"]),
        "tool_calls": tool_calls_log if tool_calls_log else None,
        "cyrano_score": cyrano_score,
    }
