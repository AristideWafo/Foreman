import { PaperAirplaneIcon } from "@heroicons/react/24/solid";
import { useId } from "react";
import type { FormEvent, KeyboardEvent } from "react";

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
        <textarea
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
          className="max-h-48 min-h-12 w-full resize-y rounded-xl border border-slate-300 bg-white px-3 py-2 text-base text-slate-900 placeholder:text-slate-500 read-only:bg-slate-100 read-only:text-slate-600 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600"
        />
        <button
          type="submit"
          disabled={!canSend}
          className="inline-flex h-12 shrink-0 items-center gap-2 rounded-xl bg-indigo-600 px-4 text-sm font-medium text-white hover:bg-indigo-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 disabled:cursor-not-allowed disabled:bg-slate-300 disabled:text-slate-600"
        >
          <PaperAirplaneIcon className="size-5" aria-hidden="true" />
          <span className="max-sm:sr-only">{submitLabel}</span>
        </button>
      </div>
      <p className="text-xs text-slate-600">
        Entrée pour envoyer, Maj+Entrée pour une nouvelle ligne.
      </p>
      {error ? (
        <p id={errorId} role="alert" className="text-sm font-medium text-red-700">
          {error}
        </p>
      ) : null}
    </form>
  );
}
