import { useState } from "react";
import { describeAdminError, type MemberRole, type UserView } from "../../api/client";
import { NativeSelect } from "@/components/NativeSelect";
import { ROLE_LABELS } from "@/components/UserRoleBadge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ConfirmDialog, type Confirmation } from "./ConfirmDialog";
import { ActionError, QueryStatus } from "./QueryStatus";
import {
  useAdminTeams,
  useAdminUsers,
  useDisableUser,
  useRemoveMember,
  useSetMemberRole,
} from "./useAdmin";

const MEMBER_ROLES: MemberRole[] = ["developer", "team_admin"];

function RoleOptions() {
  return MEMBER_ROLES.map((r) => (
    <option key={r} value={r}>
      {ROLE_LABELS[r]}
    </option>
  ));
}

/** Utilisateurs, rôle par équipe, ajout/retrait et désactivation. Chaque perte de droits se confirme. */
export function MembersTab({ isOrgAdmin }: { isOrgAdmin: boolean }) {
  const users = useAdminUsers();
  const teams = useAdminTeams();
  const setRole = useSetMemberRole();
  const remove = useRemoveMember();
  const disable = useDisableUser();
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [addUser, setAddUser] = useState("");
  const [addTeam, setAddTeam] = useState("");
  const [addRole, setAddRole] = useState<MemberRole>("developer");
  const error = [setRole, remove, disable].find((m) => m.isError)?.error;

  function changeRole(user: UserView, teamId: string, teamName: string, role: MemberRole) {
    const run = () => setRole.mutate({ teamId, userId: user.id, role });
    if (role === "developer") {
      setConfirmation({
        title: "Rétrograder ce membre ?",
        description: `${user.name} deviendra développeur dans l'équipe ${teamName} et perdra ses droits d'administration.`,
        confirmLabel: "Rétrograder",
        run,
      });
    } else run();
  }

  return (
    <div className="flex flex-col gap-6">
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          setRole.mutate(
            { teamId: addTeam, userId: addUser, role: addRole },
            { onSuccess: () => setAddUser("") },
          );
        }}
      >
        <div className="flex min-w-48 flex-col gap-1.5">
          <Label htmlFor="add-user">Utilisateur</Label>
          <NativeSelect
            id="add-user"
            required
            value={addUser}
            onChange={(e) => setAddUser(e.target.value)}
          >
            <option value="">Choisir…</option>
            {(users.data ?? [])
              .filter((u) => !u.disabled)
              .map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name}
                </option>
              ))}
          </NativeSelect>
        </div>
        <div className="flex min-w-40 flex-col gap-1.5">
          <Label htmlFor="add-team">Équipe</Label>
          <NativeSelect
            id="add-team"
            required
            value={addTeam}
            onChange={(e) => setAddTeam(e.target.value)}
          >
            <option value="">Choisir…</option>
            {(teams.data ?? []).map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </NativeSelect>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="add-role">Rôle</Label>
          <NativeSelect
            id="add-role"
            value={addRole}
            onChange={(e) => setAddRole(e.target.value as MemberRole)}
          >
            <RoleOptions />
          </NativeSelect>
        </div>
        <Button type="submit" disabled={setRole.isPending || !addUser || !addTeam}>
          Ajouter à l'équipe
        </Button>
      </form>
      <ActionError message={error ? describeAdminError(error) : null} />
      <QueryStatus
        isPending={users.isPending}
        isError={users.isError}
        empty={users.data?.length === 0}
        emptyText="Aucun utilisateur."
      />
      {users.data?.length ? (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Utilisateur</TableHead>
              <TableHead>Équipes et rôles</TableHead>
              <TableHead>
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {users.data.map((u) => (
              <TableRow key={u.id}>
                <TableCell className="align-top">
                  <div className="flex flex-col">
                    <span className="font-medium">{u.name}</span>
                    <span className="text-xs">{u.email}</span>
                    {u.disabled ? <Badge variant="secondary">Désactivé</Badge> : null}
                  </div>
                </TableCell>
                <TableCell>
                  <ul className="flex flex-col gap-2">
                    {u.memberships.length === 0 ? (
                      <li className="text-sm">Aucune équipe.</li>
                    ) : null}
                    {u.memberships.map((m) => (
                      <li key={m.team_id} className="flex flex-wrap items-center gap-2">
                        <span className="min-w-32 text-sm">{m.team_name}</span>
                        {m.role === "org_admin" ? (
                          <Badge variant="secondary">{ROLE_LABELS.org_admin}</Badge>
                        ) : (
                          <NativeSelect
                            className="w-40"
                            aria-label={`Rôle de ${u.name} dans ${m.team_name}`}
                            value={m.role}
                            disabled={u.disabled}
                            onChange={(e) =>
                              changeRole(u, m.team_id, m.team_name, e.target.value as MemberRole)
                            }
                          >
                            <RoleOptions />
                          </NativeSelect>
                        )}
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() =>
                            setConfirmation({
                              title: "Retirer ce membre ?",
                              description: `${u.name} n'aura plus accès à l'équipe ${m.team_name} ni à ses projets.`,
                              confirmLabel: "Retirer",
                              run: () => remove.mutate({ teamId: m.team_id, userId: u.id }),
                            })
                          }
                        >
                          Retirer
                          <span className="sr-only">
                            {" "}
                            {u.name} de {m.team_name}
                          </span>
                        </Button>
                      </li>
                    ))}
                  </ul>
                </TableCell>
                <TableCell className="align-top">
                  {isOrgAdmin && !u.disabled ? (
                    <Button
                      variant="destructive"
                      size="sm"
                      onClick={() =>
                        setConfirmation({
                          title: "Désactiver ce compte ?",
                          description: `${u.name} ne pourra plus se connecter. Ses sessions sont fermées.`,
                          confirmLabel: "Désactiver",
                          run: () => disable.mutate(u.id),
                        })
                      }
                    >
                      Désactiver<span className="sr-only"> {u.name}</span>
                    </Button>
                  ) : null}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      ) : null}
      <ConfirmDialog confirmation={confirmation} onClose={() => setConfirmation(null)} />
    </div>
  );
}
