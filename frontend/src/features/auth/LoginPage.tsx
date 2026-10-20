import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, login } from "../../api/client";
import { AuthPage, Field } from "./AuthForm";

/** Un seul message pour tout échec (identifiants, compte, mode) : rien ne doit révéler la cause. */
function describeLoginError(error: unknown): string {
  if (error instanceof ApiError && error.status === 429) {
    return "Trop de tentatives. Réessayez dans quelques minutes.";
  }
  return "Connexion impossible. Vérifiez vos identifiants et réessayez.";
}

export function LoginPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const mutation = useMutation({
    mutationFn: login,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["me"] });
      await navigate("/", { replace: true });
    },
  });
  return (
    <AuthPage
      title="Connexion à Foreman"
      error={mutation.isError ? describeLoginError(mutation.error) : null}
      submitLabel="Se connecter"
      busy={mutation.isPending}
      onSubmit={() => mutation.mutate({ email: email.trim(), password })}
    >
      <Field
        label="Adresse e-mail"
        id="email"
        type="email"
        autoComplete="username"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
      />
      <Field
        label="Mot de passe"
        id="password"
        type="password"
        autoComplete="current-password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
    </AuthPage>
  );
}
