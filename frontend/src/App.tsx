import { useEffect } from "react";
import { Route, Routes, useNavigate, useParams } from "react-router-dom";
import { setUnauthorizedHandler } from "./api/client";
import { InvitePage } from "./features/auth/InvitePage";
import { LoginPage } from "./features/auth/LoginPage";
import { AppShell } from "./features/layout/AppShell";
import { HomePage } from "./features/chat/HomePage";
import { ProjectPage } from "./features/chat/ProjectPage";
import { LinkButton } from "@/components/LinkButton";
import { PageHeader } from "@/components/PageHeader";

function ProjectRoute() {
  const { projectId } = useParams();
  // `key` : changer de projet remonte la page, donc recrée le flux et l'état local.
  return projectId ? <ProjectPage key={projectId} projectId={projectId} /> : <NotFoundPage />;
}

function NotFoundPage() {
  return (
    <>
      <PageHeader>Page introuvable</PageHeader>
      <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col items-start gap-4 px-4 py-8">
        <p>Cette page n'existe pas.</p>
        <LinkButton to="/">Retour à l'accueil</LinkButton>
      </main>
    </>
  );
}

export function App() {
  const navigate = useNavigate();
  // Tout 401 renvoie vers la connexion.
  useEffect(() => {
    setUnauthorizedHandler(() => void navigate("/login", { replace: true }));
    return () => setUnauthorizedHandler(null);
  }, [navigate]);
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/invite/:token" element={<InvitePage />} />
      <Route path="/accept-invite" element={<InvitePage />} />
      <Route element={<AppShell />}>
        <Route path="/" element={<HomePage />} />
        <Route path="/projects/:projectId" element={<ProjectRoute />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
