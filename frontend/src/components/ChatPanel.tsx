"use client";

import { useState, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import { sendMessageStream, getConversation, uploadDocument, waitForDocumentIndexed, saveConversation, deleteConversation, ApiError } from "@/lib/api";
import type { StreamEvent } from "@/lib/api";
import type { ChatMessage } from "@/lib/types";
import { Send, Loader2, Menu, Paperclip, X, FileText, Save, Check, Square, Plus, Trash2, Copy } from "lucide-react";

function generateId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  // Fallback for non-secure contexts (HTTP over LAN, etc.)
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}

interface ChatPanelProps {
  userId: string;
  conversationId: string | null;
  projectId: string | null;
  onConversationCreated: (id: string) => void;
  onChatComplete: () => void;
  onScoreUpdate: (score: number | null) => void;
  onToggleSidebar: () => void;
  sidebarOpen: boolean;
  onNewConversation: () => void;
  onDeleteConversation: (conversationId: string) => void;
}

interface PendingFile {
  file: File;
  name: string;
  size: number;
  uploading: boolean;
  uploaded: boolean;
  error: string | null;
}

function AssistantMessage({ msg }: { msg: ChatMessage }) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    await navigator.clipboard.writeText(msg.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
      <div
        className={`group relative max-w-[80%] rounded-2xl px-4 py-3 ${
          msg.role === "user"
            ? "bg-[var(--accent)] text-white rounded-br-md"
            : "bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-bl-md"
        }`}
      >
        {msg.role === "assistant" ? (
          <>
            <div className="chat-prose prose prose-invert max-w-none leading-relaxed [&_p]:my-1.5 [&_ul]:my-1.5 [&_ol]:my-1.5 [&_li]:my-1">
              <ReactMarkdown
                components={{
                  a: ({ href, children }) => (
                    <a href={href} target="_blank" rel="noopener noreferrer">
                      {children}
                    </a>
                  ),
                }}
              >
                {msg.content}
              </ReactMarkdown>
            </div>
            <button
              onClick={handleCopy}
              className="absolute top-2 right-2 p-1 rounded opacity-0 group-hover:opacity-100 transition-opacity text-[var(--text-secondary)] hover:text-[var(--accent)] hover:bg-[var(--bg-tertiary)]"
              title="Copiar respuesta"
            >
              {copied ? <Check className="w-3.5 h-3.5 text-green-400" /> : <Copy className="w-3.5 h-3.5" />}
            </button>
          </>
        ) : (
          <p className="text-base whitespace-pre-wrap">{msg.content}</p>
        )}

        {/* Tool calls indicator — expandable list */}
        {msg.tool_calls && Array.isArray(msg.tool_calls) && (msg.tool_calls as Array<{ tool: string }>).length > 0 && (
          <details className="mt-2 pt-2 border-t border-[var(--border-color)]">
            <summary className="text-[10px] text-[var(--text-secondary)] cursor-pointer select-none flex items-center gap-1 hover:text-[var(--accent)] transition-colors">
              ⚡ {(msg.tool_calls as Array<{ tool: string }>).length} herramienta(s) utilizada(s)
            </summary>
            <ul className="mt-1.5 space-y-0.5 pl-1">
              {(msg.tool_calls as Array<{ tool: string }>).map((tc, i) => (
                <li key={i} className="text-[10px] text-[var(--text-secondary)] flex items-center gap-1.5">
                  <span className="text-green-400">✓</span>
                  <code className="font-mono">{tc.tool}</code>
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </div>
  );
}

export function ChatPanel({
  userId,
  conversationId,
  projectId,
  onConversationCreated,
  onChatComplete,
  onScoreUpdate,
  onToggleSidebar,
  sidebarOpen,
  onNewConversation,
  onDeleteConversation,
}: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [streamingContent, setStreamingContent] = useState("");
  const [toolStatus, setToolStatus] = useState<string | null>(null);
  const [pendingFiles, setPendingFiles] = useState<PendingFile[]>([]);
  const [uploadingFiles, setUploadingFiles] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const submittingRef = useRef(false);

  useEffect(() => {
    if (conversationId) {
      loadConversation(conversationId);
    } else {
      setMessages([]);
    }
  }, [conversationId]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function loadConversation(convId: string) {
    try {
      const data = await getConversation(userId, convId);
      if (data.messages) {
        setMessages(data.messages);
      }
    } catch {
      // Conversation not found
    }
  }

  function handleFileSelect() {
    fileInputRef.current?.click();
  }

  function handleFilesChosen(e: React.ChangeEvent<HTMLInputElement>) {
    const files = e.target.files;
    if (!files) return;
    const newFiles: PendingFile[] = Array.from(files).map((f) => ({
      file: f,
      name: f.name,
      size: f.size,
      uploading: false,
      uploaded: false,
      error: null,
    }));
    setPendingFiles((prev) => [...prev, ...newFiles]);
    // Reset input so the same file can be selected again
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  function removePendingFile(index: number) {
    setPendingFiles((prev) => prev.filter((_, i) => i !== index));
  }

  async function uploadPendingFiles(): Promise<string[]> {
    if (!projectId || pendingFiles.length === 0) return [];
    setUploadingFiles(true);
    const uploadedNames: string[] = [];

    for (let i = 0; i < pendingFiles.length; i++) {
      const pf = pendingFiles[i];
      if (pf.uploaded) {
        uploadedNames.push(pf.name);
        continue;
      }
      setPendingFiles((prev) =>
        prev.map((f, idx) => (idx === i ? { ...f, uploading: true } : f))
      );
      try {
        const docRecord = await uploadDocument(projectId, userId, pf.file);
        // Wait for the vector-store indexing to complete before sending the
        // message so the agent can find the file via file_search.
        setPendingFiles((prev) =>
          prev.map((f, idx) => (idx === i ? { ...f, uploading: false, uploaded: false } : f))
        );
        setToolStatus(`⏳ Indexando ${pf.name}…`);
        await waitForDocumentIndexed(projectId, docRecord.id);
        setToolStatus(null);
        uploadedNames.push(pf.name);
        setPendingFiles((prev) =>
          prev.map((f, idx) =>
            idx === i ? { ...f, uploading: false, uploaded: true } : f
          )
        );
      } catch (err) {
        setPendingFiles((prev) =>
          prev.map((f, idx) =>
            idx === i
              ? { ...f, uploading: false, error: "Error al subir" }
              : f
          )
        );
      }
    }
    setUploadingFiles(false);
    return uploadedNames;
  }

  function formatFileSize(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim() || loading || submittingRef.current) return;
    submittingRef.current = true;

    const baseText = input.trim();

    // Show the user message immediately (optimistic update)
    const userMessage: ChatMessage = {
      id: generateId(),
      role: "user",
      content: baseText,
      tool_calls: null,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
    setLoading(true);
    setStreamingContent("");
    setToolStatus(null);

    // Upload pending files (user sees ⏳ Indexando... while message is already visible)
    let messageText = baseText;
    if (pendingFiles.length > 0 && projectId) {
      const uploadedNames = await uploadPendingFiles();
      if (uploadedNames.length > 0) {
        messageText += `\n\n[Documentos adjuntos: ${uploadedNames.join(", ")}]`;
      }
      setPendingFiles([]);
    }

    const controller = new AbortController();
    abortControllerRef.current = controller;

    let accumulatedContent = "";
    let finalToolCalls: unknown = null;
    let cancelled = false;

    try {
      await sendMessageStream(
        {
          user_id: userId,
          message: userMessage.content,
          conversation_id: conversationId || undefined,
          project_id: projectId || undefined,
        },
        (event: StreamEvent) => {
          switch (event.type) {
            case "meta":
              if (!conversationId) {
                onConversationCreated(event.conversation_id);
              }
              break;
            case "tool":
              setToolStatus(
                event.status === "running"
                  ? `⚡ Ejecutando ${event.name}...`
                  : null
              );
              break;
            case "delta":
              accumulatedContent += event.content;
              setStreamingContent(accumulatedContent.replace(/[\[【]?fileciteturn\d+file\d+[\]】]?/g, ""));
              break;
            case "done":
              finalToolCalls = event.tool_calls;
              if (event.cyrano_score !== null) {
                onScoreUpdate(event.cyrano_score);
              }
              break;
            case "error":
              accumulatedContent = event.content;
              break;
          }
        },
        controller.signal,
      );

      // Add the completed message only when not cancelled
      if (!controller.signal.aborted) {
        const assistantMessage: ChatMessage = {
          id: generateId(),
          role: "assistant",
          content: accumulatedContent || "No se recibió respuesta.",
          tool_calls: finalToolCalls as Record<string, unknown> | null,
          created_at: new Date().toISOString(),
        };
        setMessages((prev) => [...prev, assistantMessage]);
      }
    } catch (err) {
      // AbortError is expected when the user cancels — don't show an error message
      if (err instanceof DOMException && err.name === "AbortError") {
        cancelled = true;
        if (accumulatedContent) {
          // Show whatever was already streamed, marked as partial
          setMessages((prev) => [
            ...prev,
            {
              id: generateId(),
              role: "assistant",
              content: accumulatedContent + "\n\n*[Respuesta cancelada]*",
              tool_calls: null,
              created_at: new Date().toISOString(),
            },
          ]);
        }
      } else {
        const errorText =
          err instanceof ApiError
            ? err.status >= 500
              ? "Error del servidor. Por favor, inténtalo de nuevo en unos momentos."
              : err.message
            : err instanceof Error
              ? err.message
              : "Error inesperado. Por favor, inténtalo de nuevo.";

        setMessages((prev) => [
          ...prev,
          {
            id: generateId(),
            role: "assistant",
            content: errorText,
            tool_calls: null,
            created_at: new Date().toISOString(),
          },
        ]);
      }
    } finally {
      abortControllerRef.current = null;
      submittingRef.current = false;
      setLoading(false);
      setStreamingContent("");
      setToolStatus(null);
      if (!cancelled) onChatComplete();
    }
  }

  function handleCancel() {
    abortControllerRef.current?.abort();
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      // Trigger the form's submit event rather than calling handleSubmit directly
      // to avoid double-fire from both keydown and form onSubmit.
      const form = (e.target as HTMLElement).closest("form");
      form?.requestSubmit();
    }
  }

  // Auto-resize textarea
  function handleInputChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setInput(e.target.value);
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height =
        Math.min(textareaRef.current.scrollHeight, 200) + "px";
    }
  }

  return (
    <div className="flex-1 flex flex-col bg-[var(--bg-primary)]">
      {/* Header */}
      <header className="flex items-center gap-3 px-4 py-3 border-b border-[var(--border-color)] bg-[var(--bg-secondary)]">
        <button
          onClick={onToggleSidebar}
          className="p-1.5 rounded-lg hover:bg-[var(--bg-tertiary)] transition-colors"
        >
          <Menu className="w-5 h-5" />
        </button>
        <div className="flex-1">
          <h2 className="text-base font-semibold">
            {conversationId ? "Conversación Activa" : "Nueva Conversación"}
          </h2>
          {projectId && (
            <p className="text-sm text-[var(--text-secondary)]">
              Proyecto vinculado
            </p>
          )}
        </div>

        {/* New conversation button */}
        <button
          onClick={onNewConversation}
          disabled={loading}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition-colors text-xs border border-[var(--border-color)] text-[var(--text-secondary)] hover:text-[var(--accent)] hover:bg-[var(--bg-tertiary)] disabled:opacity-50"
          title="Nueva conversación"
        >
          <Plus className="w-4 h-4" />
          <span>Nueva</span>
        </button>

        {/* Save button */}
        {conversationId && (
          <button
            onClick={async () => {
              if (saving) return;
              setSaving(true);
              setSaveStatus(null);
              try {
                const result = await saveConversation(userId, conversationId, projectId || undefined);
                setSaveStatus(result.message);
                onChatComplete();
                setTimeout(() => setSaveStatus(null), 4000);
              } catch (err) {
                setSaveStatus(err instanceof Error ? err.message : "Error al guardar");
                setTimeout(() => setSaveStatus(null), 4000);
              } finally {
                setSaving(false);
              }
            }}
            disabled={saving}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition-colors text-xs border ${
              saveStatus && !saveStatus.startsWith("Error") && !saveStatus.startsWith("La conversación")
                ? "border-green-600 text-green-400 bg-green-900/20"
                : "border-[var(--border-color)] text-[var(--text-secondary)] hover:text-[var(--accent)] hover:bg-[var(--bg-tertiary)]"
            } disabled:opacity-50`}
            title="Guardar conversación en el proyecto"
          >
            {saving ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : saveStatus && !saveStatus.startsWith("Error") && !saveStatus.startsWith("La conversación") ? (
              <Check className="w-4 h-4" />
            ) : (
              <Save className="w-4 h-4" />
            )}
            <span>{saveStatus || "Guardar"}</span>
          </button>
        )}

        {/* Delete conversation button */}
        {conversationId && (
          <button
            onClick={async () => {
              if (!window.confirm("¿Eliminar esta conversación? No se puede deshacer.")) return;
              try {
                await deleteConversation(userId, conversationId);
                onDeleteConversation(conversationId);
              } catch {
                // ignore
              }
            }}
            disabled={loading}
            className="p-1.5 rounded-lg text-[var(--text-secondary)] hover:text-red-400 hover:bg-red-900/20 transition-colors disabled:opacity-50"
            title="Eliminar conversación"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        )}
      </header>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-6 space-y-6">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center space-y-4">
            <div className="w-16 h-16 rounded-full bg-[var(--bg-tertiary)] flex items-center justify-center">
              <span className="text-3xl">🚀</span>
            </div>
            <div>
              <h3 className="text-lg font-semibold mb-2">¡Bienvenido a Pipidepulus AI!</h3>
              <p className="text-sm text-[var(--text-secondary)] max-w-md">
                Soy tu consultor experto en formulación de proyectos de alto impacto.
                Puedo ayudarte a:
              </p>
              <div className="mt-4 grid grid-cols-1 gap-2 max-w-sm mx-auto">
                {[
                  "🔍 Buscar convocatorias de financiamiento",
                  "📄 Analizar requisitos de convocatorias",
                  "📎 Subir documentos para análisis",
                  "✍️ Crear proyectos paso a paso",
                  "✅ Validar con el diagnóstico Cyrano",
                  "📝 Generar documentos Word profesionales",
                ].map((item, i) => (
                  <div
                    key={i}
                    className="text-sm text-left px-3 py-2 rounded-lg bg-[var(--bg-secondary)] border border-[var(--border-color)]"
                  >
                    {item}
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {messages.map((msg) => (
          <AssistantMessage key={msg.id} msg={msg} />
        ))}

        {loading && streamingContent && (
          <div className="flex justify-start">
            <div className="max-w-[80%] bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-2xl rounded-bl-md px-4 py-3">
              <div className="chat-prose prose prose-invert max-w-none leading-relaxed [&_p]:my-1.5 [&_ul]:my-1.5 [&_ol]:my-1.5 [&_li]:my-1">
                <ReactMarkdown
                  components={{
                    a: ({ href, children }) => (
                      <a href={href} target="_blank" rel="noopener noreferrer">
                        {children}
                      </a>
                    ),
                  }}
                >
                  {streamingContent}
                </ReactMarkdown>
              </div>
            </div>
          </div>
        )}

        {loading && !streamingContent && (
          <div className="flex justify-start">
            <div className="bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-2xl rounded-bl-md px-4 py-3">
              <div className="flex items-center gap-2 text-base text-[var(--text-secondary)]">
                <Loader2 className="w-4 h-4 animate-spin" />
                {toolStatus || "Analizando..."}
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="p-4 border-t border-[var(--border-color)] bg-[var(--bg-secondary)]">
        {/* Pending files preview */}
        {pendingFiles.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-3">
            {pendingFiles.map((pf, i) => (
              <div
                key={i}
                className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs border ${
                  pf.error
                    ? "bg-red-900/20 border-red-700 text-red-400"
                    : pf.uploaded
                    ? "bg-green-900/20 border-green-700 text-green-400"
                    : "bg-[var(--bg-tertiary)] border-[var(--border-color)] text-[var(--text-secondary)]"
                }`}
              >
                <FileText className="w-3.5 h-3.5 flex-shrink-0" />
                <span className="truncate max-w-[150px]">{pf.name}</span>
                <span className="text-[10px] opacity-70">{formatFileSize(pf.size)}</span>
                {pf.uploading && <Loader2 className="w-3 h-3 animate-spin" />}
                {pf.uploaded && <span className="text-green-400">✓</span>}
                {!pf.uploading && !pf.uploaded && (
                  <button onClick={() => removePendingFile(i)} className="hover:text-red-400">
                    <X className="w-3 h-3" />
                  </button>
                )}
              </div>
            ))}
          </div>
        )}

        {/* No project warning */}
        {pendingFiles.length > 0 && !projectId && (
          <p className="text-xs text-[var(--warning)] mb-2">
            ⚠ Selecciona un proyecto en la barra lateral para poder subir documentos
          </p>
        )}

        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.docx,.doc,.txt,.md"
          multiple
          onChange={handleFilesChosen}
          className="hidden"
        />

        <form onSubmit={handleSubmit} className="flex items-end gap-2">
          <button
            type="button"
            onClick={handleFileSelect}
            disabled={loading}
            className="p-3 rounded-xl text-[var(--text-secondary)] hover:text-[var(--accent)] hover:bg-[var(--bg-tertiary)] disabled:opacity-50 transition-colors"
            title="Adjuntar documento (PDF, DOCX, TXT)"
          >
            <Paperclip className="w-4 h-4" />
          </button>
          <div className="flex-1 relative">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={handleInputChange}
              onKeyDown={handleKeyDown}
              placeholder="Escribe tu mensaje..."
              rows={1}
              className="w-full resize-none rounded-xl bg-[var(--bg-primary)] border border-[var(--border-color)] px-4 py-3 pr-10 text-base focus:outline-none focus:border-[var(--accent)] transition-colors placeholder:text-[var(--text-secondary)]"
            />
          </div>
          <button
            type="submit"
            disabled={loading || !input.trim()}
            className="p-3 rounded-xl bg-[var(--accent)] text-white hover:bg-[var(--accent-hover)] disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
          </button>
          {loading && (
            <button
              type="button"
              onClick={handleCancel}
              title="Cancelar respuesta"
              className="p-3 rounded-xl border border-red-600 text-red-400 hover:bg-red-900/20 transition-colors"
            >
              <Square className="w-4 h-4" />
            </button>
          )}
        </form>
        <p className="text-xs text-[var(--text-secondary)] mt-2 text-center">
          Pipidepulus AI puede cometer errores. Verifica la información importante.
        </p>
      </div>
    </div>
  );
}
