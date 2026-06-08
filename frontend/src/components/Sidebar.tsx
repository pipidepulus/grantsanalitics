"use client";

import { useState, useEffect } from "react";
import type { ProjectListItem, Conversation, ProjectDocuments } from "@/lib/types";
import {
  createProject,
  listAllProjectDocuments,
  downloadDocument,
  deleteDocument,
  retryDocumentIndexing,
} from "@/lib/api";
import {
  FolderOpen,
  User,
  Plus,
  MessageSquare,
  ChevronDown,
  ChevronRight,
  FileText,
  HelpCircle,
  X,
  Download,
  Upload,
  File,
  BarChart2,
} from "lucide-react";

interface SidebarProps {
  projects: ProjectListItem[];
  conversations: Conversation[];
  activeProjectId: string | null;
  activeView: "chat" | "review";
  cyranoScore: number | null;
  onProjectChatSelect: (projectId: string, conversationId: string | null) => void;
  onProjectReviewSelect: (projectId: string) => void;
  onDeleteProject: (id: string) => void;
  onRefresh: () => void;
  userId: string;
}

export function Sidebar({
  projects,
  conversations,
  activeProjectId,
  activeView,
  cyranoScore,
  onProjectChatSelect,
  onProjectReviewSelect,
  onDeleteProject,
  onRefresh,
  userId,
}: SidebarProps) {
  const [expandedProjectId, setExpandedProjectId] = useState<string | null>(null);
  const [expandedDocsProjectId, setExpandedDocsProjectId] = useState<string | null>(null);
  const [newProjectTitle, setNewProjectTitle] = useState("");
  const [showNewProject, setShowNewProject] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  const [projectDocs, setProjectDocs] = useState<Record<string, ProjectDocuments>>({});
  const [loadingDocs, setLoadingDocs] = useState<string | null>(null);
  const [retryingDoc, setRetryingDoc] = useState<string | null>(null);

  useEffect(() => {
    if (activeProjectId) {
      setExpandedProjectId(activeProjectId);
    }
  }, [activeProjectId]);

  async function loadProjectDocs(projectId: string) {
    setLoadingDocs(projectId);
    try {
      const docs = await listAllProjectDocuments(projectId);
      setProjectDocs((prev) => ({ ...prev, [projectId]: docs }));
    } catch {
      // ignore
    }
    setLoadingDocs(null);
  }

  async function handleCreateProject(e: React.FormEvent) {
    e.preventDefault();
    if (!newProjectTitle.trim()) return;
    try {
      const project = await createProject({ title: newProjectTitle, user_id: userId });
      setNewProjectTitle("");
      setShowNewProject(false);
      onProjectChatSelect(project.id, null);
      onRefresh();
    } catch (err) {
      console.error("Failed to create project:", err);
    }
  }

  async function handleRetryIndexing(docId: string, projectId: string) {
    setRetryingDoc(docId);
    try {
      await retryDocumentIndexing(docId);
      const updated = await listAllProjectDocuments(projectId);
      setProjectDocs((prev) => ({ ...prev, [projectId]: updated }));
    } catch {
      // ignore
    }
    setRetryingDoc(null);
  }

  function handleToggleProject(projectId: string) {
    const next = expandedProjectId === projectId ? null : projectId;
    setExpandedProjectId(next);
    if (next && !projectDocs[next]) {
      loadProjectDocs(next);
    }
  }

  function handleToggleDocs(projectId: string) {
    const next = expandedDocsProjectId === projectId ? null : projectId;
    setExpandedDocsProjectId(next);
    if (next && !projectDocs[next]) {
      loadProjectDocs(next);
    }
  }

  function getScoreColor(score: number | null) {
    if (!score) return "text-[var(--text-secondary)]";
    if (score >= 95.01) return "text-[var(--success)]";
    if (score >= 80) return "text-[var(--warning)]";
    return "text-[var(--danger)]";
  }

  function getStatusLabel(status: string) {
    const labels: Record<string, string> = {
      draft: "Borrador",
      in_progress: "En Progreso",
      validated: "Validado",
      exported: "Exportado",
    };
    return labels[status] || status;
  }

  function getProjectConversationId(projectId: string): string | null {
    const conv = conversations
      .filter((c) => c.project_id === projectId)
      .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())[0];
    return conv?.id ?? null;
  }

  return (
    <aside className="w-72 h-full flex flex-col border-r border-[var(--border-color)] bg-[var(--bg-secondary)] relative">
      {/* Header */}
      <div className="p-4 border-b border-[var(--border-color)]">
        <h1 className="text-lg font-bold text-[var(--accent)]">Pipidepulus AI</h1>
        <p className="text-sm text-[var(--text-secondary)] mt-1">
          Generador de Proyectos de Alto Impacto
        </p>
      </div>

      {/* New Project CTA */}
      <div className="p-3 border-b border-[var(--border-color)]">
        {!showNewProject ? (
          <button
            onClick={() => setShowNewProject(true)}
            className="w-full flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg text-sm font-medium bg-[var(--accent)] text-white hover:opacity-90 transition-opacity"
          >
            <Plus className="w-4 h-4" />
            Nuevo Proyecto
          </button>
        ) : (
          <form onSubmit={handleCreateProject} className="flex flex-col gap-2">
            <input
              type="text"
              value={newProjectTitle}
              onChange={(e) => setNewProjectTitle(e.target.value)}
              placeholder="Título del proyecto..."
              autoFocus
              className="w-full px-3 py-2 text-sm rounded-lg bg-[var(--bg-primary)] border border-[var(--border-color)] text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
            />
            <div className="flex gap-2">
              <button
                type="submit"
                className="flex-1 px-3 py-1.5 text-xs rounded-lg bg-[var(--accent)] text-white hover:opacity-90"
              >
                Crear
              </button>
              <button
                type="button"
                onClick={() => { setShowNewProject(false); setNewProjectTitle(""); }}
                className="flex-1 px-3 py-1.5 text-xs rounded-lg border border-[var(--border-color)] text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)]"
              >
                Cancelar
              </button>
            </div>
          </form>
        )}
      </div>

      {/* Projects List */}
      <nav className="flex-1 overflow-y-auto">
        {projects.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-40 gap-2 px-6 text-center">
            <FolderOpen className="w-8 h-8 text-[var(--text-secondary)] opacity-30" />
            <p className="text-xs text-[var(--text-secondary)]">
              No tienes proyectos aún. Crea tu primer proyecto para comenzar.
            </p>
          </div>
        ) : (
          <div className="p-2 space-y-1">
            {projects.map((project) => {
              const isExpanded = expandedProjectId === project.id;
              const isActive = activeProjectId === project.id;
              const docs = projectDocs[project.id];
              const isDocsExpanded = expandedDocsProjectId === project.id;
              const projectConvId = getProjectConversationId(project.id);

              return (
                <div key={project.id}>
                  {/* Project Row */}
                  <div
                    className={`group flex items-center gap-1 px-2 py-2 rounded-lg cursor-pointer transition-colors ${
                      isActive
                        ? "bg-[var(--bg-tertiary)] border-l-2 border-[var(--accent)] pl-1.5"
                        : "hover:bg-[var(--bg-tertiary)]"
                    }`}
                  >
                    <button
                      onClick={() => handleToggleProject(project.id)}
                      className="flex-shrink-0 p-0.5 text-[var(--text-secondary)]"
                    >
                      {isExpanded ? (
                        <ChevronDown className="w-3.5 h-3.5" />
                      ) : (
                        <ChevronRight className="w-3.5 h-3.5" />
                      )}
                    </button>

                    <button
                      onClick={() => handleToggleProject(project.id)}
                      className="flex-1 text-left min-w-0"
                    >
                      <div className="truncate text-sm font-medium text-[var(--text-primary)]">
                        {project.title}
                      </div>
                      <div className="flex items-center gap-2 mt-0.5">
                        <span className="text-[10px] text-[var(--text-secondary)]">
                          {getStatusLabel(project.status)}
                        </span>
                        {project.cyrano_score !== null && (
                          <span className={`text-[10px] font-semibold ${getScoreColor(project.cyrano_score)}`}>
                            {project.cyrano_score.toFixed(1)}
                          </span>
                        )}
                      </div>
                    </button>

                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        if (confirm(`¿Eliminar "${project.title}"? Se borrarán todos sus documentos.`)) {
                          onDeleteProject(project.id);
                        }
                      }}
                      className="flex-shrink-0 p-1 opacity-0 group-hover:opacity-100 text-[var(--danger)] hover:bg-[var(--bg-primary)] rounded transition-all"
                      title="Eliminar proyecto"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>

                  {/* Sub-items */}
                  {isExpanded && (
                    <div className="ml-6 mr-1 mb-1 mt-0.5 space-y-0.5">
                      {/* Chat */}
                      <button
                        onClick={() => onProjectChatSelect(project.id, projectConvId)}
                        className={`w-full flex items-center gap-2 px-3 py-1.5 rounded text-xs transition-colors ${
                          isActive && activeView === "chat"
                            ? "bg-[var(--accent)] text-white"
                            : "text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)] hover:text-[var(--text-primary)]"
                        }`}
                      >
                        <MessageSquare className="w-3.5 h-3.5 flex-shrink-0" />
                        Chat del proyecto
                      </button>

                      {/* Revisión / Análisis */}
                      <button
                        onClick={() => onProjectReviewSelect(project.id)}
                        className={`w-full flex items-center gap-2 px-3 py-1.5 rounded text-xs transition-colors ${
                          isActive && activeView === "review"
                            ? "bg-[var(--warning)]/20 text-[var(--warning)]"
                            : "text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)] hover:text-[var(--text-primary)]"
                        }`}
                      >
                        <BarChart2 className="w-3.5 h-3.5 flex-shrink-0" />
                        Revisión / Análisis
                        {isActive && cyranoScore !== null && (
                          <span className={`ml-auto text-[10px] font-bold ${getScoreColor(cyranoScore)}`}>
                            {cyranoScore.toFixed(1)}
                          </span>
                        )}
                      </button>

                      {/* Documentos toggle */}
                      <button
                        onClick={() => handleToggleDocs(project.id)}
                        className="w-full flex items-center gap-2 px-3 py-1.5 rounded text-xs text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)] hover:text-[var(--text-primary)] transition-colors"
                      >
                        <FileText className="w-3.5 h-3.5 flex-shrink-0" />
                        Documentos
                        {isDocsExpanded ? (
                          <ChevronDown className="w-3 h-3 ml-auto" />
                        ) : (
                          <ChevronRight className="w-3 h-3 ml-auto" />
                        )}
                      </button>

                      {/* Documents list */}
                      {isDocsExpanded && (
                        <div className="ml-2 space-y-0.5 pb-1">
                          {loadingDocs === project.id ? (
                            <p className="text-[10px] text-[var(--text-secondary)] px-2 py-1">Cargando...</p>
                          ) : docs ? (
                            <>
                              {docs.uploaded.length > 0 && (
                                <div className="mb-1">
                                  <p className="text-[9px] text-[var(--accent)] px-2 flex items-center gap-1 mb-0.5">
                                    <Upload className="w-2.5 h-2.5" /> Subidos
                                  </p>
                                  {docs.uploaded.map((doc) => (
                                    <div
                                      key={doc.id}
                                      className="group/doc flex items-center gap-1 px-2 py-0.5 text-[10px] text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)] rounded"
                                    >
                                      <File className="w-2.5 h-2.5 flex-shrink-0" />
                                      <a href={downloadDocument(doc.id)} className="truncate flex-1" title={doc.filename}>
                                        {doc.filename}
                                      </a>
                                      {doc.indexing_status === "indexed" && (
                                        <span className="text-[9px] text-[var(--success)] flex-shrink-0" title="Indexado">✓</span>
                                      )}
                                      {doc.indexing_status === "pending" && (
                                        <span className="text-[9px] text-[var(--warning)] flex-shrink-0" title="Indexando...">⏳</span>
                                      )}
                                      {doc.indexing_status === "failed" && (
                                        <button
                                          onClick={(e) => { e.stopPropagation(); handleRetryIndexing(doc.id, project.id); }}
                                          disabled={retryingDoc === doc.id}
                                          className="text-[9px] text-[var(--danger)] flex-shrink-0 hover:text-white disabled:opacity-50"
                                          title="Error — clic para reintentar"
                                        >
                                          {retryingDoc === doc.id ? "⏳" : "⚠"}
                                        </button>
                                      )}
                                      <a href={downloadDocument(doc.id)} title="Descargar" className="opacity-0 group-hover/doc:opacity-100">
                                        <Download className="w-2.5 h-2.5" />
                                      </a>
                                      <button
                                        onClick={async (e) => {
                                          e.stopPropagation();
                                          if (confirm(`¿Eliminar "${doc.filename}"?`)) {
                                            try {
                                              await deleteDocument(doc.id);
                                              const updated = await listAllProjectDocuments(project.id);
                                              setProjectDocs((prev) => ({ ...prev, [project.id]: updated }));
                                            } catch { /* ignore */ }
                                          }
                                        }}
                                        className="opacity-0 group-hover/doc:opacity-100 text-[var(--danger)] flex-shrink-0"
                                        title="Eliminar"
                                      >
                                        <X className="w-2.5 h-2.5" />
                                      </button>
                                    </div>
                                  ))}
                                </div>
                              )}

                              {docs.generated.length > 0 && (
                                <div>
                                  <p className="text-[9px] text-[var(--success)] px-2 flex items-center gap-1 mb-0.5">
                                    <FileText className="w-2.5 h-2.5" /> Generados
                                  </p>
                                  {docs.generated.map((doc) => (
                                    <div
                                      key={doc.id}
                                      className="group/doc flex items-center gap-1 px-2 py-0.5 text-[10px] text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)] rounded"
                                    >
                                      <FileText className="w-2.5 h-2.5 flex-shrink-0 text-[var(--success)]" />
                                      <a href={downloadDocument(doc.id)} className="truncate flex-1" title={doc.filename}>
                                        {doc.filename}
                                      </a>
                                      <a href={downloadDocument(doc.id)} title="Descargar" className="opacity-0 group-hover/doc:opacity-100">
                                        <Download className="w-2.5 h-2.5" />
                                      </a>
                                      <button
                                        onClick={async (e) => {
                                          e.stopPropagation();
                                          if (confirm(`¿Eliminar "${doc.filename}"?`)) {
                                            try {
                                              await deleteDocument(doc.id);
                                              const updated = await listAllProjectDocuments(project.id);
                                              setProjectDocs((prev) => ({ ...prev, [project.id]: updated }));
                                            } catch { /* ignore */ }
                                          }
                                        }}
                                        className="opacity-0 group-hover/doc:opacity-100 text-[var(--danger)] flex-shrink-0"
                                        title="Eliminar"
                                      >
                                        <X className="w-2.5 h-2.5" />
                                      </button>
                                    </div>
                                  ))}
                                </div>
                              )}

                              {docs.uploaded.length === 0 && docs.generated.length === 0 && (
                                <p className="text-[10px] text-[var(--text-secondary)] px-2 py-1 italic">Sin documentos aún</p>
                              )}
                            </>
                          ) : (
                            <p className="text-[10px] text-[var(--text-secondary)] px-2 py-1 italic">Sin documentos aún</p>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </nav>

      {/* Footer */}
      <div className="p-3 border-t border-[var(--border-color)] space-y-1">
        <button
          onClick={() => setShowHelp(true)}
          className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm hover:bg-[var(--bg-tertiary)] transition-colors text-[var(--accent)]"
        >
          <HelpCircle className="w-4 h-4" />
          <span className="text-sm">Ayuda &amp; Manual de Usuario</span>
        </button>
        <button disabled className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm opacity-40 cursor-not-allowed" title="Próximamente">
          <User className="w-4 h-4" />
          <span className="text-sm text-[var(--text-secondary)]">Perfil Proponente <span className="text-[10px] ml-1">(próximamente)</span></span>
        </button>
      </div>

      {/* Help / User Manual Panel */}
      {showHelp && (
        <div className="fixed inset-0 z-50 flex">
          <div className="w-full max-w-md bg-[var(--bg-secondary)] border-r border-[var(--border-color)] flex flex-col h-full overflow-hidden">
            <div className="flex items-center justify-between p-4 border-b border-[var(--border-color)]">
              <div className="flex items-center gap-2">
                <HelpCircle className="w-5 h-5 text-[var(--accent)]" />
                <h2 className="text-sm font-bold text-[var(--text-primary)]">Manual de Usuario</h2>
              </div>
              <button onClick={() => setShowHelp(false)} className="p-1 rounded hover:bg-[var(--bg-tertiary)] transition-colors">
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-4 space-y-5 text-xs text-[var(--text-secondary)] leading-relaxed">
              <section>
                <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-2">¿Qué es Pipidepulus AI?</h3>
                <p>
                  Pipidepulus AI es tu consultor experto en formulación de proyectos para convocatorias de financiamiento.
                  Utiliza inteligencia artificial para guiarte paso a paso en la creación, validación y exportación de
                  propuestas ganadoras siguiendo la <strong>Metodología Propulsa</strong>.
                </p>
              </section>

              <section>
                <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-2">🚀 ¿Cómo empezar?</h3>
                <ol className="list-decimal list-inside space-y-1.5">
                  <li>Haz clic en <strong>&quot;Nuevo Proyecto&quot;</strong> e ingresa un título para tu propuesta.</li>
                  <li>Entra al <strong>Chat del proyecto</strong> y describe tu idea o pide que busque convocatorias activas indicando <strong>sector</strong> y <strong>territorio</strong>.</li>
                  <li>El asistente te guiará por los 6 pasos de la Metodología Propulsa para construir tu proyecto.</li>
                  <li>Usa <strong>Revisión / Análisis</strong> para ver el estado del documento y el puntaje Cyrano. Cuando alcance <strong>≥ 95.01</strong>, el documento estará listo para exportar.</li>
                  <li>Todos los archivos subidos y generados están en la sección <strong>Documentos</strong> de cada proyecto.</li>
                </ol>
              </section>

              <section>
                <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-2">📎 Cómo compartir una convocatoria con el asistente</h3>
                <p className="mb-2">Tenés dos formas de darle el texto de una convocatoria:</p>
                <ul className="space-y-2 list-disc list-inside">
                  <li><strong className="text-[var(--text-primary)]">Adjuntar archivo</strong> — Hacé clic en el ícono 📎 en la barra de escritura y seleccioná un PDF, Word o TXT. El sistema lo indexa y lo analiza automáticamente.</li>
                  <li><strong className="text-[var(--text-primary)]">Pegar texto directo</strong> — Copiá el contenido de la convocatoria (o su FAQ, TDR, especificaciones) y pegalo directamente en el chat. El asistente lo detecta y lo procesa igual que un archivo subido.</li>
                </ul>
              </section>

              <section>
                <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-2">💾 Botón Guardar</h3>
                <p>El botón <strong>Guardar</strong> en el header del chat guarda una copia de la conversación vinculada al proyecto activo. Usalo cuando quieras preservar una sesión importante antes de continuar en otra sesión.</p>
              </section>

              <section>
                <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-2">📋 Metodología Propulsa (6 Pasos)</h3>
                <div className="space-y-2">
                  {[
                    ["Paso 1", "Identificación del Problema — Define el problema central, su impacto y evidencia de respaldo."],
                    ["Paso 2", "Árbol de Problemas — Construye la lógica: Causas → Problema Central → Efectos."],
                    ["Paso 3", "Objetivos SMART — Convierte el Árbol de Problemas en un Árbol de Objetivos medibles."],
                    ["Paso 4", "Cadena de Valor — Vincula: Actividad → Producto → Indicador → Meta."],
                    ["Paso 5", "Cronograma — Planifica hitos y fases de ejecución del proyecto."],
                    ["Paso 6", "Presupuesto — Estima costos por rubro alineados con la convocatoria."],
                  ].map(([step, desc]) => (
                    <div key={step} className="p-2 rounded bg-[var(--bg-tertiary)]">
                      <strong className="text-[var(--accent)]">{step}:</strong> {desc}
                    </div>
                  ))}
                </div>
              </section>

              <section>
                <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-2">🗂️ Secciones del Panel Lateral</h3>
                <ul className="space-y-2">
                  <li><strong className="text-[var(--text-primary)]">Nuevo Proyecto</strong> — Crea un proyecto nuevo. Cada proyecto organiza su propio chat, análisis y documentos.</li>
                  <li><strong className="text-[var(--text-primary)]">Chat del proyecto</strong> — Historial de conversación con el asistente vinculado a ese proyecto.</li>
                  <li><strong className="text-[var(--text-primary)]">Revisión / Análisis</strong> — Vista dividida: sugerencias del AI a la izquierda, borrador del documento a la derecha. Muestra el puntaje Cyrano actualizado.</li>
                  <li><strong className="text-[var(--text-primary)]">Documentos</strong> — Archivos subidos (convocatorias, cartas, CVs) y documentos generados (borradores, versión final Word).</li>
                </ul>
              </section>

              <section>
                <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-2">🏆 Diagnóstico Cyrano</h3>
                <p className="mb-2">El sistema evalúa tu proyecto con un puntaje de <strong>0 a 100</strong>.</p>
                <div className="p-2 rounded bg-[var(--bg-tertiary)] space-y-1">
                  <div className="flex items-center gap-2"><span className="w-3 h-3 rounded-full bg-[var(--success)]"></span><span><strong>≥ 95.01</strong> — Documento final listo</span></div>
                  <div className="flex items-center gap-2"><span className="w-3 h-3 rounded-full bg-[var(--warning)]"></span><span><strong>80 – 95</strong> — Necesita mejoras menores</span></div>
                  <div className="flex items-center gap-2"><span className="w-3 h-3 rounded-full bg-[var(--danger)]"></span><span><strong>&lt; 80</strong> — Requiere trabajo significativo</span></div>
                </div>
                <p className="mt-2">Si el puntaje es menor a 95.01, el asistente entra en modo <strong>Consultor Experto</strong> y te indica exactamente qué mejorar.</p>
              </section>

              <section>
                <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-2">💬 ¿Qué puedo pedirle al asistente?</h3>
                <ul className="space-y-1 list-disc list-inside">
                  <li>Buscar convocatorias activas por sector y país</li>
                  <li>Analizar un documento de convocatoria subido o texto pegado</li>
                  <li>Guiarte paso a paso en la formulación del proyecto</li>
                  <li>Construir Árboles de Problemas y Objetivos</li>
                  <li>Diseñar la Cadena de Valor con indicadores y metas</li>
                  <li>Elaborar cronograma y presupuesto</li>
                  <li>Validar topes presupuestarios contra la convocatoria</li>
                  <li>Ejecutar el diagnóstico Cyrano</li>
                  <li>Generar borradores o el documento Word final del proyecto</li>
                </ul>
                <p className="mt-2">Cuando el asistente genera el documento Word, incluye un <strong>link de descarga</strong> directamente en el chat.</p>
              </section>

              <section>
                <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-2">📖 Glosario de Términos</h3>
                <div className="space-y-1.5">
                  {[
                    ["Árbol de Problemas", "Estructura lógica: Causas → Problema → Efectos"],
                    ["Cadena de Valor", "Vínculo: Actividad → Producto → Indicador → Meta"],
                    ["Convocatoria / TDR", "Oportunidad abierta de financiamiento"],
                    ["Contrapartida", "Fondos de contraparte requeridos por el solicitante"],
                    ["Hito", "Punto clave de verificación en el cronograma"],
                    ["Indicador", "Métrica medible vinculada a un producto/resultado"],
                    ["Meta", "Objetivo cuantitativo para cada indicador"],
                    ["Puntaje Cyrano", "Calificación cuantitativa del proyecto (meta: 95.01)"],
                  ].map(([term, def]) => (
                    <div key={term} className="flex gap-2">
                      <span className="font-semibold text-[var(--text-primary)] whitespace-nowrap">{term}:</span>
                      <span>{def}</span>
                    </div>
                  ))}
                </div>
              </section>

              <section className="pb-4">
                <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-2">💡 Consejos Útiles</h3>
                <ul className="space-y-1 list-disc list-inside">
                  <li>Sé específico al describir tu problema central.</li>
                  <li>Subí el documento de la convocatoria o pegá su texto directo en el chat — ambas formas funcionan igual.</li>
                  <li>Usá el diagnóstico Cyrano frecuentemente para ver tu progreso.</li>
                  <li>El chat puede estar en cualquier idioma, pero el documento Word se genera en el idioma que le indiques al asistente (español o inglés), independientemente del idioma de la convocatoria.</li>
                  <li>Podés tener múltiples proyectos y convocatorias simultáneamente.</li>
                  <li>Si la convocatoria es larga, pegá las secciones más relevantes (criterios, montos, fechas) en lugar del texto completo.</li>
                </ul>
              </section>
            </div>
          </div>
          <div className="flex-1 bg-black/40" onClick={() => setShowHelp(false)} />
        </div>
      )}
    </aside>
  );
}
