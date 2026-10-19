import { ArrowPathIcon } from "@heroicons/react/24/outline";
import { useMutation } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { describeError, postMessage } from "../../api/client";
import { LinkButton } from "@/components/LinkButton";
import { PageHeader } from "@/components/PageHeader";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Bubble, BubbleContent } from "@/components/ui/bubble";
import { Button } from "@/components/ui/button";
import { Message, MessageContent } from "@/components/ui/message";
import {
  MessageScroller,
  MessageScrollerButton,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerProvider,
  MessageScrollerViewport,
} from "@/components/ui/message-scroller";
import { Card } from "../cards/Card";
import { RETRYABLE_STATES } from "../cards/RetryPlan";
import { useProjectEvents } from "../events/useProjectEvents";
import { foldExecutions, type TimelineItem } from "../events/timeline";
import { useProjects } from "../projects/useProjects";
import { MessageInput } from "./MessageInput";
import { TurnTrace } from "./TurnTrace";
import { useStaggered } from "./useStaggered";

/** Durée pendant laquelle la réflexion reste visible avant la suite (cf. TurnTrace). */
const TRACE_MS = 1800;

function readFirstMessage(state: unknown): string | null {
  if (typeof state === "object" && state !== null && "firstMessage" in state) {
    const { firstMessage } = state;
    if (typeof firstMessage === "string" && firstMessage !== "") return firstMessage;
  }
  return null;
}

/**
 * Texte à renvoyer pour relancer la dernière exécution du projet (plan ou exécution seule) : le dernier
 * message utilisateur qui la précède. Le flux n'expose pas de lien message -> plan, d'où ce choix.
 */
export function findRetry(items: TimelineItem[]): { key: string; text: string } | null {
  const isRun = (i: TimelineItem) =>
    i.kind === "card" && (i.card.kind === "plan" || i.card.kind === "execution");
  const last = items.map(isRun).lastIndexOf(true);
  const item = items[last];
  if (item?.kind !== "card") return null;
  const state =
    item.execution?.card.state ?? (item.card.kind === "execution" ? item.card.state : "");
  const stale =
    item.card.kind === "plan" &&
    (item.card.status === "invalidated" || item.card.status === "expired");
  if (!stale && !RETRYABLE_STATES.includes(state)) return null;
  const users = items.slice(0, last).filter((i) => i.kind === "message" && i.role === "user");
  const message = users[users.length - 1];
  return message?.kind === "message" ? { key: item.key, text: message.text } : null;
}

function TimelineEntry({
  item,
  projectId,
  retryText,
}: {
  item: TimelineItem;
  projectId: string;
  retryText?: string;
}) {
  switch (item.kind) {
    case "message":
      return item.role === "user" ? (
        <Message align="end">
          <MessageContent>
            <Bubble variant="secondary" align="end">
              <BubbleContent className="whitespace-pre-wrap">
                <span className="sr-only">Vous : </span>
                {item.text}
              </BubbleContent>
            </Bubble>
          </MessageContent>
        </Message>
      ) : (
        <Message align="start">
          <MessageContent>
            <Bubble variant="ghost">
              <BubbleContent className="whitespace-pre-wrap">
                <span className="sr-only">Foreman : </span>
                {item.text}
              </BubbleContent>
            </Bubble>
          </MessageContent>
        </Message>
      );
    case "trace":
      return <TurnTrace status={item.status} tools={item.tools} />;
    case "card":
      return (
        <Card
          card={item.card}
          projectId={projectId}
          logs={item.execution?.logs ?? item.logs}
          execution={item.execution?.card}
          retryText={retryText}
        />
      );
    case "error":
      return (
        <Alert variant="destructive">
          <AlertDescription>{item.message}</AlertDescription>
        </Alert>
      );
  }
}

export function ProjectPage({ projectId }: { projectId: string }) {
  const location = useLocation();
  const navigate = useNavigate();
  const { projects } = useProjects();
  const { items: events, turnRunning, connection, retry } = useProjectEvents(projectId);
  const items = useMemo(() => foldExecutions(events), [events]);
  const retryTarget = useMemo(() => findRetry(items), [items]);
  const visible = useStaggered(items, (previous) => (previous.kind === "trace" ? TRACE_MS : 450));
  const [draft, setDraft] = useState("");
  const firstMessage = useRef(readFirstMessage(location.state));
  const send = useMutation({ mutationFn: (text: string) => postMessage(projectId, text) });
  const sendMessage = send.mutateAsync;
  const title = projects.find((p) => p.id === projectId)?.title || "Projet";

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

  async function submit() {
    await send.mutateAsync(draft.trim());
    setDraft("");
  }

  if (connection.status === "error") {
    const notFound = connection.reason === "not_found";
    return (
      <>
        <PageHeader>{title}</PageHeader>
        <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col items-start gap-4 px-4 py-8">
          <p role="alert">
            {notFound
              ? "Projet introuvable. Il a peut-être été supprimé."
              : "Impossible de joindre le projet pour le moment."}
          </p>
          {notFound ? (
            <LinkButton to="/">Retour à l'accueil</LinkButton>
          ) : (
            <Button type="button" onClick={retry}>
              <ArrowPathIcon data-icon="inline-start" />
              Réessayer
            </Button>
          )}
        </main>
      </>
    );
  }

  const connecting = connection.status === "connecting" && items.length === 0;
  // Entre l'envoi et le premier événement du serveur : la réflexion est déjà affichée.
  const awaitingServer = send.isPending && !turnRunning && visible.length === items.length;

  return (
    <>
      <PageHeader>{title}</PageHeader>
      <div className="flex min-h-0 w-full flex-1 flex-col">
        {connection.status === "reconnecting" ? (
          <p role="status" className="mx-auto w-full max-w-3xl px-4 pt-3 text-sm">
            Connexion interrompue, reconnexion en cours…
          </p>
        ) : null}
        {connecting ? (
          <p role="status" className="mx-auto w-full max-w-3xl px-4 pt-3 text-sm">
            Connexion au projet…
          </p>
        ) : null}
        {!connecting && items.length === 0 ? (
          <p className="mx-auto w-full max-w-3xl px-4 pt-3 text-sm">
            Aucun message pour l'instant. Décrivez ce que vous voulez faire.
          </p>
        ) : null}
        <div className="min-h-0 flex-1">
          <MessageScrollerProvider>
            <MessageScroller aria-label="Conversation" role="log">
              <MessageScrollerViewport>
                <MessageScrollerContent className="mx-auto w-full max-w-3xl gap-4 px-4 py-4">
                  {visible.map((item) => (
                    <MessageScrollerItem
                      key={item.key}
                      messageId={item.key}
                      scrollAnchor={item.kind === "message" && item.role === "user"}
                      className="motion-safe:animate-in motion-safe:duration-200 motion-safe:fade-in-0"
                    >
                      <TimelineEntry
                        item={item}
                        projectId={projectId}
                        retryText={retryTarget?.key === item.key ? retryTarget.text : undefined}
                      />
                    </MessageScrollerItem>
                  ))}
                  {awaitingServer ? (
                    <MessageScrollerItem
                      messageId="pending"
                      className="motion-safe:animate-in motion-safe:duration-200 motion-safe:fade-in-0"
                    >
                      <TurnTrace status="running" tools={[]} />
                    </MessageScrollerItem>
                  ) : null}
                </MessageScrollerContent>
              </MessageScrollerViewport>
              <MessageScrollerButton />
            </MessageScroller>
          </MessageScrollerProvider>
        </div>
        <div className="mx-auto w-full max-w-3xl px-4 pb-4">
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
        </div>
      </div>
    </>
  );
}
