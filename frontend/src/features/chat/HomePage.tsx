import { SparklesIcon } from "@heroicons/react/24/outline";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { createProject, describeError } from "../../api/client";
import { NativeSelect } from "@/components/NativeSelect";
import { PageHeader } from "@/components/PageHeader";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Label } from "@/components/ui/label";
import { useMe } from "../cards/useMe";
import { PROJECTS_KEY } from "../projects/useProjects";
import { useTeamSelection } from "../projects/useTeamSelection";
import { MessageInput } from "./MessageInput";
import { PromptSuggestions } from "./PromptSuggestions";

const TITLE_MAX = 60;

export function HomePage() {
  const navigate = useNavigate();
  const state: unknown = useLocation().state;
  const notice =
    typeof state === "object" &&
    state !== null &&
    "notice" in state &&
    typeof state.notice === "string"
      ? state.notice
      : null;
  const queryClient = useQueryClient();
  const [text, setText] = useState("");
  const teams = useMe()?.teams ?? [];
  // `null` : on suit la sélection de la barre latérale (une seule équipe active = défaut).
  // Vide : le serveur choisit l'équipe par défaut (personnelle, ou de développement).
  const [choice, setChoice] = useState<string | null>(null);
  const { stored } = useTeamSelection();
  const active = stored.filter((id) => teams.some((t) => t.id === id));
  const teamId = choice ?? (stored.length === 1 && active.length === 1 ? active[0] : "");
  const create = useMutation({
    mutationFn: (title: string) => createProject({ title, team_id: teamId || null }),
  });

  async function start(message: string) {
    const project = await create.mutateAsync(message.slice(0, TITLE_MAX));
    await queryClient.invalidateQueries({ queryKey: PROJECTS_KEY });
    // La page du projet ouvre le flux d'événements, puis poste ce premier message.
    await navigate(`/projects/${project.id}`, { state: { firstMessage: message } });
  }

  return (
    <>
      <PageHeader>Nouveau projet</PageHeader>
      <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col justify-center gap-10 px-4 py-8">
        {notice ? (
          <Alert>
            <AlertDescription>{notice}</AlertDescription>
          </Alert>
        ) : null}
        <div className="flex flex-col items-center gap-2 text-center">
          <p className="flex items-center gap-2 text-sm font-medium">
            <SparklesIcon aria-hidden="true" />
            Bonjour
          </p>
          <h2 className="text-3xl font-semibold tracking-tight">Que voulez-vous faire ?</h2>
          <p className="text-sm">
            Décrivez votre demande : Foreman propose un plan que vous relisez avant toute action.
          </p>
        </div>
        {teams.length > 0 ? (
          <div className="flex items-center gap-2 self-center">
            <Label htmlFor="project-team">Équipe du projet</Label>
            <NativeSelect
              id="project-team"
              className="w-56"
              value={teamId}
              onChange={(e) => setChoice(e.target.value)}
            >
              <option value="">Équipe par défaut</option>
              {teams.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </NativeSelect>
          </div>
        ) : null}
        <MessageInput
          value={text}
          onChange={setText}
          onSend={() => start(text.trim())}
          label="Votre demande"
          submitLabel="Démarrer"
          placeholder="Par exemple : déployer mon application sur un nouveau serveur"
          busy={create.isPending}
          error={create.isError ? describeError(create.error) : null}
        />
        <PromptSuggestions
          disabled={create.isPending}
          onPick={(suggestion) => void start(suggestion).catch(() => undefined)}
        />
      </main>
    </>
  );
}
