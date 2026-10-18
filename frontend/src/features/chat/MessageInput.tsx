import { Send } from "lucide-react";
import { useId } from "react";
import type { FormEvent, KeyboardEvent } from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

interface MessageInputProps {
  value: string;
  onChange: (value: string) => void;
  /** Envoie le texte ; une promesse rejetée signifie « échec », la saisie est alors conservée. */
  onSend: () => Promise<unknown> | void;
  label: string;
  submitLabel: string;
  placeholder?: string;
  /** Envoi impossible pour l'instant (tour en cours, requête en vol). */
  busy?: boolean;
  /** Message d'erreur déjà formulé pour l'utilisateur. */
  error?: string | null;
}

export function MessageInput({
  value,
  onChange,
  onSend,
  label,
  submitLabel,
  placeholder,
  busy = false,
  error = null,
}: MessageInputProps) {
  const id = useId();
  const errorId = `${id}-error`;
  const canSend = !busy && value.trim() !== "";

  async function send() {
    if (!canSend) return;
    try {
      await onSend();
    } catch {
      // L'erreur est affichée par le parent ; la saisie reste intacte.
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void send();
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // Entrée envoie, Maj+Entrée saute une ligne ; on ne coupe pas une composition (IME).
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void send();
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-2">
      <label htmlFor={id} className="sr-only">
        {label}
      </label>
      <div className="flex items-end gap-2">
        {/* readOnly plutôt que disabled : le champ garde le focus pendant un tour en cours. */}
        <Textarea
          id={id}
          autoFocus
          rows={2}
          maxLength={4000}
          value={value}
          readOnly={busy}
          aria-busy={busy}
          aria-describedby={error ? errorId : undefined}
          placeholder={placeholder}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={onKeyDown}
          className="max-h-48 min-h-12 resize-y read-only:bg-muted"
        />
        <Button type="submit" size="lg" disabled={!canSend} className="h-12 shrink-0">
          <Send aria-hidden="true" />
          <span className="max-sm:sr-only">{submitLabel}</span>
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        Entrée pour envoyer, Maj+Entrée pour une nouvelle ligne.
      </p>
      {error ? (
        <Alert variant="destructive" id={errorId}>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
    </form>
  );
}
