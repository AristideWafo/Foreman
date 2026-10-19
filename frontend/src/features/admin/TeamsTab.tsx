import { useState } from "react";
import { describeAdminError } from "../../api/client";
import { NativeSelect } from "@/components/NativeSelect";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ActionError, QueryStatus } from "./QueryStatus";
import { useAdminTeams, useAdminUsers, useCreateTeam } from "./useAdmin";

/** Équipes visibles ; la création est réservée à l'admin d'organisation (le serveur décide). */
export function TeamsTab({ isOrgAdmin }: { isOrgAdmin: boolean }) {
  const teams = useAdminTeams();
  const users = useAdminUsers();
  const create = useCreateTeam();
  const [name, setName] = useState("");
  const [firstAdminId, setFirstAdminId] = useState("");
  const candidates = (users.data ?? []).filter((u) => !u.disabled);

  return (
    <div className="flex flex-col gap-6">
      {isOrgAdmin ? (
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate(
              { name: name.trim(), first_admin_id: firstAdminId },
              {
                onSuccess: () => {
                  setName("");
                  setFirstAdminId("");
                },
              },
            );
          }}
        >
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="team-name">Nom de l'équipe</Label>
            <Input
              id="team-name"
              required
              maxLength={100}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="flex min-w-48 flex-col gap-1.5">
            <Label htmlFor="team-first-admin">Premier administrateur</Label>
            <NativeSelect
              id="team-first-admin"
              required
              value={firstAdminId}
              onChange={(e) => setFirstAdminId(e.target.value)}
            >
              <option value="">Choisir un utilisateur…</option>
              {candidates.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name} ({u.email})
                </option>
              ))}
            </NativeSelect>
          </div>
          <Button type="submit" disabled={create.isPending || !name.trim() || !firstAdminId}>
            {create.isPending ? "Création…" : "Créer l'équipe"}
          </Button>
        </form>
      ) : null}
      <ActionError message={create.isError ? describeAdminError(create.error) : null} />
      <QueryStatus
        isPending={teams.isPending}
        isError={teams.isError}
        empty={teams.data?.length === 0}
        emptyText="Aucune équipe."
      />
      {teams.data?.length ? (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Équipe</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {teams.data.map((t) => (
              <TableRow key={t.id}>
                <TableCell>{t.name}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      ) : null}
    </div>
  );
}
