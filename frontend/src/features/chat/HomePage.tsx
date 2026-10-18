import { ServerStackIcon } from "@heroicons/react/24/outline";
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { createProject, describeError } from "../../api/client";
import { MessageInput } from "./MessageInput";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";

export function HomePage() {
  const navigate = useNavigate();
  const [text, setText] = useState("");
  const create = useMutation({
    mutationFn: () => createProject({ title: "" }),
  });

  async function start() {
    const message = text.trim();
    const project = await create.mutateAsync();
    // La page du projet ouvre le flux d'événements, puis poste ce premier message.
    await navigate(`/projects/${project.id}`, { state: { firstMessage: message } });
  }

  return (
    <main className="mx-auto flex min-h-dvh max-w-3xl flex-col justify-center px-4 py-8">
      <Card>
        <CardHeader>
          <div className="flex items-center gap-3">
            <ServerStackIcon className="size-8 text-primary" aria-hidden="true" />
            <h1 className="text-2xl font-semibold">Foreman</h1>
          </div>
          <CardDescription>
            Décrivez ce que vous voulez faire : Foreman propose un plan que vous pouvez relire.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <MessageInput
            value={text}
            onChange={setText}
            onSend={start}
            label="Votre demande"
            submitLabel="Démarrer"
            placeholder="Par exemple : déployer mon application sur un nouveau serveur"
            busy={create.isPending}
            error={create.isError ? describeError(create.error) : null}
          />
        </CardContent>
      </Card>
    </main>
  );
}
