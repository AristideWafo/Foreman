import { Route, Routes, useParams } from "react-router-dom";
import { HomePage } from "./features/chat/HomePage";
import { ProjectPage } from "./features/chat/ProjectPage";
import { LinkButton } from "@/components/LinkButton";

function ProjectRoute() {
  const { projectId } = useParams();
  // `key` : changer de projet remonte la page, donc recrée le flux et l'état local.
  return projectId ? <ProjectPage key={projectId} projectId={projectId} /> : <NotFoundPage />;
}

function NotFoundPage() {
  return (
    <main className="mx-auto flex min-h-dvh max-w-3xl flex-col items-start justify-center gap-4 px-4">
      <h1 className="text-2xl font-semibold">Page introuvable</h1>
      <LinkButton to="/">Retour à l'accueil</LinkButton>
    </main>
  );
}

export function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/projects/:projectId" element={<ProjectRoute />} />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
