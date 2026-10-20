import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ApiError, acceptInvite } from "../../api/client";
import { AuthPage, Field } from "./AuthForm";

const PASSWORD_MIN = 12;
const PASSWORD_MAX = 128;

/** Jeton en chemin (`/invite/:token`) ou en fragment (`/accept-invite#token=…`, lien de la CLI). */
function readToken(pathToken: string | undefined): string {
  return pathToken ?? new URLSearchParams(window.location.hash.slice(1)).get("token") ?? "";
}

function describeInviteError(error: unknown): string {
  if (error instanceof ApiError && error.status === 429) {
    return "Trop de tentatives. Réessayez dans quelques minutes.";
  }
  return "Invitation invalide ou expirée, ou informations incorrectes.";
}

export function InvitePage() {
  const navigate = useNavigate();
  const pathToken = useParams().token;
  const [token] = useState(() => {
    const value = readToken(pathToken);
    // Le jeton ne reste ni dans l'URL ni dans l'historique une fois lu (jamais journalisé ni stocké).
    if (window.location.hash) {
      window.history.replaceState(null, "", window.location.pathname + window.location.search);
    }
    return value;
  });
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: acceptInvite,
    onSuccess: () => navigate("/login", { replace: true }),
  });

  function submit() {
    if (password.length < PASSWORD_MIN || password.length > PASSWORD_MAX) {
      setLocalError(
        `Le mot de passe doit contenir entre ${PASSWORD_MIN} et ${PASSWORD_MAX} caractères.`,
      );
    } else if (password !== confirmation) {
      setLocalError("Les deux mots de passe ne correspondent pas.");
    } else {
      setLocalError(null);
      mutation.mutate({ token, name: name.trim(), email: email.trim(), password });
    }
  }

  return (
    <AuthPage
      title="Créer votre mot de passe"
      error={localError ?? (mutation.isError ? describeInviteError(mutation.error) : null)}
      submitLabel="Activer mon compte"
      busy={mutation.isPending}
      onSubmit={submit}
    >
      <Field
        label="Nom"
        id="name"
        autoComplete="name"
        value={name}
        onChange={(e) => setName(e.target.value)}
      />
      <Field
        label="Adresse e-mail"
        id="email"
        type="email"
        autoComplete="username"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
      />
      <Field
        label="Mot de passe (12 caractères minimum)"
        id="password"
        type="password"
        autoComplete="new-password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      <Field
        label="Confirmer le mot de passe"
        id="confirmation"
        type="password"
        autoComplete="new-password"
        value={confirmation}
        onChange={(e) => setConfirmation(e.target.value)}
      />
    </AuthPage>
  );
}
