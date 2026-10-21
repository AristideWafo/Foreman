import { useState } from "react";
import {
  CheckCircleIcon,
  ExclamationTriangleIcon,
  MinusCircleIcon,
} from "@heroicons/react/24/outline";
import { describeAdminError, type IntegrationView, type RightView } from "../../api/client";
import { BrandLogo } from "@/components/BrandLogo";
import { NativeSelect } from "@/components/NativeSelect";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ConfirmDialog, type Confirmation } from "./ConfirmDialog";
import { ActionError } from "./QueryStatus";
import {
  useRevokeCredentials,
  useSetCredentials,
  useSetModel,
  useTestIntegration,
} from "./useAdmin";

const VERDICTS: Record<RightView["verdict"], { label: string; icon: typeof CheckCircleIcon }> = {
  ok: { label: "ok", icon: CheckCircleIcon },
  missing: { label: "manquant", icon: ExclamationTriangleIcon },
  excess: { label: "en trop", icon: MinusCircleIcon },
};

function StatusBadge({ integration: i }: { integration: IntegrationView }) {
  if (!i.configured) return <Badge variant="secondary">Non configuré</Badge>;
  if (i.status === "ok") return <Badge>Complet</Badge>;
  if (i.status === "incomplete") return <Badge variant="outline">Incomplet</Badge>;
  if (i.status === "revoked") return <Badge variant="destructive">Révoqué</Badge>;
  return <Badge variant="secondary">Non testé</Badge>;
}

/** Droits lus de l'API, un par ligne, avec leur verdict (icône + texte, jamais la couleur seule). */
function Rights({ rights, label }: { rights: RightView[]; label: string }) {
  if (rights.length === 0) return null;
  return (
    <ul className="flex flex-col gap-1 text-sm" aria-label={label}>
      {rights.map((r) => {
        const { label: text, icon: Icon } = VERDICTS[r.verdict];
        return (
          <li key={`${r.token}/${r.right}`} className="flex items-center gap-2">
            <Icon aria-hidden="true" className="size-4 shrink-0" />
            <span className="min-w-0 break-words">
              {r.token} : {r.right}
            </span>
            <span className="text-muted-foreground">({text})</span>
          </li>
        );
      })}
    </ul>
  );
}

/** Tarifs en USD par million de jetons (models.yaml côté serveur). */
function ModelPicker({ integration }: { integration: IntegrationView }) {
  const setModel = useSetModel();
  const saved = integration.llm?.model ?? "";
  const [choice, setChoice] = useState(saved);
  const id = `model-${integration.connector}`;
  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor={id}>Modèle</Label>
      <div className="flex flex-wrap gap-2">
        <NativeSelect
          id={id}
          className="min-w-0 flex-1 basis-64"
          value={choice}
          onChange={(e) => setChoice(e.target.value)}
        >
          {saved === "" ? <option value="">Choisir…</option> : null}
          {(integration.llm?.models ?? []).map((m) => (
            <option key={m.id} value={m.id}>
              {m.label} (entrée {m.input_usd} $, sortie {m.output_usd} $ par million de jetons)
            </option>
          ))}
        </NativeSelect>
        <Button
          variant="outline"
          disabled={setModel.isPending || choice === "" || choice === saved}
          onClick={() => setModel.mutate(choice)}
        >
          Choisir ce modèle
        </Button>
      </div>
      {choice !== "" && choice !== saved ? (
        <Alert>
          <AlertDescription>
            Évaluations non rejouées sur ce modèle (voir le ticket #61).
          </AlertDescription>
        </Alert>
      ) : null}
      <ActionError message={setModel.isError ? describeAdminError(setModel.error) : null} />
    </div>
  );
}

/** Une ligne par connecteur : statut, droits, jeton (écriture seule), test et révocation. */
export function IntegrationRow({ integration }: { integration: IntegrationView }) {
  const { connector } = integration;
  const credentials = useSetCredentials();
  const revoke = useRevokeCredentials();
  const test = useTestIntegration();
  const [open, setOpen] = useState(false);
  const [token, setToken] = useState("");
  const [name, setName] = useState("");
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const tokenId = `token-${connector}`;
  const tokenNames = integration.tokens.map((t) => t.name);

  return (
    <li className="flex flex-col gap-3 rounded-xl border p-4">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <BrandLogo provider={connector} resourceType="" />
        <h3 className="text-sm font-medium capitalize">{connector}</h3>
        <StatusBadge integration={integration} />
        {integration.configured ? (
          <span className="text-sm text-muted-foreground">Jeton enregistré</span>
        ) : null}
        <div className="flex w-full flex-wrap gap-2 sm:ml-auto sm:w-auto">
          <Button variant="outline" size="sm" onClick={() => setOpen((o) => !o)}>
            {integration.configured ? "Remplacer le jeton" : "Configurer"}
            <span className="sr-only"> {connector}</span>
          </Button>
          {integration.configured ? (
            <>
              <Button
                variant="outline"
                size="sm"
                disabled={test.isPending}
                onClick={() => test.mutate(connector)}
              >
                {test.isPending ? "Test…" : "Tester"}
                <span className="sr-only"> {connector}</span>
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() =>
                  setConfirmation({
                    title: `Révoquer le jeton ${connector} ?`,
                    description:
                      "Foreman ne pourra plus utiliser ce connecteur tant qu'un nouveau jeton n'est pas enregistré.",
                    confirmLabel: "Révoquer",
                    run: () => revoke.mutate(connector),
                  })
                }
              >
                Révoquer<span className="sr-only"> {connector}</span>
              </Button>
            </>
          ) : null}
        </div>
      </div>
      <div role="status">
        <Rights
          rights={test.data?.rights ?? integration.rights}
          label={`Droits requis pour ${connector}`}
        />
      </div>
      {open ? (
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            const value = token;
            setToken(""); // vidé dès l'envoi, succès ou échec ; jamais dans le cache de requêtes
            void credentials
              .save({ connector, token: value, name: name || undefined })
              .then((ok) => ok && setOpen(false));
          }}
        >
          {tokenNames.length > 1 ? (
            <div className="flex min-w-40 flex-col gap-1.5">
              <Label htmlFor={`${tokenId}-name`}>Jeton à remplacer</Label>
              <NativeSelect
                id={`${tokenId}-name`}
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
              >
                <option value="">Choisir…</option>
                {tokenNames.map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </NativeSelect>
            </div>
          ) : null}
          <div className="flex min-w-0 flex-1 basis-64 flex-col gap-1.5">
            <Label htmlFor={tokenId}>Jeton {connector}</Label>
            <Input
              id={tokenId}
              type="password"
              autoComplete="new-password"
              required
              value={token}
              onChange={(e) => setToken(e.target.value)}
            />
          </div>
          <Button type="submit" disabled={credentials.isPending || !token}>
            {credentials.isPending ? "Enregistrement…" : "Enregistrer"}
          </Button>
        </form>
      ) : null}
      <ActionError message={credentials.error ? describeAdminError(credentials.error) : null} />
      <ActionError message={revoke.isError ? describeAdminError(revoke.error) : null} />
      <ActionError message={test.isError ? describeAdminError(test.error) : null} />
      {integration.kind === "llm" && integration.llm ? (
        <ModelPicker integration={integration} />
      ) : null}
      <ConfirmDialog confirmation={confirmation} onClose={() => setConfirmation(null)} />
    </li>
  );
}
