import type { IntegrationView } from "../../api/client";
import { ExternalLink } from "@/components/ExternalLink";

/** Aide « Comment configurer ? » : tout vient de l'API (déclaré dans `connector.yaml`). */
export function IntegrationHelp({ integration }: { integration: IntegrationView }) {
  const help = integration.help;
  if (!help) return null;
  return (
    <section
      className="flex flex-col gap-3 rounded-lg bg-muted p-4 text-sm"
      aria-label={`Comment configurer ${integration.connector}`}
    >
      <ol className="flex list-decimal flex-col gap-1 pl-5">
        {help.steps.map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ol>
      {help.url ? (
        <p>
          <ExternalLink href={help.url}>Ouvrir la page de création du jeton</ExternalLink>
        </p>
      ) : null}
      {integration.tokens
        .filter((t) => t.permissions.length > 0)
        .map((t) => (
          <div key={t.name} className="flex flex-col gap-1">
            <h4 className="font-medium">{t.label}</h4>
            <p className="text-muted-foreground">Droits à cocher, et uniquement ceux-là :</p>
            <ul className="flex list-disc flex-col gap-1 pl-5">
              {t.permissions.map((p) => (
                <li key={p.name}>
                  <code className="font-mono">{p.name}</code> : {p.explanation}
                </li>
              ))}
            </ul>
          </div>
        ))}
      {help.note ? <p className="text-muted-foreground">{help.note}</p> : null}
      {help.sources.length > 0 ? (
        <p className="text-muted-foreground">
          Sources :{" "}
          {help.sources.map((s, i) => (
            <span key={s}>
              {i > 0 ? ", " : null}
              <ExternalLink href={s}>{s.replace("https://", "")}</ExternalLink>
            </span>
          ))}
        </p>
      ) : null}
    </section>
  );
}
