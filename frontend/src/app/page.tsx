"use client";

import { useState, useEffect } from "react";
import { Sidebar } from "@/components/Sidebar";
import { ChatPanel } from "@/components/ChatPanel";
import { ReviewPanel } from "@/components/ReviewPanel";
import type { ProjectListItem, Conversation } from "@/lib/types";
import { createUser, listProjects, listConversations, deleteProject, deleteConversation } from "@/lib/api";

const DEMO_USER_EMAIL = "demo@pipidepulus.ai";
const DEMO_USER_NAME = "Demo User";

export default function Home() {
  const [projects, setProjects] = useState<ProjectListItem[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeProjectId, setActiveProjectId] = useState<string | null>(null);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [activeView, setActiveView] = useState<"chat" | "review">("chat");
  const [cyranoScore, setCyranoScore] = useState<number | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [userId, setUserId] = useState<string | null>(null);
  const [connectionError, setConnectionError] = useState(false);
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    initUser();
  }, []);

  useEffect(() => {
    if (userId) loadData();
  }, [userId]);

  async function initUser() {
    try {
      setConnectionError(false);
      const user = await createUser({ name: DEMO_USER_NAME, email: DEMO_USER_EMAIL });
      setUserId(user.id);
    } catch {
      setConnectionError(true);
    }
  }

  async function loadData() {
    if (!userId) return;
    try {
      setLoadError(false);
      const [proj, convs] = await Promise.all([
        listProjects(userId),
        listConversations(userId),
      ]);
      setProjects(proj);
      setConversations(convs);
    } catch {
      setLoadError(true);
    }
  }

  function handleConversationCreated(id: string) {
    setActiveConversationId(id);
  }

  function handleProjectChatSelect(projectId: string, conversationId: string | null) {
    setActiveProjectId(projectId);
    setActiveConversationId(conversationId);
    setActiveView("chat");
    const project = projects.find((p) => p.id === projectId);
    if (project?.cyrano_score) setCyranoScore(project.cyrano_score);
  }

  function handleProjectReviewSelect(projectId: string) {
    setActiveProjectId(projectId);
    setActiveView("review");
    const project = projects.find((p) => p.id === projectId);
    if (project?.cyrano_score) setCyranoScore(project.cyrano_score);
  }

  async function handleDeleteProject(id: string) {
    try {
      await deleteProject(id);
      if (activeProjectId === id) {
        setActiveProjectId(null);
        setCyranoScore(null);
      }
      loadData();
    } catch {
      // ignore
    }
  }

  async function handleDeleteConversation(conversationId: string) {
    if (activeConversationId === conversationId) {
      setActiveConversationId(null);
    }
    await loadData();
  }

  function handleNewConversation() {
    setActiveConversationId(null);
  }

  function handleScoreUpdate(score: number | null) {
    setCyranoScore(score);
    // Auto-open the Review Panel so the Cyrano evaluation is immediately visible
    if (score !== null && activeProjectId) {
      setActiveView("review");
    }
  }

  return (
    <div className="flex h-screen overflow-hidden">
      {!userId ? (
        <div className="flex flex-col items-center justify-center w-full gap-4">
          {connectionError ? (
            <>
              <p className="text-red-400 text-sm">No se pudo conectar al servidor.</p>
              <button
                onClick={initUser}
                className="px-4 py-2 text-sm rounded-lg bg-[var(--accent)] text-white hover:opacity-90 transition-opacity"
              >
                Reintentar
              </button>
            </>
          ) : (
            <p className="text-gray-400">Conectando...</p>
          )}
        </div>
      ) : (
        <>
          {loadError && (
            <div className="absolute top-3 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 rounded-lg bg-[#2a1a1a] border border-red-800 px-4 py-2 text-sm text-red-400 shadow-lg">
              <span>Error al cargar proyectos y conversaciones.</span>
              <button
                onClick={loadData}
                className="underline hover:text-red-300 transition-colors"
              >
                Reintentar
              </button>
            </div>
          )}
          {/* Sidebar */}
          {sidebarOpen && (
            <Sidebar
              projects={projects}
              conversations={conversations}
              activeProjectId={activeProjectId}
              activeView={activeView}
              cyranoScore={cyranoScore}
              onProjectChatSelect={handleProjectChatSelect}
              onProjectReviewSelect={handleProjectReviewSelect}
              onDeleteProject={handleDeleteProject}
              onRefresh={loadData}
              userId={userId}
            />
          )}

          {/* Main Area */}
          <div className="flex flex-1 overflow-hidden">
            <ChatPanel
              userId={userId}
              conversationId={activeConversationId}
              projectId={activeProjectId}
              onConversationCreated={handleConversationCreated}
              onChatComplete={loadData}
              onScoreUpdate={handleScoreUpdate}
              onToggleSidebar={() => setSidebarOpen(!sidebarOpen)}
              sidebarOpen={sidebarOpen}
              onNewConversation={handleNewConversation}
              onDeleteConversation={handleDeleteConversation}
            />

            {/* Review Panel (split view) */}
            {activeView === "review" && activeProjectId && (
              <ReviewPanel
                projectId={activeProjectId}
                onClose={() => setActiveView("chat")}
              />
            )}
          </div>
        </>
      )}
    </div>
  );
}
