"""
Function tools definitions for OpenAI Responses API.
These tools are invoked by the AI agent during conversation.
"""

import asyncio
import json
import re
import uuid
from io import BytesIO
from docx import Document
from docx.shared import Pt, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.call_spec import CallSpec
from app.models.document import GeneratedDoc
from app.models.cyrano_evaluation import CyranoEvaluation
from app.models.enums import ProjectStatus, ProjectLanguage
from app.database import SessionLocal
from openai import AsyncOpenAI
from app.config import get_settings
from app.core.prompts import EXTRACT_REQUIREMENTS_PROMPT


# ──────────────────────────────────────────────
# Tool definitions for OpenAI Responses API
# ──────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "name": "search_funding_calls",
        "description": "Busca convocatorias activas de financiamiento en la web según sector y territorio. Retorna una lista de convocatorias relevantes.",
        "parameters": {
            "type": "object",
            "properties": {
                "sector": {
                    "type": "string",
                    "description": "Sector del proyecto (ej: agricultura, tecnología, salud, educación)"
                },
                "territory": {
                    "type": "string",
                    "description": "País o región de interés"
                },
                "keywords": {
                    "type": ["string", "null"],
                    "description": "Palabras clave adicionales para la búsqueda"
                }
            },
            "required": ["sector", "territory", "keywords"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "extract_requirements",
        "description": "Extrae requisitos estructurados de un documento de convocatoria previamente subido. Analiza criterios de elegibilidad, montos, fechas y secciones obligatorias.",
        "parameters": {
            "type": "object",
            "properties": {
                "document_text": {
                    "type": "string",
                    "description": "Texto del documento de convocatoria a analizar"
                },
                "call_spec_id": {
                    "type": ["string", "null"],
                    "description": "ID de la convocatoria en la base de datos"
                }
            },
            "required": ["document_text", "call_spec_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "calculate_budget",
        "description": "Valida que los rubros presupuestarios no superen los topes de la convocatoria. Verifica alineación con actividades del proyecto.",
        "parameters": {
            "type": "object",
            "properties": {
                "budget_items": {
                    "type": "string",
                    "description": "JSON string con los rubros del presupuesto: [{rubro, monto, actividad_vinculada}]"
                },
                "max_total": {
                    "type": "number",
                    "description": "Monto máximo permitido por la convocatoria"
                },
                "admin_cap_percent": {
                    "type": "number",
                    "description": "Porcentaje máximo permitido para gastos administrativos"
                },
                "project_id": {
                    "type": "string",
                    "description": "ID del proyecto para guardar el presupuesto validado"
                }
            },
            "required": ["budget_items", "max_total", "admin_cap_percent", "project_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "generate_word_document",
        "description": "Genera un documento Word (.docx) profesional con toda la información del proyecto y lo almacena en PostgreSQL. Usa el parámetro 'content' para pasar el contenido completo del proyecto en markdown.",
        "parameters": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "ID del proyecto a exportar"
                },
                "language": {
                    "type": "string",
                    "description": "Idioma del documento: 'es' para español, 'en' para inglés",
                    "enum": ["es", "en"]
                },
                "content": {
                    "type": ["string", "null"],
                    "description": "Contenido completo del proyecto en formato markdown. Si se proporciona, genera el Word a partir de este texto. Si es null, usa los datos estructurados del proyecto en la base de datos."
                }
            },
            "required": ["project_id", "language", "content"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "run_diagnostic",
        "description": "Ejecuta el diagnóstico Cyrano para evaluar la calidad del proyecto. Asigna puntajes por sección y retorna feedback de mejora si el puntaje es < 95.01.",
        "parameters": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "ID del proyecto a diagnosticar"
                }
            },
            "required": ["project_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "save_project_data",
        "description": "Guarda los datos del proyecto en PostgreSQL. Crea un nuevo proyecto o actualiza uno existente. DEBE usarse para persistir el contenido del proyecto antes de generar el documento Word.",
        "parameters": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": ["string", "null"],
                    "description": "ID del proyecto existente para actualizar. Usar null para crear un proyecto nuevo."
                },
                "user_id": {
                    "type": "string",
                    "description": "ID del usuario propietario (del session_context)"
                },
                "title": {
                    "type": "string",
                    "description": "Título del proyecto"
                },
                "problem_definition": {
                    "type": ["string", "null"],
                    "description": "Texto de la definición del problema"
                },
                "objectives": {
                    "type": ["string", "null"],
                    "description": "Texto de los objetivos (general y específicos)"
                },
                "methodology": {
                    "type": ["string", "null"],
                    "description": "Descripción de la metodología, cadena de valor y actividades"
                },
                "timeline_text": {
                    "type": ["string", "null"],
                    "description": "Texto del cronograma"
                },
                "budget_text": {
                    "type": ["string", "null"],
                    "description": "Texto del presupuesto detallado"
                },
                "full_content": {
                    "type": ["string", "null"],
                    "description": "Contenido completo del proyecto en formato markdown (todas las secciones consolidadas)"
                }
            },
            "required": ["project_id", "user_id", "title", "problem_definition", "objectives", "methodology", "timeline_text", "budget_text", "full_content"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "save_to_project_memory",
        "description": "Guarda un resumen del proyecto completado en el Vector Store de memoria de proyectos para conocimiento acumulado. Usar después de generar el documento Word final.",
        "parameters": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "ID del proyecto a guardar en memoria"
                },
                "summary": {
                    "type": "string",
                    "description": "Resumen ejecutivo del proyecto completado para memoria de conocimiento. Incluir: título, problema, objetivos, resultados clave, presupuesto, lecciones aprendidas."
                }
            },
            "required": ["project_id", "summary"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "save_diagnostic_result",
        "description": (
            "Persiste el resultado estructurado del diagnóstico Cyrano en la base de datos. "
            "DEBE llamarse SIEMPRE después de run_diagnostic, con los puntajes exactos por sección, "
            "el puntaje ponderado total, la lista de brechas y el veredicto. "
            "Retorna el ID de la evaluación guardada y el número de versión."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "ID del proyecto evaluado",
                },
                "score": {
                    "type": "number",
                    "description": "Puntaje total ponderado (0–100)",
                },
                "sections": {
                    "type": "object",
                    "description": (
                        "Puntaje de 1 a 10 por cada sección. Claves esperadas: "
                        "problem_definition, problem_tree, objectives, value_chain, timeline, budget"
                    ),
                    "properties": {
                        "problem_definition": {"type": "number"},
                        "problem_tree": {"type": "number"},
                        "objectives": {"type": "number"},
                        "value_chain": {"type": "number"},
                        "timeline": {"type": "number"},
                        "budget": {"type": "number"},
                    },
                    "required": [
                        "problem_definition",
                        "problem_tree",
                        "objectives",
                        "value_chain",
                        "timeline",
                        "budget",
                    ],
                    "additionalProperties": False,
                },
                "gaps": {
                    "type": "array",
                    "description": "Lista de brechas identificadas, cada una como string descriptivo",
                    "items": {"type": "string"},
                },
                "recommendations": {
                    "type": "array",
                    "description": "Lista de recomendaciones priorizadas por impacto en el puntaje",
                    "items": {"type": "string"},
                },
                "verdict": {
                    "type": "string",
                    "description": "APROBADO si score >= 95.01, EN REVISIÓN si score < 95.01",
                    "enum": ["APROBADO", "EN REVISIÓN"],
                },
            },
            "required": [
                "project_id",
                "score",
                "sections",
                "gaps",
                "recommendations",
                "verdict",
            ],
            "additionalProperties": False,
        },
        "strict": True,
    },
]

async def handle_search_funding_calls(args: dict) -> str:
    """Execute real web search for active funding calls using OpenAI web_search_preview."""
    sector = args["sector"]
    territory = args["territory"]
    keywords = args.get("keywords", "")

    _settings = get_settings()
    _client = AsyncOpenAI(api_key=_settings.OPENAI_API_KEY)

    search_prompt = (
        f"Busca convocatorias de financiamiento ABIERTAS y ACTIVAS para proyectos de "
        f"{sector} en {territory}."
    )
    if keywords:
        search_prompt += f" Palabras clave adicionales: {keywords}."
    search_prompt += (
        " Para cada convocatoria encontrada, incluye: nombre de la convocatoria, "
        "organización que la publica, fecha límite de aplicación, "
        "enlace/URL oficial completo (formato markdown: [texto](url)), "
        "monto disponible y requisitos principales. "
        "IMPORTANTE: Siempre incluye los enlaces/URLs como links en formato markdown. "
        "Solo incluye convocatorias actualmente vigentes. "
        "Responde en formato estructurado."
    )

    try:
        response = await _client.responses.create(
            model=_settings.OPENAI_MODEL,
            tools=[{"type": "web_search_preview"}],
            input=search_prompt,
        )

        # Extract text from the response
        text_parts = []
        for item in response.output:
            if item.type == "message":
                for content in item.content:
                    if content.type == "output_text":
                        text_parts.append(content.text)

        result_text = "\n".join(text_parts) if text_parts else None

        if not result_text:
            return json.dumps({
                "status": "no_results",
                "source": "web_search",
                "message": f"No se encontraron convocatorias vigentes para sector '{sector}' en '{territory}'.",
            })

        return json.dumps({
            "status": "success",
            "source": "web_search",
            "results": result_text,
        })
    except Exception as e:
        return json.dumps({
            "status": "error",
            "source": "web_search",
            "message": f"Error al buscar convocatorias en la web: {str(e)}",
        })


async def handle_extract_requirements(args: dict) -> str:
    """Extract structured requirements from a call document using LLM.

    Calls EXTRACT_REQUIREMENTS_PROMPT with the document text, parses the
    structured JSON response, and persists the result in the call_specs table.
    Returns the extracted data so the AI can use it in the conversation.
    """
    document_text = args["document_text"]
    call_spec_id = args.get("call_spec_id")
    title = args.get("title", "Convocatoria")

    _settings = get_settings()
    _client = AsyncOpenAI(api_key=_settings.OPENAI_API_KEY)

    prompt = f"{EXTRACT_REQUIREMENTS_PROMPT}\n\n<document>\n{document_text}\n</document>"

    try:
        response = await _client.responses.create(
            model=_settings.OPENAI_MODEL,
            input=prompt,
        )

        text_parts = []
        for item in response.output:
            if item.type == "message":
                for content in item.content:
                    if content.type == "output_text":
                        text_parts.append(content.text)
        raw_response = "\n".join(text_parts)

        # Parse JSON from response — handle optional ```json ... ``` fences
        extracted: dict = {}
        try:
            json_match = re.search(r"```json\s*(.*?)\s*```", raw_response, re.DOTALL)
            if json_match:
                extracted = json.loads(json_match.group(1))
            else:
                extracted = json.loads(raw_response)
        except (json.JSONDecodeError, ValueError):
            extracted = {"raw_extraction": raw_response}

        def _save_to_db() -> str:
            db = SessionLocal()
            try:
                # Helper: safely truncate extracted strings for varchar columns
                def _str(val: object, limit: int = 250) -> str | None:
                    s = str(val).strip() if val else None
                    return s[:limit] if s else None

                if call_spec_id:
                    spec = db.query(CallSpec).filter(
                        CallSpec.id == uuid.UUID(call_spec_id)
                    ).first()
                    if spec:
                        spec.extracted_requirements = extracted
                        spec.eligibility_criteria = _str(extracted.get("criterios_elegibilidad"), 2000)
                        spec.max_amount = _str(extracted.get("montos_maximos"))
                        spec.counterpart_required = _str(extracted.get("contrapartidas_requeridas"))
                        spec.deadline = _str(extracted.get("fechas_cierre"))
                        spec.mandatory_sections = extracted.get("secciones_obligatorias")
                        spec.raw_text = document_text[:10_000]
                        db.commit()
                        return str(spec.id)

                # Create new CallSpec row
                spec = CallSpec(
                    title=title,
                    extracted_requirements=extracted,
                    eligibility_criteria=_str(extracted.get("criterios_elegibilidad"), 2000),
                    max_amount=_str(extracted.get("montos_maximos")),
                    counterpart_required=_str(extracted.get("contrapartidas_requeridas")),
                    deadline=_str(extracted.get("fechas_cierre")),
                    mandatory_sections=extracted.get("secciones_obligatorias"),
                    raw_text=document_text[:10_000],
                )
                db.add(spec)
                db.commit()
                db.refresh(spec)
                return str(spec.id)
            finally:
                db.close()

        saved_id = await asyncio.to_thread(_save_to_db)

        return json.dumps({
            "status": "success",
            "call_spec_id": saved_id,
            "document_length": len(document_text),
            "extracted": extracted,
            "message": "Requisitos extraídos y guardados correctamente en call_specs.",
        })

    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": f"Error al extraer requisitos: {str(e)}",
        })


def handle_calculate_budget(args: dict, db: Session) -> str:
    """Validate budget items against call constraints."""
    try:
        budget_items = json.loads(args["budget_items"])
    except (json.JSONDecodeError, TypeError):
        return json.dumps({"status": "error", "message": "Formato de presupuesto inválido. Debe ser JSON válido."})

    max_total = args["max_total"]
    admin_cap = args["admin_cap_percent"]
    project_id = uuid.UUID(args["project_id"]) if isinstance(args["project_id"], str) else args["project_id"]

    total = sum(item.get("monto", 0) for item in budget_items)
    admin_total = sum(item.get("monto", 0) for item in budget_items if item.get("rubro", "").lower() in ["administrativo", "admin", "gastos administrativos"])
    admin_percent = (admin_total / total * 100) if total > 0 else 0

    issues = []
    if total > max_total:
        issues.append(f"El presupuesto total ({total:,.2f}) excede el máximo permitido ({max_total:,.2f})")
    if admin_percent > admin_cap:
        issues.append(f"Los gastos administrativos ({admin_percent:.1f}%) exceden el tope ({admin_cap}%)")

    # Check for items without linked activities
    unlinked = [item for item in budget_items if not item.get("actividad_vinculada")]
    if unlinked:
        issues.append(f"{len(unlinked)} rubros sin actividad vinculada")

    result = {
        "status": "valid" if not issues else "issues_found",
        "total": total,
        "max_allowed": max_total,
        "admin_percent": round(admin_percent, 1),
        "admin_cap": admin_cap,
        "issues": issues,
        "items_count": len(budget_items),
    }

    # Update project budget if valid
    if not issues:
        project = db.query(Project).filter(Project.id == project_id).first()
        if project:
            project.budget = {"items": budget_items, "total": total, "validated": True}
            db.commit()

    return json.dumps(result)


def handle_generate_word_document(args: dict, db: Session) -> str:
    """Generate a professional Word document for the project."""
    project_id = uuid.UUID(args["project_id"]) if isinstance(args["project_id"], str) else args["project_id"]
    language = args["language"]
    content = args.get("content")

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return json.dumps({"status": "error", "message": "Proyecto no encontrado"})

    # Determine if this is a draft (score < 95.01) or final document
    current_score = project.cyrano_score
    is_draft = current_score is None or current_score < 95.01

    doc = Document()

    # Title
    title_para = doc.add_heading(project.title, level=0)
    title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # Cyrano score badge in the document
    if current_score is not None:
        score_label = "BORRADOR" if is_draft else "DOCUMENTO FINAL"
        score_text = f"Puntaje Cyrano: {current_score:.1f}/100 — {score_label}"
    else:
        score_text = "Puntaje Cyrano: Sin evaluar — BORRADOR"
    score_para = doc.add_paragraph(score_text)
    score_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in score_para.runs:
        run.bold = True

    # Metadata
    doc.add_paragraph(f"{'Idioma' if language == 'es' else 'Language'}: {'Español' if language == 'es' else 'English'}")
    doc.add_paragraph(f"{'Estado' if language == 'es' else 'Status'}: {project.status}")

    if content:
        # Generate from markdown content provided by the AI
        _markdown_to_docx(doc, content)
    else:
        # Generate from structured data in the project model
        _generate_structured_doc(doc, project, language)

    # Save to buffer
    buffer = BytesIO()
    doc.save(buffer)
    doc_bytes = buffer.getvalue()

    # Upsert: update existing document or create new one
    safe_title = project.title.replace(' ', '_')[:80]
    filename = f"{safe_title}.docx"

    existing = (
        db.query(GeneratedDoc)
        .filter(GeneratedDoc.project_id == project_id, GeneratedDoc.filename == filename)
        .first()
    )

    # Write to object storage; fall back to inline binary on failure
    storage_path: str | None = None
    try:
        from app.services.storage import get_storage, make_generated_doc_key
        storage = get_storage()
        key = make_generated_doc_key(str(project_id), filename)
        storage.save(key, doc_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        storage_path = key
    except Exception as exc:
        import logging as _logging
        _logging.getLogger(__name__).error("generated_doc_storage_failed", extra={"error": str(exc)})

    if existing:
        existing.binary_file = None if storage_path else doc_bytes
        existing.storage_path = storage_path
        generated_doc = existing
    else:
        generated_doc = GeneratedDoc(
            project_id=project_id,
            filename=filename,
            binary_file=None if storage_path else doc_bytes,
            storage_path=storage_path,
            version_number=1,
        )
        db.add(generated_doc)
    db.commit()
    db.refresh(generated_doc)

    doc_type = "borrador" if is_draft else "documento final"
    score_msg = f" (Puntaje Cyrano: {current_score:.1f}/100)" if current_score is not None else ""

    return json.dumps({
        "status": "success",
        "document_id": str(generated_doc.id),
        "filename": filename,
        "download_url": f"/api/documents/{str(generated_doc.id)}/download",
        "is_draft": is_draft,
        "cyrano_score": current_score,
        "message": f"Documento '{filename}' generado como {doc_type}{score_msg}. Enlace de descarga: /api/documents/{str(generated_doc.id)}/download",
    })


def handle_run_diagnostic(args: dict, db: Session) -> str:
    """Run the Cyrano diagnostic on a project."""
    project_id = uuid.UUID(args["project_id"]) if isinstance(args["project_id"], str) else args["project_id"]

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return json.dumps({"status": "error", "message": "Proyecto no encontrado"})

    # Guard: refuse to evaluate a project with no content
    campos_con_datos = [
        project.problem_definition,
        project.problem_tree,
        project.objectives_tree,
        project.value_chain,
        project.timeline,
        project.budget,
    ]
    tiene_full_content = bool(
        project.json_data and project.json_data.get("full_content")
    )
    if not any(campos_con_datos) and not tiene_full_content:
        return json.dumps({
            "status": "error",
            "message": (
                "El proyecto no tiene datos guardados. Llama save_project_data "
                "con el contenido del proyecto antes de ejecutar el diagnóstico."
            ),
        })

    # Collect project data for evaluation
    project_data = {
        "title": project.title,
        "problem_definition": project.problem_definition,
        "problem_tree": project.problem_tree,
        "objectives_tree": project.objectives_tree,
        "value_chain": project.value_chain,
        "timeline": project.timeline,
        "budget": project.budget,
    }

    # Fall back to text-libre versions from json_data when structured fields are
    # absent or are legacy {"text": "..."} wrappers (Fix #6).
    jd = project.json_data or {}

    def _unwrap(val: object) -> object:
        """Return plain text when val is the legacy {"text": "..."} wrapper."""
        if isinstance(val, dict) and list(val.keys()) == ["text"]:
            return val["text"]
        return val

    for struct_key, text_key in (
        ("objectives_tree", "objectives_text"),
        ("value_chain", "methodology_text"),
        ("timeline", "timeline_text"),
        ("budget", "budget_text"),
    ):
        project_data[struct_key] = _unwrap(project_data[struct_key])
        if not project_data[struct_key] and jd.get(text_key):
            project_data[struct_key] = jd[text_key]

    # Include calculate_budget result so the LLM evaluator sees structural issues (Fix #10)
    raw_budget = project.budget
    if isinstance(raw_budget, dict) and ("validated" in raw_budget or "issues" in raw_budget):
        project_data["budget_integrity"] = {
            "validated": raw_budget.get("validated", False),
            "total": raw_budget.get("total"),
            "issues": raw_budget.get("issues", []),
        }
    else:
        project_data["budget_integrity"] = {
            "validated": False,
            "issues": ["calculate_budget no ejecutado para este proyecto"],
        }

    # If structured fields are empty but json_data has full_content, include it
    if project.json_data and project.json_data.get("full_content"):
        project_data["full_content"] = project.json_data["full_content"]

    # Return project data for the LLM to evaluate with the Cyrano prompt
    return json.dumps({
        "status": "ready_for_evaluation",
        "project_data": project_data,
        "evaluation_instructions": (
            "Evalúa cada uno de los 6 pasos con puntaje 1-10 y calcula el promedio simple: "
            "score = (suma de las 6 notas / 6) × 10. "
            "Interpreta: 1-6 Débil, 7-8 Intermedio, 9-10 Sólido. "
            "Identifica brechas específicas y recomendaciones priorizadas. "
            "Veredicto: 'APROBADO — Sólido' si score >= 95.01, "
            "'EN REVISIÓN — Intermedio' si 70 <= score < 95.01, "
            "'EN REVISIÓN — Débil' si score < 70. "
            "OBLIGATORIO: llama save_diagnostic_result con score, sections, gaps, "
            "recommendations y verdict exactos antes de responder al usuario."
        ),
    })


# ──────────────────────────────────────────────
# Document generation helpers
# ──────────────────────────────────────────────

def _add_tree_section(doc: Document, tree_data: dict, lang: str):
    causes_label = "Causas" if lang == "es" else "Causes"
    problem_label = "Problema Central" if lang == "es" else "Central Problem"
    effects_label = "Efectos" if lang == "es" else "Effects"

    if "central_problem" in tree_data:
        doc.add_heading(problem_label, level=2)
        doc.add_paragraph(tree_data["central_problem"])

    if "causes" in tree_data:
        doc.add_heading(causes_label, level=2)
        for i, cause in enumerate(tree_data["causes"], 1):
            doc.add_paragraph(f"{i}. {cause}", style="List Number")

    if "effects" in tree_data:
        doc.add_heading(effects_label, level=2)
        for i, effect in enumerate(tree_data["effects"], 1):
            doc.add_paragraph(f"{i}. {effect}", style="List Number")


def _add_objectives_section(doc: Document, objectives: dict, lang: str):
    general_label = "Objetivo General" if lang == "es" else "General Objective"
    specific_label = "Objetivos Específicos" if lang == "es" else "Specific Objectives"

    if "general" in objectives:
        doc.add_heading(general_label, level=2)
        doc.add_paragraph(objectives["general"])

    if "specific" in objectives:
        doc.add_heading(specific_label, level=2)
        for i, obj in enumerate(objectives["specific"], 1):
            doc.add_paragraph(f"{i}. {obj}", style="List Number")


def _add_value_chain_section(doc: Document, chain: dict, lang: str):
    if "items" in chain:
        table = doc.add_table(rows=1, cols=4)
        table.style = "Table Grid"
        headers = (
            ["Actividad", "Producto", "Indicador", "Meta"] if lang == "es"
            else ["Activity", "Product", "Indicator", "Target"]
        )
        for i, header in enumerate(headers):
            table.rows[0].cells[i].text = header

        for item in chain["items"]:
            row = table.add_row()
            row.cells[0].text = item.get("actividad", item.get("activity", ""))
            row.cells[1].text = item.get("producto", item.get("product", ""))
            row.cells[2].text = item.get("indicador", item.get("indicator", ""))
            row.cells[3].text = item.get("meta", item.get("target", ""))


def _add_timeline_section(doc: Document, timeline: dict, lang: str):
    if "activities" in timeline:
        table = doc.add_table(rows=1, cols=4)
        table.style = "Table Grid"
        headers = (
            ["Actividad", "Inicio", "Fin", "Responsable"] if lang == "es"
            else ["Activity", "Start", "End", "Responsible"]
        )
        for i, header in enumerate(headers):
            table.rows[0].cells[i].text = header

        for act in timeline["activities"]:
            row = table.add_row()
            row.cells[0].text = act.get("actividad", act.get("activity", ""))
            row.cells[1].text = act.get("inicio", act.get("start", ""))
            row.cells[2].text = act.get("fin", act.get("end", ""))
            row.cells[3].text = act.get("responsable", act.get("responsible", ""))


def _add_budget_section(doc: Document, budget: dict, lang: str):
    if "items" in budget:
        table = doc.add_table(rows=1, cols=3)
        table.style = "Table Grid"
        headers = (
            ["Rubro", "Monto", "Actividad Vinculada"] if lang == "es"
            else ["Category", "Amount", "Linked Activity"]
        )
        for i, header in enumerate(headers):
            table.rows[0].cells[i].text = header

        for item in budget["items"]:
            row = table.add_row()
            row.cells[0].text = item.get("rubro", item.get("category", ""))
            row.cells[1].text = f"${item.get('monto', item.get('amount', 0)):,.2f}"
            row.cells[2].text = item.get("actividad_vinculada", item.get("linked_activity", ""))

        # Total row
        total = budget.get("total", sum(i.get("monto", i.get("amount", 0)) for i in budget["items"]))
        total_row = table.add_row()
        total_row.cells[0].text = "TOTAL"
        total_row.cells[1].text = f"${total:,.2f}"
        total_row.cells[2].text = ""


# ──────────────────────────────────────────────
# Structured document generation
# ──────────────────────────────────────────────

def _generate_structured_doc(doc, project, language: str):
    """Generate Word document sections from structured project data."""
    sec_titles = {
        "es": {
            "problem": "1. Identificación del Problema",
            "problem_tree": "2. Árbol de Problemas",
            "objectives": "3. Objetivos",
            "value_chain": "4. Cadena de Valor",
            "timeline": "5. Cronograma",
            "budget": "6. Presupuesto",
        },
        "en": {
            "problem": "1. Problem Identification",
            "problem_tree": "2. Problem Tree",
            "objectives": "3. Objectives",
            "value_chain": "4. Value Chain",
            "timeline": "5. Timeline",
            "budget": "6. Budget",
        }
    }
    titles = sec_titles.get(language, sec_titles["es"])

    doc.add_heading(titles["problem"], level=1)
    doc.add_paragraph(project.problem_definition or "Por definir")

    doc.add_heading(titles["problem_tree"], level=1)
    if project.problem_tree:
        _add_tree_section(doc, project.problem_tree, language)
    else:
        doc.add_paragraph("Por definir")

    doc.add_heading(titles["objectives"], level=1)
    if project.objectives_tree:
        _add_objectives_section(doc, project.objectives_tree, language)
    else:
        doc.add_paragraph("Por definir")

    doc.add_heading(titles["value_chain"], level=1)
    if project.value_chain:
        _add_value_chain_section(doc, project.value_chain, language)
    else:
        doc.add_paragraph("Por definir")

    doc.add_heading(titles["timeline"], level=1)
    if project.timeline:
        _add_timeline_section(doc, project.timeline, language)
    else:
        doc.add_paragraph("Por definir")

    doc.add_heading(titles["budget"], level=1)
    if project.budget:
        _add_budget_section(doc, project.budget, language)
    else:
        doc.add_paragraph("Por definir")


# ──────────────────────────────────────────────
# Markdown to Word conversion
# ──────────────────────────────────────────────

def _markdown_to_docx(doc, markdown_text: str):
    """Convert markdown text to Word document content."""
    lines = markdown_text.split('\n')

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Headings
        heading_match = re.match(r'^(#{1,3})\s+(.+)$', stripped)
        if heading_match:
            level = len(heading_match.group(1))
            doc.add_heading(heading_match.group(2), level=level)
            continue

        # Bullet list
        if stripped.startswith(('- ', '• ', '* ')):
            text = stripped[2:]
            p = doc.add_paragraph(style='List Bullet')
            _add_formatted_text(p, text)
            continue

        # Numbered list
        num_match = re.match(r'^(\d+)[\.\)]\s+(.+)$', stripped)
        if num_match:
            p = doc.add_paragraph(style='List Number')
            _add_formatted_text(p, num_match.group(2))
            continue

        # Regular paragraph with inline formatting
        p = doc.add_paragraph()
        _add_formatted_text(p, stripped)


def _add_formatted_text(paragraph, text: str):
    """Add text with bold formatting to a paragraph."""
    parts = re.split(r'(\*\*.*?\*\*)', text)
    for part in parts:
        if part.startswith('**') and part.endswith('**'):
            run = paragraph.add_run(part[2:-2])
            run.bold = True
        else:
            paragraph.add_run(part)


# ──────────────────────────────────────────────
# Project data persistence handlers
# ──────────────────────────────────────────────

def handle_save_project_data(args: dict, db: Session) -> str:
    """Save project data to PostgreSQL. Creates a new project or updates an existing one."""
    project_id_str = args.get("project_id")
    user_id = args.get("user_id")
    title = args.get("title") or "Proyecto sin título"

    if project_id_str:
        project = db.query(Project).filter(
            Project.id == uuid.UUID(project_id_str)
        ).first()
        if not project:
            return json.dumps({"status": "error", "message": "Proyecto no encontrado"})
        # Keep existing title if none provided
        if args.get("title"):
            project.title = title
    else:
        if not user_id:
            return json.dumps({"status": "error", "message": "user_id requerido para crear un proyecto nuevo"})
        project = Project(user_id=uuid.UUID(user_id), title=title)
        db.add(project)
        db.flush()
        project.title = title

    if args.get("problem_definition"):
        project.problem_definition = args["problem_definition"]

    # Text-libre fields are saved in json_data, NOT in the structured JSON columns.
    # Structured columns (objectives_tree, value_chain, timeline, budget) are only
    # updated by tools that produce properly-shaped dicts (e.g. calculate_budget).
    # Wrapping plain text as {"text": "..."} in those columns caused the Cyrano
    # evaluator to receive malformed data — Fix #6.
    json_data: dict = dict(project.json_data or {})
    if args.get("objectives"):
        json_data["objectives_text"] = args["objectives"]
    if args.get("methodology"):
        json_data["methodology_text"] = args["methodology"]
    if args.get("timeline_text"):
        json_data["timeline_text"] = args["timeline_text"]
    if args.get("budget_text"):
        json_data["budget_text"] = args["budget_text"]
    if args.get("full_content"):
        json_data["full_content"] = args["full_content"]
    if json_data:
        project.json_data = json_data

    project.status = ProjectStatus.in_progress
    db.commit()

    return json.dumps({
        "status": "success",
        "project_id": str(project.id),
        "message": f"Proyecto '{title}' guardado exitosamente en la base de datos.",
    })


def handle_save_to_project_memory(args: dict, db: Session) -> str:
    """Upload project summary to the projects vector store for accumulated knowledge."""
    project_id = uuid.UUID(args["project_id"])
    summary = args["summary"]

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return json.dumps({"status": "error", "message": "Proyecto no encontrado"})

    _settings = get_settings()
    _client = OpenAI(api_key=_settings.OPENAI_API_KEY)

    # Build content for the vector store
    content = f"# Proyecto: {project.title}\n\n{summary}"

    try:
        # Upload file to OpenAI
        file_buffer = BytesIO(content.encode('utf-8'))
        file_buffer.name = f"proyecto_{project.title.replace(' ', '_')[:50]}.md"

        uploaded_file = _client.files.create(
            file=file_buffer,
            purpose="assistants",
        )

        # Add to projects vector store (tag with project_id for scoped retrieval)
        _client.vector_stores.files.create(
            vector_store_id=_settings.OPENAI_PROJECTS_VECTOR_STORE_ID,
            file_id=uploaded_file.id,
            attributes={"project_id": str(project_id)},
        )

        project.status = ProjectStatus.completed
        db.commit()

        return json.dumps({
            "status": "success",
            "message": f"Proyecto '{project.title}' guardado en memoria de proyectos para referencia futura.",
            "file_id": uploaded_file.id,
        })
    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": f"Error al guardar en memoria de proyectos: {str(e)}",
        })


def handle_save_diagnostic_result(args: dict, db: Session) -> str:
    """Persist a structured Cyrano evaluation and update project.cyrano_score.

    Called by the LLM right after running the diagnostic so the score is
    stored as structured data instead of being extracted with regex.

    The score is always recalculated server-side from the section notes
    (simple average of the 6 steps × 10) to prevent LLM arithmetic errors.
    """
    project_id = uuid.UUID(args["project_id"])

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return json.dumps({"status": "error", "message": "Proyecto no encontrado"})

    # --- Recalculate score server-side (simple average, as per the manual) ---
    _SECTIONS = [
        "problem_definition",
        "problem_tree",
        "objectives",
        "value_chain",
        "timeline",
        "budget",
    ]
    sections = args.get("sections") or {}

    # Cap budget note when calculate_budget reported structural issues (Fix #10)
    if "budget" in sections and sections["budget"] is not None:
        budget_data = project.budget if isinstance(project.budget, dict) else {}
        if budget_data.get("issues"):
            sections["budget"] = min(float(sections["budget"]), 5.0)

    valid_notes = [
        float(sections[k])
        for k in _SECTIONS
        if k in sections and sections[k] is not None
    ]
    if valid_notes:
        calculated_score = round((sum(valid_notes) / len(valid_notes)) * 10, 2)
    else:
        # Fall back to LLM-provided score only when no section data is present
        calculated_score = round(float(args.get("score", 0)), 2)

    # Enforce verdict label from the Cyrano rubric bands
    if calculated_score >= 95.01:
        verdict = "APROBADO — Sólido"
    elif calculated_score >= 70:
        verdict = "EN REVISIÓN — Intermedio"
    else:
        verdict = "EN REVISIÓN — Débil"

    score = calculated_score

    # Determine next version number for this project
    existing_count = (
        db.query(CyranoEvaluation)
        .filter(CyranoEvaluation.project_id == project_id)
        .count()
    )
    version = existing_count + 1

    evaluation = CyranoEvaluation(
        project_id=project_id,
        score=score,
        sections=sections if sections else args.get("sections"),
        feedback={
            "gaps": args.get("gaps", []),
            "recommendations": args.get("recommendations", []),
        },
        verdict=verdict,
        version=version,
    )
    db.add(evaluation)

    # Keep project.cyrano_score in sync
    project.cyrano_score = score
    db.commit()
    db.refresh(evaluation)

    return json.dumps({
        "status": "success",
        "evaluation_id": str(evaluation.id),
        "version": version,
        "score": score,
        "verdict": verdict,
        "message": (
            f"Diagnóstico Cyrano v{version} persistido. "
            f"Puntaje: {score:.1f}/100 — {verdict}"
        ),
    })
