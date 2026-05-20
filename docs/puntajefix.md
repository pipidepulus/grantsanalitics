# Fix Plan: Flujo del Puntaje Cyrano

Problemas identificados en el flujo de evaluación, ordenados de mayor a menor impacto.
Implementar en orden. Marcar con ✅ cuando esté hecho.

---

## ❓ Pregunta frecuente: ¿El puntaje sólo se emite cuando es ≥ 95.01?

**No.** El puntaje se calcula y persiste en **cada llamada a `run_diagnostic`**, sin importar
el valor resultante. El umbral 95.01 sólo controla:

- Si el veredicto es `"APROBADO"` o `"EN REVISIÓN"`.
- Si `project.status` debería pasar a `"validated"` (Fix #3 — actualmente no lo hace).
- Si el documento Word se genera como "borrador" o "documento final".

**El problema real** no es la emisión del puntaje total — ese ya se guarda siempre.
El problema es que **los puntajes por sección** (que el LLM envía en `save_diagnostic_result.sections`)
están persistidos en `cyrano_evaluations.sections` y el endpoint `GET /projects/{id}/evaluations`
los expone completos, pero el **`ReviewPanel` nunca los muestra**. El usuario ve sólo el número
total y nunca sabe en qué secciones está fallando ni cuánto vale cada una.
Esto se resuelve en el **Fix #9** de este documento.

---

## 📊 Rúbrica Cyrano: Especificación del Manual vs. Código Actual

### ✅ Especificación del Manual (fuente de verdad)

> "Asigna puntajes **1–10** a cada paso y **promedia**."  
> Interpreta: **1–6 Débil · 7–8 Intermedio · 9–10 Sólido**

Esto implica **promedio simple** — los 6 pasos valen exactamente lo mismo.

| Sección | Clave interna (`sections.*`) | Peso correcto | Pts máx. |
|---------|------------------------------|---------------|----------|
| Identificación del Problema | `problem_definition` | 1/6 ≈ 16.67% | 16.67 |
| Árbol de Problemas | `problem_tree` | 1/6 ≈ 16.67% | 16.67 |
| Objetivos SMART | `objectives` | 1/6 ≈ 16.67% | 16.67 |
| Cadena de Valor | `value_chain` | 1/6 ≈ 16.67% | 16.67 |
| Cronograma | `timeline` | 1/6 ≈ 16.67% | 16.67 |
| Presupuesto | `budget` | 1/6 ≈ 16.67% | 16.67 |
| **TOTAL** | | **100%** | **100 pts** |

**Fórmula correcta:**
```
score = ((problem_definition + problem_tree + objectives
        + value_chain + timeline + budget) / 6) × 10
```

**Bandas de interpretación** (sobre escala 0–100):

| Nota 1-10 | Score 0-100 | Etiqueta del manual | Color en frontend hoy |
|-----------|-------------|---------------------|-----------------------|
| 1–6 | 10–60 | **Débil** | 🔴 rojo (`< 80`) |
| 7–8 | 70–80 | **Intermedio** | 🟡 amarillo (`80–95`) |
| 9–10 | 90–100 | **Sólido** | 🟢 verde (`≥ 95.01`) |

> **Nota:** El threshold 95.01 equivale a nota ~9.5/10 — límite alto del rango "Sólido". Es coherente.

---

### ⚠️ Discrepancia: el código usa pesos desiguales en vez de promedio simple

`CYRANO_DIAGNOSTIC_PROMPT` en `prompts.py` define pesos distintos:

| Sección | Peso en código | Peso correcto (manual) | Diferencia |
|---------|---------------|------------------------|------------|
| problem_definition | 15% | 16.67% | −1.67% |
| problem_tree | 15% | 16.67% | −1.67% |
| objectives | 15% | 16.67% | −1.67% |
| **value_chain** | **20%** | 16.67% | **+3.33%** |
| timeline | 15% | 16.67% | −1.67% |
| **budget** | **20%** | 16.67% | **+3.33%** |

Valor/Cadena y Presupuesto tienen un 3.33% extra cada uno. Esto penaliza proyectos
fuertes en formulación pero con presupuesto incompleto — puede no ser la intención.
**Este error está embebido en el prompt y en la fórmula del Fix #4.**

---

### ❌ Etiquetas de interpretación ausentes en todo el código

Las etiquetas **"Débil / Intermedio / Sólido"** del manual no aparecen en ningún lugar:
- `CYRANO_DIAGNOSTIC_PROMPT` — solo pide `"APROBADO"` o `"EN REVISIÓN"` como veredicto
- `ReviewPanel.tsx` — muestra colores rojo/amarillo/verde pero **sin texto de etiqueta**
- `Sidebar.tsx` — muestra el número puro (ej. `87.5`)
- `handle_save_diagnostic_result` — guarda el `verdict` textual enviado por el LLM pero no hay regla

Esto se corrige en el **Fix #8** (ReviewPanel) y en el **Fix #1** (actualizar el prompt).

---

## #1 ✅ ~~`CYRANO_DIAGNOSTIC_PROMPT` definido pero nunca usado~~ — FIXED

**Archivo:** `backend/app/core/prompts.py` + `backend/app/services/ai_agent.py`

**Qué pasa hoy:**
En `prompts.py` existe un prompt completo con la rúbrica exacta de evaluación Cyrano
(pesos por sección, criterios por subsección, formato de respuesta). Sin embargo, ese
prompt **nunca se importa ni se usa en ningún lugar**. Cuando el LLM evalúa el proyecto,
solo ve las instrucciones cortas que `handle_run_diagnostic` mete dentro del JSON de la
respuesta de herramienta. Eso es mucho menos preciso que el prompt dedicado.

**Qué hay que hacer:**
- En `ai_agent.py`, importar `CYRANO_DIAGNOSTIC_PROMPT` desde `prompts.py`.
- Dentro del loop `_process_response`, detectar cuándo `run_diagnostic` acaba de
  retornar su resultado.
- Inyectar `CYRANO_DIAGNOSTIC_PROMPT` como un mensaje adicional de sistema en ese
  punto del loop, antes de que el LLM procese el resultado y calcule el puntaje.
- **Corregir los pesos en `CYRANO_DIAGNOSTIC_PROMPT`**: reemplazar los pesos desiguales
  (15%/15%/15%/20%/15%/20%) por promedio simple (todos 1/6 ≈ 16.67%), según el manual.
- **Agregar las etiquetas de interpretación** al prompt:
  ```
  Interpreta la nota promedio (1-10):
  - 1–6: Débil   → score 10–60  → EN REVISIÓN
  - 7–8: Intermedio → score 70–80 → EN REVISIÓN
  - 9–10 (≥9.501): Sólido → score 95.01–100 → APROBADO
  ```
  e incluir la etiqueta (Débil / Intermedio / Sólido) en el campo `verdict` del resultado.

**Impacto si no se hace:**
El LLM evalúa con instrucciones incompletas → puntajes inconsistentes entre sesiones,
evaluaciones que no respetan los pesos exactos por sección.

---

## #2 ✅ ~~Diagnóstico sobre proyecto vacío retorna puntaje arbitrario~~ — FIXED

**Archivo:** `backend/app/services/tools.py` → función `handle_run_diagnostic`

**Qué pasa hoy:**
`handle_run_diagnostic` lee los campos estructurados del proyecto
(`problem_definition`, `problem_tree`, `objectives_tree`, etc.) y los manda al LLM
para que los evalúe. Si el AI no llamó antes a `save_project_data` en esa sesión,
todos esos campos son `None` en la base de datos. El diagnóstico igual procede y el LLM
evalúa campos vacíos, pudiendo retornar puntajes entre 10 y 30 sobre un proyecto que
técnicamente no tiene contenido guardado.

**Qué hay que hacer:**
Agregar validación al inicio de `handle_run_diagnostic`:

```python
campos_con_datos = [
    project.problem_definition,
    project.problem_tree,
    project.objectives_tree,
    project.value_chain,
    project.timeline,
    project.budget,
]
tiene_full_content = project.json_data and project.json_data.get("full_content")

if not any(campos_con_datos) and not tiene_full_content:
    return json.dumps({
        "status": "error",
        "message": (
            "El proyecto no tiene datos guardados. Llama save_project_data "
            "con el contenido del proyecto antes de ejecutar el diagnóstico."
        )
    })
```

**Impacto si no se hace:**
Puntajes de 0-30 sobre proyectos vacíos que confunden al usuario y contaminan
el historial de evaluaciones en `cyrano_evaluations`.

---

## #3 ✅ ~~El `project.status` nunca llega a "validated" automáticamente~~ — FIXED

**Archivo:** `backend/app/services/diagnostic.py` → función `persist_cyrano_score`

**Qué pasa hoy:**
`persist_cyrano_score` actualiza `project.cyrano_score` pero deja intacto
`project.status`. Cuando el puntaje supera 95.01, el proyecto sigue figurando como
`"in_progress"` o `"draft"` en el sidebar. El usuario ve el número verde pero el
estado textual no cambia. Para que el estado llegue a `"validated"` el LLM tendría que
llamar `save_project_data` con el status correcto, pero no está instruido para hacerlo
automáticamente en ese momento.

**Qué hay que hacer:**
En `persist_cyrano_score`, después de asignar el score, agregar:

```python
from app.models.enums import ProjectStatus

project.cyrano_score = cyrano_score

if cyrano_score >= 95.01 and project.status not in (
    ProjectStatus.validated.value, ProjectStatus.exported.value
):
    project.status = ProjectStatus.validated.value
elif cyrano_score < 95.01 and project.status == ProjectStatus.draft.value:
    project.status = ProjectStatus.in_progress.value

db.commit()
```

**Impacto si no se hace:**
La etiqueta de estado en el sidebar nunca muestra "Validado" aunque el puntaje
sea ≥ 95.01, generando confusión sobre si el proyecto está listo para exportar.

---

## #4 ✅ ~~El score enviado por el LLM no se verifica matemáticamente~~ — FIXED

**Archivo:** `backend/app/services/tools.py` → función `handle_save_diagnostic_result`

**Qué pasa hoy:**
El LLM envía `score=97` en `save_diagnostic_result` junto con los puntajes
individuales de cada sección (ej: problem_definition=9, problem_tree=8, etc.).
El backend guarda el `score` tal cual lo mandó el LLM, sin verificar que sea
matemáticamente correcto según los pesos definidos. Un LLM puede reportar
`score=92` con secciones que en realidad sumen 87, y ese 92 incorrecto se persiste.

**Pesos correctos (promedio simple — según el manual):**
- Todas las secciones: 1/6 ≈ 16.67% cada una

**Qué hay que hacer:**
En `handle_save_diagnostic_result`, calcular el score en el servidor usando promedio simple
y reemplazar el que mandó el LLM:

```python
SECTIONS = [
    "problem_definition",
    "problem_tree",
    "objectives",
    "value_chain",
    "timeline",
    "budget",
]

sections = args["sections"]
valid_scores = [sections[k] for k in SECTIONS if k in sections and sections[k] is not None]
if valid_scores:
    calculated_score = round((sum(valid_scores) / len(valid_scores)) * 10, 2)
else:
    calculated_score = 0.0
# Reemplazar el score que mandó el LLM
args["score"] = calculated_score
```

También actualizar el veredicto según las bandas del manual:
```python
if calculated_score >= 95.01:
    interpretation = "Sólido"
    verdict = "APROBADO"
elif calculated_score >= 70:
    interpretation = "Intermedio"
    verdict = "EN REVISIÓN"
else:
    interpretation = "Débil"
    verdict = "EN REVISIÓN"
args["verdict"] = f"{verdict} — {interpretation}"
```

**Impacto si no se hace:**
El puntaje almacenado puede no reflejar la rúbrica real. El umbral 95.01 se evalúa
sobre un número potencialmente incorrecto.

---

## #5 ✅ ~~`handle_extract_requirements` es un stub vacío~~ — FIXED

**Archivo:** `backend/app/services/tools.py` → función `handle_extract_requirements`
**Archivo relacionado:** `backend/app/core/prompts.py` → `EXTRACT_REQUIREMENTS_PROMPT`

**Qué pasaba:**
La función recibía el texto del documento pero no hacía nada con él. Solo retornaba
`{"status": "ready", "document_length": ...}`. El prompt `EXTRACT_REQUIREMENTS_PROMPT`
estaba completamente implementado en `prompts.py` pero nunca se llamaba. Los requisitos
de la convocatoria (fechas, montos máximos, criterios de elegibilidad) no se persistían
en la tabla `call_specs`. Cada vez que el AI mencionaba datos de la convocatoria, los
inventaba desde el contexto de la conversación sin fuente estructurada.

**Qué se hizo:**
- Convertida a función `async` (igual que `handle_search_funding_calls`) para poder
  llamar al LLM con `await _client.responses.create(...)`.
- Importados `asyncio`, `SessionLocal` y `EXTRACT_REQUIREMENTS_PROMPT` en `tools.py`.
- La función llama al LLM con `EXTRACT_REQUIREMENTS_PROMPT` + `<document>` y parsea
  la respuesta JSON (con soporte para bloques ` ```json ``` `).
- Si `call_spec_id` se recibe, actualiza la fila existente en `call_specs`.
- Si no, crea una fila nueva con todos los campos extraídos:
  `eligibility_criteria`, `max_amount`, `counterpart_required`, `deadline`,
  `mandatory_sections`, `raw_text` (primeros 10 000 chars), `extracted_requirements`.
- Retorna `{"status": "success", "call_spec_id": ..., "extracted": {...}}` para que
  el LLM pueda usar los datos extraídos en la conversación.
- La persistencia en DB se ejecuta con `asyncio.to_thread(_save_to_db)` para no
  bloquear el event loop.

**Impacto:**
La herramienta `calculate_budget` ahora puede recibir `max_amount` real de la
convocatoria desde la base de datos en vez de datos dictados por el usuario en el chat.

---

## #6 ✅ ~~`save_project_data` mezcla representaciones y rompe el esquema esperado~~ — FIXED

**Archivo:** `backend/app/services/tools.py` → funciones `handle_save_project_data` y `handle_run_diagnostic`

**Qué pasaba:**
Cuando el AI mandaba `objectives="Objetivo general: X. Objetivos específicos: 1. Y 2. Z"`,
el handler lo guardaba como `project.objectives_tree = {"text": "Objetivo general: X..."}`.
Pero `handle_run_diagnostic` mandaba ese campo al evaluador esperando
`{"general": "...", "specific": [...]}`. Mismo problema con `methodology` → `value_chain`,
`timeline_text` → `timeline`, `budget_text` → `budget`.
Además, `calculate_budget` sobreescribía `project.budget` con la estructura correcta
`{"items": [...], "total": ..., "validated": True}`, pero un `save_project_data`
posterior lo volvía a destruir con `{"text": "presupuesto: $X..."}`.

**Qué se hizo:**

**En `handle_save_project_data`:**
- Eliminados los 4 bloques `project.<campo> = {"text": args["..."]}`.
- Los campos de texto libre (`objectives`, `methodology`, `timeline_text`, `budget_text`)
  se guardan en `project.json_data` bajo claves propias:
  `objectives_text`, `methodology_text`, `timeline_text`, `budget_text`.
- `project.json_data` se construye como merge del dict existente (no se sobreescribe),
  por lo que `calculate_budget` puede seguir guardando `project.budget` sin riesgo.
- Las columnas estructuradas (`objectives_tree`, `value_chain`, `timeline`, `budget`)
  solo se actualizan por herramientas que producen dicts con la forma correcta.

**En `handle_run_diagnostic`:**
- Agregada función helper `_unwrap(val)` que detecta y desempaqueta wrappers
  legados `{"text": "..."}` (datos existentes en la DB antes del fix).
- Para cada par `(structured_key, text_key)`, se normaliza el valor:
  - Si es un wrapper legado → se extrae el texto plano.
  - Si el campo estructurado está vacío → se lee el texto libre desde `json_data`.
- El evaluador recibe siempre el mejor dato disponible, en lugar de `None` o un dict malformado.

---

## #7 ✅ ~~Regex de fallback puede capturar números equivocados~~ — FIXED

**Archivo:** `backend/app/services/diagnostic.py` → función `extract_cyrano_score`

**Qué pasaba:**
El patrón `(\d+(?:\.\d+)?)\s*puntos` podría coincidir con menciones de presupuesto
("75,000 pesos"), duraciones ("12 meses de ejecución") u otras cifras que aparezcan
antes del puntaje en la respuesta del AI. El riesgo es bajo pero existe.

**Qué se hizo:**
Agregado al inicio de la lista de patrones el más específico:

```python
r"puntaje\s+cyrano\s*[:=]\s*(\d+(?:\.\d+)?)",
```

Ahora la lista completa en orden de precedencia es:
1. `puntaje cyrano: 87.5` — nuevo, captura primero cuando el AI escribe la etiqueta explícita
2. `puntaje total/final/ponderado: X` — puntaje genérico con etiqueta
3. `score: X` — anglicismo
4. `X / 100` — fracción sobre 100
5. `X puntos` — el más genérico (mayor riesgo de falso positivo)

---

## #8 ✅ ~~`max_iterations=10` puede ser insuficiente en flujos completos~~ — FIXED

**Archivo:** `backend/app/services/ai_agent.py` → función `_process_response`

**Qué pasaba:**
El límite estaba en 10 iteraciones. Un flujo completo consume como mínimo:
1. `save_project_data`
2. `run_diagnostic`
3. `save_diagnostic_result`
4. `generate_word_document`
5. `save_to_project_memory`

Eso son 5 iteraciones base. Si además se llama `calculate_budget`,
`extract_requirements`, o el AI hace llamadas adicionales, el contador llegaba a 8-9
fácilmente. Si se cortaba en 10, el mensaje final al usuario podía quedar truncado
o el `save_to_project_memory` no llegaba a ejecutarse.

**Qué se hizo:**
Cambiado `max_iterations = 10` → `max_iterations = 15` en las **dos** funciones
donde aparece en `ai_agent.py` (`_process_response` y la función de streaming).

---

## #9 ✅ ~~`ReviewPanel` nunca muestra el desglose por sección ni el historial de puntajes~~ — FIXED

**Archivos:** `frontend/src/components/ReviewPanel.tsx` + `frontend/src/lib/api.ts` + `frontend/src/lib/types.ts`

**Qué pasaba:**
`ReviewPanel.tsx` nunca llamaba `GET /api/projects/{id}/evaluations`. Solo mostraba
`project.cyrano_score` total. El usuario no sabía qué sección tenía 6/10 vs 9/10,
cuánto aportaba cada una, ni cómo evolucionó entre diagnósticos.

**Qué se hizo:**

**`frontend/src/lib/types.ts`:**
- Agregada interfaz `CyranoEvaluation` con campos `id`, `score`, `version`, `verdict`,
  `sections` (6 claves opcionales 1-10), `feedback` (gaps + recommendations), `created_at`.

**`frontend/src/lib/api.ts`:**
- Importado `CyranoEvaluation` desde types.
- Agregada función `listCyranoEvaluations(projectId)` que llama
  `GET /api/projects/{id}/evaluations` usando el helper `request<T>` tipado.

**`frontend/src/components/ReviewPanel.tsx`:**
- Importados `listCyranoEvaluations` y `CyranoEvaluation`.
- Nuevo estado `evaluations: CyranoEvaluation[]`.
- `loadProject()` ahora hace `Promise.all` con tres llamadas: `getProject`, `listAllProjectDocuments`, `listCyranoEvaluations`.
- Nueva pestaña **"🏆 Cyrano"** agregada al array `tabs`.
- Nuevo componente `CyranoTab` que muestra:
  - Encabezado: versión, score, verdict, "Faltan X pts para aprobar".
  - Tabla de desglose por sección: Nota/10, Aporte (contribución al total), Etiqueta
    (Débil/Intermedio/Sólido con colores), delta vs evaluación anterior (si existe).
  - Lista de brechas (`feedback.gaps`) con bullets rojos.
  - Lista de recomendaciones (`feedback.recommendations`) numerada.
  - Historial de todas las versiones con fechas y scores.
- Helpers `getSectionLabel()` y `labelColor()` con las bandas del manual:
  ≤6 → Débil, 7-8 → Intermedio, 9-10 → Sólido.

---

## #10 ✅ ~~Presupuesto: sub-criterios sin pesos y `calculate_budget` desconectado del Cyrano~~ — FIXED

**Archivos:** `backend/app/core/prompts.py` + `backend/app/services/tools.py`

### El problema: dos evaluaciones del presupuesto que nunca se hablaban

| Dónde | Qué evaluaba | ¿Llegaba al puntaje Cyrano? |
|---|---|---|
| `CYRANO_DIAGNOSTIC_PROMPT` | 3 sub-criterios cualitativos sin pesos | ✅ Sí |
| `calculate_budget` (tool) | Integridad estructural y total vs tope | ❌ No |

El evaluador Cyrano podía dar 7/10 al presupuesto sin saber que `calculate_budget`
ya había reportado "3 rubros sin actividad vinculada" + "Admin (9.2%) excede tope (7%)".

### Qué se hizo

**Paso A — Sub-pesos explícitos en `CYRANO_DIAGNOSTIC_PROMPT` (`prompts.py`):**

La sección 6 ahora define tres sub-criterios con pesos internos:
- a) Desglose por rubros: **40%** de la sección
- b) Alineación con actividades del cronograma: **35%** de la sección
- c) Cumplimiento de topes de la convocatoria: **25%** de la sección

Se agrega nota al evaluador: si `budget_integrity.issues` no está vacío, esas
fallas son evidencia objetiva que debe considerar — no puede ignorarlas.

**Paso B — Alimentar `calculate_budget` al evaluador (`handle_run_diagnostic` en `tools.py`):**

Antes de retornar el payload al LLM, se lee `project.budget`:
- Si es un dict con claves `validated`/`issues` (es decir, `calculate_budget` ya corrió):
  se agrega `budget_integrity: { validated, total, issues }` al payload.
- Si no: se agrega `budget_integrity: { validated: false, issues: ["calculate_budget no ejecutado"] }`.

Esto garantiza que el evaluador Cyrano siempre recibe el contexto estructural del presupuesto.

**Paso C — Cap automático de nota si hay issues (`handle_save_diagnostic_result` en `tools.py`):**

Antes de calcular el promedio, si `project.budget` tiene `issues` no vacíos,
la nota de `sections["budget"]` se limita a `min(nota_LLM, 5.0)`.

Esto garantiza que un presupuesto con problemas estructurales nunca supere 5/10,
independientemente de lo que haya evaluado el LLM.
   - Desglose por rubros adecuado         ← ¿cuánto pesa?                ❌ no definido
```

Propuesta de sub-pesos explícitos (a confirmar contra el knowledge base en Vector Store):
```
6. Presupuesto (peso total: 20%)
   - Desglose por rubros adecuado         → 40% del 20% = 8 pts máx
     (Personal, Equipos, Insumos, Servicios, Admin — cada rubro vinculado a actividad)
   - Alineación con actividades           → 35% del 20% = 7 pts máx
     (cada actividad del cronograma tiene al menos un rubro con monto)
   - Cumplimiento de topes de convocatoria → 25% del 20% = 5 pts máx
     (total ≤ max_total, Admin ≤ admin_cap%)
```

### `calculate_budget` valida pero el resultado no alimenta al Cyrano

---

## Resumen de orden de implementación

| # | Estado | Archivo principal | Descripción corta |
|---|--------|-------------------|-------------------|
| 1 | ✅ FIXED | `ai_agent.py` | Inyectar `CYRANO_DIAGNOSTIC_PROMPT` en el loop |
| 2 | ✅ FIXED | `tools.py` | Bloquear diagnóstico en proyecto vacío |
| 3 | ✅ FIXED | `diagnostic.py` | Auto-actualizar status a "validated" |
| 4 | ✅ FIXED | `tools.py` | Recalcular score en servidor con pesos fijos |
| 5 | ✅ FIXED | `tools.py` | Implementar `extract_requirements` real |
| 6 | ✅ FIXED | `tools.py` | Separar texto libre de campos estructurados |
| 7 | ✅ FIXED | `diagnostic.py` | Mejorar regex de fallback |
| 8 | ✅ FIXED | `ai_agent.py` | Subir `max_iterations` a 15 |
| 9 | ✅ FIXED | `ReviewPanel.tsx` + `api.ts` | Mostrar desglose por sección y gaps |
| 10 | ✅ FIXED | `prompts.py` + `tools.py` | Sub-pesos de presupuesto + conectar `calculate_budget` |
