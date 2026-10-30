import { useId, useState } from "react";
import { CheckIcon, MinusCircleIcon, QuestionMarkCircleIcon } from "@heroicons/react/24/outline";
import type { ClarificationCardData } from "../../api/events";
import { CardHeading } from "@/components/CardHeading";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useAnswerQuestion } from "./useAnswerQuestion";

type Question = ClarificationCardData["questions"][number];

/**
 * Une question : options imposées par le serveur (ou champ libre si elles sont vides), puis « Répondre » et
 * « Reporter ». Recréée (`key`) quand la question change d'état, donc à chaque carte réémise.
 */
function OpenQuestion({ projectId, question }: { projectId: string; question: Question }) {
  const legendId = useId();
  const [choice, setChoice] = useState("");
  const { answer, defer, pending, sent, waitingForCard, errorMessage } = useAnswerQuestion(
    projectId,
    question.id,
  );
  const free = question.options.length === 0;
  const locked = pending || sent || waitingForCard;
  const value = free ? choice.trim() : choice;

  return (
    <fieldset className="flex min-w-0 flex-col gap-3" aria-busy={pending}>
      <legend id={legendId} className="mb-3 text-sm whitespace-pre-wrap">
        {question.prompt}
      </legend>
      {free ? (
        <>
          {question.suggestions?.length ? (
            <ToggleGroup
              variant="outline"
              className="flex-wrap"
              value={choice ? [choice] : []}
              onValueChange={(next) => setChoice(next[0] ?? "")}
              disabled={locked}
            >
              {question.suggestions.map((suggestion) => (
                <ToggleGroupItem key={suggestion} value={suggestion}>
                  {suggestion}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          ) : null}
          <Input
            value={choice}
            onChange={(event) => setChoice(event.target.value)}
            aria-labelledby={legendId}
            maxLength={500}
            disabled={locked}
          />
        </>
      ) : (
        <ToggleGroup
          variant="outline"
          className="flex-wrap"
          value={choice ? [choice] : []}
          onValueChange={(next) => setChoice(next[0] ?? "")}
          disabled={locked}
        >
          {question.options.map((option) => (
            <ToggleGroupItem key={option} value={option}>
              {choice === option ? <CheckIcon data-icon="inline-start" /> : null}
              {option}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" onClick={() => answer(value)} disabled={locked || value === ""}>
          {pending ? "Envoi en cours…" : "Répondre"}
        </Button>
        <Button type="button" variant="outline" onClick={defer} disabled={locked}>
          Reporter
        </Button>
        {sent ? (
          <p role="status" className="text-sm text-muted-foreground">
            Envoyé. La carte va être mise à jour.
          </p>
        ) : null}
      </div>
      {errorMessage ? (
        <Alert variant="destructive">
          <AlertDescription>{errorMessage}</AlertDescription>
        </Alert>
      ) : null}
    </fieldset>
  );
}

/** Question close : sa réponse (texte) ou « Reportée ». Plus aucun bouton. */
function ClosedQuestion({ question }: { question: Question }) {
  const answered = question.status === "answered";
  return (
    <div className="flex flex-col gap-2">
      <p className="text-sm whitespace-pre-wrap">{question.prompt}</p>
      <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
        {answered ? <CheckIcon aria-hidden="true" /> : <MinusCircleIcon aria-hidden="true" />}
        {answered ? `Réponse : ${question.answer ?? ""}` : "Reportée"}
      </p>
    </div>
  );
}

/** Carte de clarification : les questions de l'agent, avec « Répondre » ou « Reporter » pour chacune. */
export function ClarificationCard({
  card,
  projectId,
}: {
  card: ClarificationCardData;
  projectId: string;
}) {
  return (
    <Card role="group" aria-label="Clarification" className="ring-0">
      <CardHeading
        icon={<QuestionMarkCircleIcon aria-hidden="true" />}
        title="Clarification"
        description="Précisez ces points pour que le plan soit complet."
      />
      <CardContent className="flex flex-col gap-6">
        {card.questions.map((question) =>
          question.status === "open" ? (
            <OpenQuestion
              key={`${question.id}:${question.status}`}
              projectId={projectId}
              question={question}
            />
          ) : (
            <ClosedQuestion key={`${question.id}:${question.status}`} question={question} />
          ),
        )}
      </CardContent>
    </Card>
  );
}
