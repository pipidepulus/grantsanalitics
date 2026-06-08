"""
Deep health check for Ollama — connectivity, model availability, inference test, embedding test.
"""

import logging

logger = logging.getLogger(__name__)


async def check_deep_health(ollama_base_url: str, model_name: str, embedding_model: str) -> dict:
    """Deep health check for Ollama.
    
    Returns:
        dict with keys: status, detail, models, model_availability, inference_test, embedding_test
    """
    import httpx

    result = {
        "status": "error",
        "detail": "not checked",
        "models": [],
        "model_availability": {},
        "inference_test": False,
        "embedding_test": False,
    }

    # 1. connectivity
    ollama_ok = False
    tags = []
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{ollama_base_url}/api/tags")
            resp.raise_for_status()
            tags = resp.json().get("models", [])
        ollama_ok = True
    except Exception as exc:
        result["detail"] = f"Ollama unreachable: {exc}"
        logger.error(f"health_check: Ollama not reachable: {exc}")
        return result

    model_names = [m["name"] for m in tags]
    result["models"] = model_names[:10]

    # 2. model availability
    model_avail = {}
    for name in [model_name, embedding_model]:
        found = any(name == m or m.startswith(name) for m in model_names)
        model_avail[name] = found
    result["model_availability"] = model_avail

    # 3. inference test
    if model_avail.get(model_name):
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{ollama_base_url}/v1/chat/completions",
                    json={
                        "model": model_name,
                        "messages": [{"role": "user", "content": "ok"}],
                        "max_tokens": 1,
                    },
                )
                resp.raise_for_status()
                result["inference_test"] = True
        except Exception as exc:
            logger.warning(f"health_check: inference test failed for {model_name}: {exc}")
            result["detail"] = f"Inference test failed: {exc}"

    # 4. embedding test
    if model_avail.get(embedding_model):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{ollama_base_url}/api/embed",
                    json={"model": embedding_model, "input": "ok"},
                )
                resp.raise_for_status()
                result["embedding_test"] = True
        except Exception as exc:
            logger.warning(f"health_check: embedding test failed for {embedding_model}: {exc}")
            result["detail"] = f"Embedding test failed: {exc}"

    all_ok = ollama_ok and model_avail.get(model_name, False) and model_avail.get(embedding_model, False)
    result["status"] = "ok" if all_ok else "warning"
    if not all_ok:
        missing = [m for m in [model_name, embedding_model] if not model_avail.get(m)]
        result["detail"] = f"Missing models: {missing}"

    logger.info(
        "ollama_health_check",
        extra={
            "status": result["status"],
            "models_available": len(model_names),
            "inference_test": result["inference_test"],
            "embedding_test": result["embedding_test"],
        },
    )
    return result
