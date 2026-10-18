import { ArrowUpIcon } from "@heroicons/react/24/outline";
import { useId } from "react";
import type { FormEvent, KeyboardEvent } from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupText,
  InputGroupTextarea,
} from "@/components/ui/input-group";

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
    <form onSubmit={onSubmit} className="flex flex-col gap-2">
      <label htmlFor={id} className="sr-only">
        {label}
      </label>
      <InputGroup>
        {/* readOnly plutôt que disabled : le champ garde le focus pendant un tour en cours. */}
        <InputGroupTextarea
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
          className="max-h-48 min-h-12"
        />
        <InputGroupAddon align="block-end">
          <InputGroupText>Maj+Entrée : nouvelle ligne</InputGroupText>
          <InputGroupButton
            type="submit"
            variant="default"
            size="icon-sm"
            disabled={!canSend}
            className="ml-auto rounded-full"
          >
            <ArrowUpIcon />
            <span className="sr-only">{submitLabel}</span>
          </InputGroupButton>
        </InputGroupAddon>
      </InputGroup>
      {error ? (
        <Alert variant="destructive" id={errorId}>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
    </form>
  );
}
