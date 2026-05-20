Este documento constituye la **Especificación Técnica y de Arquitectura (Source of Truth)** para el desarrollo del sistema **"Pipidepulus AI: Generador de Proyectos de Alto Impacto"**. Está diseñado para ser procesado por un flujo de **Spec-Driven Development (SDD)**.

-----
**Software Requirements Specification (SRS) - Pipidepulus AI**

**1. Visión General**

El sistema es una plataforma avanzada de ingeniería de proyectos que automatiza la búsqueda, análisis, formulación y optimización de propuestas para convocatorias de financiamiento (grants/subvenciones). Utiliza la metodología propietaria de Pipidepulus **Proyectos** para garantizar que los documentos generados cumplan con los más altos estándares de elegibilidad y competitividad.

**2. Pilares Tecnológicos (Stack & AI)**

- **LLM Core:** OpenAI GPT-5-mini (interfaz vía API con soporte para function\_calling).
- **Capacidades AI:**
  - web\_search: Para detección de convocatorias en tiempo real.
  - file\_search: Para extracción de datos de bases de programas y términos de referencia (TDR).
  - function\_tools: Para cálculos presupuestarios y estructuración de cronogramas.
  - Debe utilizar responses API en lugar de chat completions API de OpenAI
- **Vector Stores (OpenAI):**
  - **VS\_Knowledge\_Base:** Contiene la metodología Propulsa (Árbol de problemas, Cadena de valor, etc.).
  - **VS\_Project\_Memory:** Almacena proyectos previos, especificaciones de convocatorias analizadas y "experiencia" de éxito/fallo.
- **Base de Datos:** PostgreSQL (almacenamiento de documentos generados, perfiles de usuario y metadatos de versiones).
- **Output:** Generación dinámica de documentos .docx con formato profesional.
-----
**3. Arquitectura del Sistema y Flujo de Trabajo**

**Módulo A: Detección y Extracción (Paso "Detecta")**

1. **Web Scanning:** El sistema utiliza la herramienta de búsqueda para localizar convocatorias según sector/territorio solicitado.
1. **Data Extraction:** El usuario sube los PDF/Documentos de la convocatoria. El sistema aplica un proceso de "parsing" avanzado para extraer:
   1. Criterios de elegibilidad.
   1. Montos máximos y contrapartidas requeridas.
   1. Fechas de cierre.
   1. Secciones obligatorias del formulario.

**Módulo B: Núcleo Metodológico Propulsa (Paso "Crea")**

El sistema guía al usuario a través de los 6 pasos definidos en la guía:

1. **Identificación del Problema:** Definición, impacto y evidencia.
1. **Árbol de Problemas:** Generación lógica de Causas 
1. `        `→



Problema Central 

`        `→



Efectos.

1. **Establecimiento de Objetivos:** Conversión del Árbol de Problemas en Árbol de Objetivos (SMART).
1. **Cadena de Valor:** Vinculación de Actividad 
1. `        `→Producto         →Indicador         →Meta.
1. **Cronograma:** Planificación temporal detallada.
1. **Presupuesto:** Estimación de costos por rubros (Personal, Equipos, Insumos, etc.).

**Módulo C: El Ciclo de Optimización "Cyrano 95+" (Paso "Valida")**

El sistema actúa como un evaluador implacable basado en el documento "Cyrano Validador":

- **Evaluación Cuantitativa:** Asigna puntajes (1-10) a cada sección.
- **El Umbral Crítico:** Si el proyecto suma menos de **95.01 puntos** (sobre una escala normalizada de 100), el sistema bloquea la exportación final.
- **Iteración Inteligente:** El chat entra en modo "Consultor Experto", analizando junto al usuario las brechas (ej. "El presupuesto no está alineado con la actividad 2.1" o "Falta evidencia cualitativa en el impacto").
-----
**4. Especificaciones de la Interfaz de Usuario (UI/UX)**

- **Layout:** Interfaz tipo Chat centralizado.
- **Barra Lateral (Sidebar):**
  - *Radar de Convocatorias:* Historial de búsquedas web.
  - *Bóveda de Proyectos:* Acceso a documentos en PostgreSQL.
  - *Editor de Perfil Proponente:* Datos de la organización/usuario.
  - *Status de Validación:* Un indicador visual (badge) que muestra el puntaje actual del proyecto en tiempo real.
- **Modo Revisión:** Una vista dividida donde el chat muestra las sugerencias de mejora y el panel derecho muestra el borrador del documento.
-----
**5. Definición de Herramientas (Function Tools para GPT-5-mini)**

|Función|Descripción|
| :- | :- |
|search\_funding\_calls|Ejecuta búsqueda web para encontrar TDRs activos.|
|extract\_requirements|Procesa archivos subidos para mapear reglas de la convocatoria.|
|calculate\_budget|Valida que los rubros no superen los topes de la convocatoria (ej. admin < 7%).|
|generate\_word\_document|Compila toda la información en un archivo Word con estilos profesionales.|
|run\_diagnostic|Ejecuta la lógica de puntuación y retorna el feedback de mejora.|

-----
**6. Modelo de Datos (PostgreSQL)**

- **Users:** ID, Organización, Preferencias.
- **Projects:** ID, Título, Estado, Puntaje\_Cyrano, JSON\_Data (Estructura completa).
- **Generated\_Docs:** ID, Project\_ID, Binary\_File (Word), Version\_Number, Timestamp.
- **Call\_Spec:** ID, Requisitos\_Extraídos, Fuente\_URL.
-----
**7. Lógica de Negocio: Invariabilidad de Términos**

El sistema tiene prohibido alucinar o modificar los términos metodológicos.

- **Glosario Invariable:** Árbol de problemas, Cadena de valor, Contrapartida, Hito, Indicador, Meta, Resultado.
- **Bilingüismo:** Capacidad de traducir la lógica técnica manteniendo la equivalencia semántica (ej. *Problem Tree* ↔*Árbol de problemas*). El documento final debe tener la opción de seleccionar el idioma en inglés o español
-----
**8. Source of Truth para SDD (Instrucción de Desarrollo)**

"Construir un sistema que orqueste dos Vector Stores en OpenAI. El primero servirá como base de conocimiento estática de la Metodología Propulsa. El segundo será una memoria dinámica de proyectos. El flujo de trabajo debe impedir la radicación si el diagnóstico de validación es 

`        `≤95



. El documento final debe seguir el formato de 'Plan de Negocios / Protocolo' del ejemplo de Cytoreg, asegurando coherencia total entre el problema, los objetivos y el presupuesto."

-----
**Fin del documento.**

