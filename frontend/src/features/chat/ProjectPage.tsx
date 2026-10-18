import { ArrowLeftIcon, ArrowPathIcon, SparklesIcon } from "@heroicons/react/24/outline";
import { useMutation } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { describeError, postMessage } from "../../api/client";
import { Card } from "../cards/Card";
import { useProjectEvents } from "../events/useProjectEvents";
import type { TimelineItem } from "../events/timeline";
import { MessageInput } from "./MessageInput";
import { LinkButton } from "@/components/LinkButton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";

function readFirstMessage(state: unknown): string | null {
  if (typeof state === "object" && state !== null && "firstMessage" in state) {
    const { firstMessage } = state;
    if (typeof firstMessage === "string" && firstMessage !== "") return firstMessage;
  }
  return null;
}

function TimelineEntry({ item }: { item: TimelineItem }) {
  switch (item.kind) {
    case "message":
      return item.role === "user" ? (
        <li className="flex justify-end">
          <p className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-sm bg-primary px-4 py-2 text-primary-foreground">
            <span className="sr-only">Vous : </span>
            {item.text}
          </p>
        </li>
      ) : (
        <li className="flex justify-start">
          <p className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-bl-sm border bg-card px-4 py-2 text-card-foreground">
            <span className="sr-only">Foreman : </span>
            {item.text}
          </p>
        </li>
      );
    case "card":
      return (
        <li>
          <Card card={item.card} />
        </li>
      );
    case "error":
      return (
        <li>
          <Alert variant="destructive">
            <AlertDescription>{item.message}</AlertDescription>
          </Alert>
        </li>
      );
  }
}

export function ProjectPage({ projectId }: { projectId: string }) {
  const location = useLocation();
  const navigate = useNavigate();
  const { items, turnRunning, connection, retry } = useProjectEvents(projectId);
  const [draft, setDraft] = useState("");
  const firstMessage = useRef(readFirstMessage(location.state));
  const endRef = useRef<HTMLLIElement>(null);
  const send = useMutation({ mutationFn: (text: string) => postMessage(projectId, text) });
  const sendMessage = send.mutateAsync;

  // Premier message venu de l'accueil : posté seulement une fois le flux ouvert.
  const streamOpen = connection.status === "open";
  useEffect(() => {
    const text = firstMessage.current;
    if (text === null || !streamOpen) return;
    firstMessage.current = null;
    // Efface l'état de navigation pour qu'un rechargement ne renvoie pas le message.
    void navigate(location.pathname, { replace: true, state: null });
    sendMessage(text).catch(() => setDraft(text));
  }, [streamOpen, navigate, location.pathname, sendMessage]);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end" });
  }, [items.length, turnRunning]);

  async function submit() {
    await send.mutateAsync(draft.trim());
    setDraft("");
  }

  const header = (
    <header className="flex items-center gap-3 border-b px-4 py-3">
      <LinkButton to="/" variant="ghost" size="sm">
        <ArrowLeftIcon aria-hidden="true" />
        Accueil
      </LinkButton>
      <h1 className="text-lg font-semibold">Foreman</h1>
    </header>
  );

  if (connection.status === "error") {
    const notFound = connection.reason === "not_found";
    return (
      <div className="mx-auto flex min-h-dvh max-w-3xl flex-col">
        {header}
        <main className="flex flex-1 flex-col items-start gap-4 px-4 py-8">
          <p role="alert">
            {notFound
              ? "Projet introuvable. Il a peut-être été supprimé."
              : "Impossible de joindre le projet pour le moment."}
          </p>
          {notFound ? (
            <LinkButton to="/">Retour à l'accueil</LinkButton>
          ) : (
            <Button type="button" onClick={retry}>
              <ArrowPathIcon aria-hidden="true" />
              Réessayer
            </Button>
          )}
        </main>
      </div>
    );
  }

  const connecting = connection.status === "connecting" && items.length === 0;

  return (
    <div className="mx-auto flex h-dvh max-w-3xl flex-col">
      {header}
      <ScrollArea className="min-h-0 flex-1">
        <main className="px-4 py-4">
          {connection.status === "reconnecting" ? (
            <p role="status" className="mb-3 text-sm text-amber-700 dark:text-amber-400">
              Connexion interrompue, reconnexion en cours…
            </p>
          ) : null}
          {connecting ? (
            <p role="status" className="text-muted-foreground">
              Connexion au projet…
            </p>
          ) : null}
          {!connecting && items.length === 0 ? (
            <p className="text-muted-foreground">
              Aucun message pour l'instant. Décrivez ce que vous voulez faire.
            </p>
          ) : null}
          <div role="log" aria-label="Conversation">
            <ol className="space-y-3">
              {items.map((item) => (
                <TimelineEntry key={item.key} item={item} />
              ))}
              {turnRunning ? (
                <li role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
                  <SparklesIcon className="size-4 motion-safe:animate-pulse" aria-hidden="true" />
                  Foreman prépare une réponse…
                </li>
              ) : null}
              <li ref={endRef} aria-hidden="true" />
            </ol>
          </div>
        </main>
      </ScrollArea>
      <footer className="border-t bg-muted/50 px-4 py-3">
        <MessageInput
          value={draft}
          onChange={setDraft}
          onSend={submit}
          label="Votre message"
          submitLabel="Envoyer"
          placeholder="Écrivez votre message"
          busy={send.isPending || turnRunning}
          error={send.isError ? describeError(send.error) : null}
        />
      </footer>
    </div>
  );
}
