import type { components, paths } from "./schema";

export type Project = components["schemas"]["Project"];
export type ErrorCode = components["schemas"]["ErrorResponse"]["error"];

type CreateProjectBody = NonNullable<
  paths["/api/projects"]["post"]["requestBody"]
>["content"]["application/json"];
type MessageAccepted =
  paths["/api/projects/{project_id}/messages"]["post"]["responses"][202]["content"]["application/json"];

const ERROR_CODES: readonly ErrorCode[] = [
  "not_found",
  "invalid_request",
  "method_not_allowed",
  "turn_in_progress",
  "capacity_exceeded",
  "internal_error",
  "not_implemented",
];

/** Erreur d'API : seuls le statut et le code opaque du contrat sont conservés. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: ErrorCode | null;

  constructor(status: number, code: ErrorCode | null) {
    super(`api_error_${status}`);
    this.status = status;
    this.code = code;
  }
}

async function readErrorCode(res: Response): Promise<ErrorCode | null> {
  try {
    const body: unknown = await res.json();
    if (typeof body === "object" && body !== null && "error" in body) {
      return ERROR_CODES.find((code) => code === body.error) ?? null;
    }
  } catch {
    // Corps absent ou illisible : le statut suffit.
  }
  return null;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch {
    throw new ApiError(0, null);
  }
  if (!res.ok) throw new ApiError(res.status, await readErrorCode(res));
  return (await res.json()) as T;
}

function jsonPost(body: unknown): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

export function createProject(body: CreateProjectBody = { title: "" }): Promise<Project> {
  return request<Project>("/api/projects", jsonPost(body));
}

export function getProject(projectId: string): Promise<Project> {
  return request<Project>(`/api/projects/${encodeURIComponent(projectId)}`);
}

export function postMessage(projectId: string, text: string): Promise<MessageAccepted> {
  return request<MessageAccepted>(
    `/api/projects/${encodeURIComponent(projectId)}/messages`,
    jsonPost({ text }),
  );
}

export function eventsUrl(projectId: string): string {
  return `/api/projects/${encodeURIComponent(projectId)}/events`;
}

/** Message utilisateur en français, sans aucun détail technique. */
export function describeError(error: unknown): string {
  const code = error instanceof ApiError ? error.code : null;
  switch (code) {
    case "turn_in_progress":
      return "Une réponse est déjà en cours. Attendez qu'elle se termine avant d'envoyer un autre message.";
    case "invalid_request":
      return "Message invalide : il doit contenir entre 1 et 4 000 caractères.";
    case "capacity_exceeded":
      return "Le service est momentanément saturé. Réessayez dans un instant.";
    case "not_found":
      return "Projet introuvable.";
    default:
      return "Une erreur est survenue. Réessayez dans un instant.";
  }
}
