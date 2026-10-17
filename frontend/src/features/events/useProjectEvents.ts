import { useCallback, useEffect, useReducer, useState } from "react";
import { ApiError, eventsUrl, getProject } from "../../api/client";
import { applyEvent, initialTimeline, parseEvent } from "./timeline";

export type Connection =
  | { status: "connecting" | "open" | "reconnecting" }
  | { status: "error"; reason: "not_found" | "generic" };

/**
 * Flux d'événements d'un projet (EventSource natif). La connexion est ouverte au montage,
 * donc avant tout envoi de message, et fermée au démontage.
 */
export function useProjectEvents(projectId: string) {
  const [timeline, dispatch] = useReducer(applyEvent, initialTimeline);
  const [connection, setConnection] = useState<Connection>({ status: "connecting" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let disposed = false;
    const source = new EventSource(eventsUrl(projectId));

    source.onopen = () => setConnection({ status: "open" });
    source.onmessage = (message: MessageEvent<string>) => {
      const event = parseEvent(message.data);
      if (event) dispatch(event);
    };
    source.onerror = () => {
      if (source.readyState !== EventSource.CLOSED) {
        // Le navigateur se reconnecte seul (Last-Event-ID inclus).
        setConnection({ status: "reconnecting" });
        return;
      }
      // EventSource n'expose ni statut ni corps : on interroge le projet pour distinguer 404 et le reste.
      getProject(projectId).then(
        () => {
          if (!disposed) setConnection({ status: "error", reason: "generic" });
        },
        (error: unknown) => {
          if (disposed) return;
          // 422 : identifiant mal formé, donc aucun projet ne peut correspondre.
          const notFound =
            error instanceof ApiError && (error.status === 404 || error.status === 422);
          setConnection({ status: "error", reason: notFound ? "not_found" : "generic" });
        },
      );
    };

    return () => {
      disposed = true;
      source.close();
    };
  }, [projectId, attempt]);

  const retry = useCallback(() => {
    setConnection({ status: "connecting" });
    setAttempt((n) => n + 1);
  }, []);

  return { items: timeline.items, turnRunning: timeline.turnRunning, connection, retry };
}
