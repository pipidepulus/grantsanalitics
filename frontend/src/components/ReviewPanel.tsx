"use client";

import { useState, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import { getProject, listAllProjectDocuments, downloadDocument, listCyranoEvaluations } from "@/lib/api";
import type { Project, GeneratedDoc, ProjectDocuments, CyranoEvaluation } from "@/lib/types";
import { X, Download, FileText, Award, FileDown, Loader2, AlertTriangle } from "lucide-react";

const API_BASE = "/api";

interface ReviewPanelProps {
  projectId: string;
  onClose: () => void;
}

export function ReviewPanel({ projectId, onClose }: ReviewPanelProps) {
  const [project, setProject] = useState<Project | null>(null);
  const [documents, setDocuments] = useState<ProjectDocuments | null>(null);
  const [evaluations, setEvaluations] = useState<CyranoEvaluation[]>([]);
  const [activeTab, setActiveTab] = useState("overview");
  const [generating, setGenerating] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);
  const [genSuccess, setGenSuccess] = useState<string | null>(null);

  useEffect(() => {
    loadProject();
  }, [projectId]);

  async function loadProject() {
    try {
      const [proj, docs, evals] = await Promise.all([
        getProject(projectId),
        listAllProjectDocuments(projectId),
        listCyranoEvaluations(projectId),
      ]);
      setProject(proj);
      setDocuments(docs);
      setEvaluations(evals);
    } catch {
      // Not available
    }
  }

  async function handleGenerateDocument() {
    if (!project) return;
    setGenerating(true);
    setGenError(null);
    setGenSuccess(null);
    try {
      const res = await fetch(`${API_BASE}/projects/${projectId}/generate-document`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ language: project.language || "es" }),
      });
      const data = await res.json();
      if (!res.ok) {
        setGenError(data.detail || "Error al generar documento");
      } else {
        setGenSuccess(data.message);
        // Reload documents
        const docs = await listAllProjectDocuments(projectId);
        setDocuments(docs);
        setTimeout(() => setGenSuccess(null), 5000);
      }
    } catch {
      setGenError("Error de conexión al generar documento");
    }
    setGenerating(false);
  }

  if (!project) {
    return (
      <div className="w-[480px] border-l border-[var(--border-color)] bg-[var(--bg-secondary)] flex items-center justify-center">
        <p className="text-sm text-[var(--text-secondary)]">Cargando proyecto...</p>
      </div>
    );
  }

  // Extract methodology content from structured fields or json_data
  const fullContent = project.json_data?.full_content as string | undefined;
  const problemDef = project.problem_definition || (project.json_data?.problem_definition as string | undefined);
  const objectives = extractText(project.objectives_tree) || (project.json_data?.objectives as string | undefined);
  const methodology = extractText(project.value_chain) || (project.json_data?.methodology as string | undefined);
  const timeline = extractText(project.timeline) || (project.json_data?.timeline as string | undefined);
  const budgetText = extractText(project.budget) || (project.json_data?.budget as string | undefined);

  const hasSections = !!(problemDef || objectives || methodology || timeline || budgetText || fullContent);
  const canGenerate = hasSections;
  const isDraft = project.cyrano_score === null || project.cyrano_score < 95.01;

  const tabs = [
    { id: "overview", label: "Resumen" },
    { id: "problem", label: "1. Problema" },
    { id: "objectives", label: "2. Objetivos" },
    { id: "chain", label: "3. Cadena" },
    { id: "timeline", label: "4. Cronograma" },
    { id: "budget", label: "5. Presupuesto" },
    { id: "cyrano", label: "🏆 Cyrano" },
    { id: "document", label: "📄 Documento" },
  ];

  function getScoreColor(score: number | null) {
    if (!score) return "text-[var(--text-secondary)]";
    if (score >= 95.01) return "text-[var(--success)]";
    if (score >= 80) return "text-[var(--warning)]";
    return "text-[var(--danger)]";
  }

  return (
    <div className="w-[480px] border-l border-[var(--border-color)] bg-[var(--bg-secondary)] flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-[var(--border-color)]">
        <div className="min-w-0 flex-1 mr-2">
          <h3 className="text-sm font-semibold truncate">{project.title}</h3>
          <div className="flex items-center gap-2 mt-1">
            <Award className="w-3 h-3 text-[var(--accent)]" />
            <span className={`text-xs font-bold ${getScoreColor(project.cyrano_score)}`}>
              {project.cyrano_score ? `${project.cyrano_score.toFixed(1)}/100` : "Sin evaluar"}
            </span>
            <span className="text-[10px] text-[var(--text-secondary)]">
              {getStatusLabel(project.status)}
            </span>
          </div>
        </div>
        <button
          onClick={onClose}
          className="p-1.5 rounded-lg hover:bg-[var(--bg-tertiary)] transition-colors flex-shrink-0"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Tabs */}
      <div className="flex flex-wrap gap-1 p-2 border-b border-[var(--border-color)]">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-2 py-1 rounded text-xs transition-colors ${
              activeTab === tab.id
                ? "bg-[var(--accent)] text-white"
                : "text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)]"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 text-sm">
        {activeTab === "overview" && (
          <div className="space-y-4">
            {!hasSections ? (
              <div className="text-center py-8">
                <p className="text-[var(--text-secondary)] text-sm">
                  Este proyecto aún no tiene contenido de la metodología.
                </p>
                <p className="text-[var(--text-secondary)] text-xs mt-2">
                  Usa el chat para desarrollar las 6 secciones con el asistente AI.
                  El sistema guardará automáticamente el progreso.
                </p>
              </div>
            ) : (
              <>
                <MethodologyStatus
                  problemDef={problemDef}
                  objectives={objectives}
                  methodology={methodology}
                  timeline={timeline}
                  budgetText={budgetText}
                />
                {fullContent && (
                  <div>
                    <h4 className="text-xs font-semibold text-[var(--accent)] mb-2">
                      Contenido Completo del Proyecto
                    </h4>
                    <div className="prose-review text-xs text-[var(--text-secondary)] max-h-96 overflow-y-auto rounded-lg bg-[var(--bg-tertiary)] p-3 border border-[var(--border-color)]">
                      <ReactMarkdown>{fullContent}</ReactMarkdown>
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {activeTab === "problem" && (
          <SectionContent
            title="Identificación del Problema"
            content={problemDef}
            placeholder="Usa el chat para definir el problema central, su impacto y evidencia de respaldo."
          />
        )}

        {activeTab === "objectives" && (
          <SectionContent
            title="Objetivos (SMART)"
            content={objectives}
            placeholder="Usa el chat para establecer el objetivo general y los específicos. Deben derivarse del Árbol de Problemas."
          />
        )}

        {activeTab === "chain" && (
          <SectionContent
            title="Cadena de Valor"
            content={methodology}
            placeholder="Usa el chat para vincular: Actividad → Producto → Indicador → Meta."
          />
        )}

        {activeTab === "timeline" && (
          <SectionContent
            title="Cronograma"
            content={timeline}
            placeholder="Usa el chat para definir la planificación temporal con hitos y plazos."
          />
        )}

        {activeTab === "budget" && (
          <SectionContent
            title="Presupuesto"
            content={budgetText}
            placeholder="Usa el chat para estimar costos por rubros (Personal, Equipos, Insumos, etc.)."
          />
        )}

        {activeTab === "cyrano" && (
          <CyranoTab evaluations={evaluations} />
        )}

        {activeTab === "document" && (
          <div className="space-y-4">
            {/* Generate Document Button */}
            <div className="rounded-lg bg-[var(--bg-tertiary)] p-4 border border-[var(--border-color)]">
              <h4 className="text-xs font-semibold text-[var(--text-primary)] mb-2">
                Generar Documento del Proyecto
              </h4>
              <p className="text-[10px] text-[var(--text-secondary)] mb-3">
                Genera un documento Word (.docx) profesional con las secciones de la metodología
                (Problema, Objetivos, Cadena de Valor, Cronograma, Presupuesto).
                Este es el producto final para radicar.
              </p>

              {isDraft && (
                <div className="flex items-center gap-2 mb-3 p-2 rounded bg-blue-900/20 border border-blue-700/30">
                  <AlertTriangle className="w-3.5 h-3.5 text-[var(--accent)] flex-shrink-0" />
                  <span className="text-[10px] text-[var(--text-secondary)]">
                    {project.cyrano_score != null
                      ? `Puntaje actual: ${project.cyrano_score.toFixed(1)}/100. Se generará como borrador.`
                      : "Sin evaluar. Se generará como borrador."}
                  </span>
                </div>
              )}

              {genError && (
                <p className="text-[10px] text-[var(--danger)] mb-2">{genError}</p>
              )}
              {genSuccess && (
                <p className="text-[10px] text-[var(--success)] mb-2">{genSuccess}</p>
              )}

              <button
                onClick={handleGenerateDocument}
                disabled={generating || !canGenerate}
                className="flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-semibold transition-colors disabled:opacity-40 bg-[var(--accent)] text-white hover:opacity-90"
              >
                {generating ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <FileDown className="w-4 h-4" />
                )}
                {generating ? "Generando..." : "Generar Documento del Proyecto"}
              </button>
            </div>

            {/* Documents Lists */}
            {documents && (
              <>
                {/* Project methodology documents */}
                {documents.generated.length > 0 && (
                  <div>
                    <h4 className="text-xs font-semibold text-[var(--text-primary)] mb-2">
                      📄 Documentos del Proyecto
                    </h4>
                    <p className="text-[10px] text-[var(--text-secondary)] mb-2">
                      Documento profesional con las secciones de la metodología.
                    </p>
                    <div className="space-y-2">
                      {documents.generated.map((doc) => (
                        <div
                          key={doc.id}
                          className="flex items-center justify-between p-3 rounded-lg bg-[var(--bg-tertiary)] border border-[var(--border-color)]"
                        >
                          <div className="flex items-center gap-2 min-w-0">
                            <FileText className="w-4 h-4 text-[var(--success)] flex-shrink-0" />
                            <p className="text-xs font-medium truncate">{doc.filename}</p>
                          </div>
                          <a
                            href={downloadDocument(doc.id)}
                            className="flex items-center gap-1 px-2 py-1 rounded text-[10px] text-[var(--accent)] hover:bg-[var(--bg-primary)] transition-colors flex-shrink-0"
                          >
                            <Download className="w-3 h-3" />
                            Descargar
                          </a>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Uploaded documents */}
                {documents.uploaded.length > 0 && (
                  <div>
                    <h4 className="text-xs font-semibold text-[var(--text-primary)] mb-2">
                      📎 Documentos Subidos
                    </h4>
                    <div className="space-y-2">
                      {documents.uploaded.map((doc) => (
                        <div
                          key={doc.id}
                          className="flex items-center justify-between p-3 rounded-lg bg-[var(--bg-tertiary)] border border-[var(--border-color)]"
                        >
                          <div className="flex items-center gap-2 min-w-0">
                            <FileText className="w-4 h-4 text-[var(--accent)] flex-shrink-0" />
                            <p className="text-xs font-medium truncate">{doc.filename}</p>
                          </div>
                          <a
                            href={downloadDocument(doc.id)}
                            className="flex items-center gap-1 px-2 py-1 rounded text-[10px] text-[var(--accent)] hover:bg-[var(--bg-primary)] transition-colors flex-shrink-0"
                          >
                            <Download className="w-3 h-3" />
                            Descargar
                          </a>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {documents.generated.length === 0 && documents.uploaded.length === 0 && (
                  <p className="text-[10px] text-[var(--text-secondary)] italic">
                    Sin documentos aún. Genera el documento del proyecto o guarda el historial del chat.
                  </p>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Cyrano evaluation tab ────────────────────────────────────────────────────

const SECTION_META: Record<string, string> = {
  problem_definition: "Identificación del Problema",
  problem_tree:       "Árbol de Problemas",
  objectives:         "Objetivos SMART",
  value_chain:        "Cadena de Valor",
  timeline:           "Cronograma",
  budget:             "Presupuesto",
};
const SECTION_KEYS = Object.keys(SECTION_META);

function getSectionLabel(score: number): "Débil" | "Intermedio" | "Sólido" {
  if (score <= 6) return "Débil";
  if (score <= 8) return "Intermedio";
  return "Sólido";
}

function labelColor(label: string) {
  if (label === "Sólido")     return "text-[var(--success)]";
  if (label === "Intermedio") return "text-[var(--warning)]";
  return "text-[var(--danger)]";
}

function CyranoTab({ evaluations }: { evaluations: CyranoEvaluation[] }) {
  if (evaluations.length === 0) {
    return (
      <div className="text-center py-8">
        <p className="text-[var(--text-secondary)] text-sm">Sin evaluaciones Cyrano todavía.</p>
        <p className="text-[var(--text-secondary)] text-xs mt-2 italic">
          Usa el chat para ejecutar el diagnóstico.
        </p>
      </div>
    );
  }

  const latest = evaluations[0];
  const prev   = evaluations[1] ?? null;
  const sections = latest.sections ?? {};
  const gaps = latest.feedback?.gaps ?? [];
  const recs  = latest.feedback?.recommendations ?? [];

  const pointsNeeded = Math.max(0, 95.01 - latest.score).toFixed(1);

  return (
    <div className="space-y-4">
      {/* Score header */}
      <div className="rounded-lg bg-[var(--bg-tertiary)] border border-[var(--border-color)] p-3">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold text-[var(--text-primary)]">
            Evaluación v{latest.version}
          </span>
          <span className={`text-xs font-bold ${latest.score >= 95.01 ? "text-[var(--success)]" : latest.score >= 70 ? "text-[var(--warning)]" : "text-[var(--danger)]"}`}>
            {latest.score.toFixed(1)} / 100
          </span>
        </div>
        {latest.verdict && (
          <p className="text-[10px] text-[var(--text-secondary)] mt-1">{latest.verdict}</p>
        )}
        {latest.score < 95.01 && (
          <p className="text-[10px] text-[var(--accent)] mt-1">
            Faltan {pointsNeeded} pts para aprobar
          </p>
        )}
      </div>

      {/* Section breakdown */}
      {Object.keys(sections).length > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-[var(--accent)] mb-2">Desglose por sección</h4>
          <div className="rounded-lg border border-[var(--border-color)] overflow-hidden">
            <table className="w-full text-[10px]">
              <thead>
                <tr className="bg-[var(--bg-tertiary)] text-[var(--text-secondary)]">
                  <th className="text-left px-2 py-1.5 font-medium">Sección</th>
                  <th className="text-center px-2 py-1.5 font-medium">Nota</th>
                  <th className="text-center px-2 py-1.5 font-medium">Aporte</th>
                  <th className="text-center px-2 py-1.5 font-medium">Etiqueta</th>
                  {prev && <th className="text-center px-2 py-1.5 font-medium">vs v{prev.version}</th>}
                </tr>
              </thead>
              <tbody>
                {SECTION_KEYS.map((key) => {
                  const note = sections[key as keyof typeof sections];
                  if (note === undefined) return null;
                  const label = getSectionLabel(note);
                  const aporte = ((note / 6) * 10).toFixed(1);
                  const prevNote = prev?.sections?.[key as keyof typeof prev.sections];
                  const delta = prevNote !== undefined ? note - prevNote : null;
                  return (
                    <tr key={key} className="border-t border-[var(--border-color)]">
                      <td className="px-2 py-1.5 text-[var(--text-primary)]">
                        {SECTION_META[key]}
                      </td>
                      <td className="px-2 py-1.5 text-center font-semibold text-[var(--text-primary)]">
                        {note}/10
                      </td>
                      <td className="px-2 py-1.5 text-center text-[var(--text-secondary)]">
                        {aporte}
                      </td>
                      <td className={`px-2 py-1.5 text-center font-medium ${labelColor(label)}`}>
                        {label}
                      </td>
                      {prev && (
                        <td className={`px-2 py-1.5 text-center ${delta === null ? "text-[var(--text-secondary)]" : delta > 0 ? "text-[var(--success)]" : delta < 0 ? "text-[var(--danger)]" : "text-[var(--text-secondary)]"}`}>
                          {delta === null ? "—" : delta > 0 ? `+${delta.toFixed(1)}` : delta < 0 ? delta.toFixed(1) : "="}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Gaps */}
      {gaps.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-[var(--danger)] mb-2">Brechas identificadas</h4>
          <ul className="space-y-1">
            {gaps.map((gap, i) => (
              <li key={i} className="text-[10px] text-[var(--text-secondary)] flex gap-1.5">
                <span className="text-[var(--danger)] flex-shrink-0">•</span>
                <span>{gap}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Recommendations */}
      {recs.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-[var(--accent)] mb-2">Recomendaciones</h4>
          <ol className="space-y-1">
            {recs.map((rec, i) => (
              <li key={i} className="text-[10px] text-[var(--text-secondary)] flex gap-1.5">
                <span className="text-[var(--accent)] flex-shrink-0 font-semibold">{i + 1}.</span>
                <span>{rec}</span>
              </li>
            ))}
          </ol>
        </div>
      )}

      {/* History summary */}
      {evaluations.length > 1 && (
        <div>
          <h4 className="text-xs font-semibold text-[var(--text-secondary)] mb-2">
            Historial ({evaluations.length} evaluaciones)
          </h4>
          <div className="space-y-1">
            {evaluations.map((ev) => (
              <div key={ev.id} className="flex items-center justify-between text-[10px] text-[var(--text-secondary)]">
                <span>v{ev.version} — {new Date(ev.created_at).toLocaleDateString("es")}</span>
                <span className={`font-semibold ${ev.score >= 95.01 ? "text-[var(--success)]" : ev.score >= 70 ? "text-[var(--warning)]" : "text-[var(--danger)]"}`}>
                  {ev.score.toFixed(1)}/100
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Existing helpers ──────────────────────────────────────────────────────────
function extractText(data: unknown): string | undefined {
  if (!data) return undefined;
  if (typeof data === "string") return data;
  if (data.text && typeof data.text === "string") return (data as { text: string }).text;
  return undefined;
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

function SectionContent({
  title,
  content,
  placeholder,
}: {
  title: string;
  content: string | undefined;
  placeholder: string;
}) {
  return (
    <div>
      <h4 className="text-xs font-semibold text-[var(--accent)] mb-3">{title}</h4>
      {content ? (
        <div className="prose-review text-xs text-[var(--text-secondary)] leading-relaxed">
          <ReactMarkdown>{content}</ReactMarkdown>
        </div>
      ) : (
        <div className="text-center py-6">
          <p className="text-[var(--text-secondary)] text-xs italic">{placeholder}</p>
        </div>
      )}
    </div>
  );
}

function MethodologyStatus({
  problemDef,
  objectives,
  methodology,
  timeline,
  budgetText,
}: {
  problemDef?: string;
  objectives?: string;
  methodology?: string;
  timeline?: string;
  budgetText?: string;
}) {
  const sections = [
    { name: "1. Problema", done: !!problemDef },
    { name: "2. Objetivos", done: !!objectives },
    { name: "3. Cadena de Valor", done: !!methodology },
    { name: "4. Cronograma", done: !!timeline },
    { name: "5. Presupuesto", done: !!budgetText },
  ];
  const completed = sections.filter((s) => s.done).length;

  return (
    <div>
      <h4 className="text-xs font-semibold text-[var(--accent)] mb-2">
        Progreso de la Metodología ({completed}/{sections.length})
      </h4>
      <div className="space-y-1">
        {sections.map((s) => (
          <div key={s.name} className="flex items-center gap-2 text-xs">
            <span className={s.done ? "text-[var(--success)]" : "text-[var(--text-secondary)] opacity-50"}>
              {s.done ? "✓" : "○"}
            </span>
            <span className={s.done ? "text-[var(--text-primary)]" : "text-[var(--text-secondary)]"}>
              {s.name}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
