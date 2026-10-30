"use client";

import { useCallback, useEffect, useId, useState, type FormEvent } from "react";
import { ApiActionError } from "@/components/additions/ApiActionError";
import { InvitationBadge, RoleBadge } from "@/components/additions/Badges";
import { ConfirmDialog } from "@/components/additions/ConfirmDialog";
import { EmptyState, ErrorState, LoadingState } from "@/components/additions/States";
import { Panel, Panels, StageHead } from "@/components/app/Stage";
import { Button } from "@/components/primitives/Button";
import { Field } from "@/components/primitives/Field";
import { roleLook } from "@/lib/additions/governance";
import { changeMemberRole, createInvitation, listInvitations, listMembers, removeMember, revokeInvitation } from "@/lib/additions/workspace";
import type { InvitationCreatedOut, InvitationOut, MemberOut, MembersOut } from "@/lib/api/types";

type Load = { state: "loading" } | { state: "ok"; data: MembersOut; invitations: InvitationOut[] } | { state: "error"; error: unknown };

/** What each role can do (auth/permissions.py). Owners can give any of them. */
const ROLES = [
  { role: "writer", help: "Writes drafts and sends them for review." },
  { role: "reviewer", help: "Checks drafts and marks them as reviewed." },
  { role: "approver", help: "Approves, rejects or sends back drafts." },
  { role: "owner", help: "Does all of that and manages this team." },
];

const day = (iso: string) => new Date(iso).toLocaleDateString(undefined, { dateStyle: "medium" });

/** Team: who is in this workspace and who has been invited. The server decides who may change it. */
export function Team() {
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [tick, setTick] = useState(0);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [removing, setRemoving] = useState<MemberOut | null>(null);
  const [revoking, setRevoking] = useState<InvitationOut | null>(null);
  // In memory only: the token can't be recovered, and must never reach storage, logs or the URL.
  const [created, setCreated] = useState<InvitationCreatedOut | null>(null);
  const refresh = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    let live = true;
    listMembers()
      .then(async (data) => {
        // Only people who can manage the team may read invitations; anyone else would get a 403.
        const invitations = data.allowed_actions.includes("invite") ? (await listInvitations()).items : [];
        if (live) setLoad({ state: "ok", data, invitations });
      })
      .catch((err) => live && setLoad({ state: "error", error: err }));
    return () => {
      live = false;
    };
  }, [tick]);

  /** Runs one change, then reloads from the server. What was typed stays if it's refused. */
  const act = async (run: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await run();
      refresh();
      return true;
    } catch (err) {
      setError(err);
      return false;
    } finally {
      setBusy(false);
    }
  };

  if (load.state === "loading")
    return (
      <>
        <StageHead title="Team" status="Loading…" />
        <LoadingState label="Loading your team…" />
      </>
    );
  if (load.state === "error")
    return (
      <>
        <StageHead title="Team" status="Couldn’t load" />
        <div className="app-empty card">
          <ErrorState
            error={load.error}
            onRetry={() => {
              setLoad({ state: "loading" });
              refresh();
            }}
          />
        </div>
      </>
    );

  const { data, invitations } = load;
  const can = (action: string) => data.allowed_actions.includes(action);
  const count = data.members.length;

  return (
    <>
      <StageHead title="Team" status={data.workspace.name} />

      <ApiActionError error={error} />

      <Panels cols="wide">
        <Panel n="01" label="Members" className="add-panel-fit" title={count === 1 ? "1 member" : `${count} members`}>
          <div className="add-table__wrap">
            <table className="add-table add-team-table">
              <thead>
                <tr>
                  <th scope="col">Name</th>
                  <th scope="col">Role</th>
                  <th scope="col">Joined</th>
                  {(can("change_role") || can("remove_member")) && <th scope="col">Manage</th>}
                </tr>
              </thead>
              <tbody>
                {data.members.map((m) => (
                  <tr key={m.user.id}>
                    <td>
                      {m.user.display_name}
                      {m.is_you && <span className="add-muted"> (you)</span>}
                    </td>
                    <td>
                      <RoleBadge role={m.role} />
                    </td>
                    <td>
                      <time dateTime={m.joined_at}>{day(m.joined_at)}</time>
                    </td>
                    {(can("change_role") || can("remove_member")) && (
                      <td>
                        {/* The server refuses changes to your own role, so they aren't offered. */}
                        {!m.is_you && (
                          <div className="add-team-manage">
                            {can("change_role") && (
                              <select
                                className="add-select"
                                aria-label={`Role for ${m.user.display_name}`}
                                value={m.role}
                                disabled={busy}
                                onChange={(e) => act(() => changeMemberRole(m.user.id, e.target.value))}
                              >
                                {/* A legacy or unknown role stays selectable as it is, so the row reads true. */}
                                {!ROLES.some((r) => r.role === m.role) && <option value={m.role}>{roleLook(m.role).label}</option>}
                                {ROLES.map((r) => (
                                  <option key={r.role} value={r.role}>
                                    {roleLook(r.role).label}
                                  </option>
                                ))}
                              </select>
                            )}
                            {can("remove_member") && (
                              <button type="button" className="add-btn-small" onClick={() => setRemoving(m)} disabled={busy}>
                                Remove
                              </button>
                            )}
                          </div>
                        )}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {count === 1 && can("invite") && (
            <p className="t-body panel__note">
              It’s just you here for now. Invite someone below and drafts can be reviewed by a second person. Nothing changes if you never invite anyone.
            </p>
          )}
        </Panel>
      </Panels>

      {can("invite") && (
        <div className="add-panels-gap">
          <Panels cols="2">
            <Panel n="02" label="Invite someone" title="Add a teammate">
              <InviteForm busy={busy} onSubmit={(email, role) => act(async () => setCreated(await createInvitation(email, role)))} />
              {created && <InviteLink created={created} onDone={() => setCreated(null)} />}
            </Panel>
            <Panel n="03" label="Invitations" title="Sent so far">
              {invitations.length === 0 ? (
                <EmptyState title="No invitations yet">Invitations you create will appear here.</EmptyState>
              ) : (
                <ul className="rows">
                  {invitations.map((i) => (
                    <li key={i.id} className="rows__item add-invite-row">
                      <div>
                        <p className="rows__title add-wrap">{i.email}</p>
                        <p className="rows__meta">
                          {roleLook(i.role).label} · invited by {i.invited_by?.display_name ?? "someone no longer here"}
                          {i.status === "pending" ? ` · expires ${day(i.expires_at)}` : ""}
                        </p>
                      </div>
                      <div className="add-team-manage">
                        <InvitationBadge status={i.status} />
                        {i.status === "pending" && (
                          <button type="button" className="add-btn-small" onClick={() => setRevoking(i)} disabled={busy}>
                            Revoke
                          </button>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          </Panels>
        </div>
      )}

      <ConfirmDialog
        open={removing !== null}
        title={`Remove ${removing?.user.display_name ?? "this person"}?`}
        confirmLabel="Remove"
        busy={busy}
        onCancel={() => setRemoving(null)}
        onConfirm={async () => {
          const m = removing;
          setRemoving(null);
          if (m) await act(() => removeMember(m.user.id));
        }}
      >
        <p>They lose access to this workspace straight away. What they wrote stays, and you can invite them again later.</p>
      </ConfirmDialog>
      <ConfirmDialog
        open={revoking !== null}
        title={`Revoke the invitation for ${revoking?.email ?? "this person"}?`}
        confirmLabel="Revoke"
        busy={busy}
        onCancel={() => setRevoking(null)}
        onConfirm={async () => {
          const i = revoking;
          setRevoking(null);
          if (!i) return;
          if (await act(() => revokeInvitation(i.id))) setCreated((c) => (c?.invitation.id === i.id ? null : c));
        }}
      >
        <p>The link stops working. You can create a new one at any time.</p>
      </ConfirmDialog>
    </>
  );
}

function InviteForm({ busy, onSubmit }: { busy: boolean; onSubmit: (email: string, role: string) => Promise<boolean> }) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("writer");
  const roleId = useId();
  const emailId = useId();
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (await onSubmit(email.trim(), role)) setEmail("");
  };
  return (
    <form className="add-stack" onSubmit={submit}>
      <Field label="Email" id={emailId} type="email" autoComplete="off" required value={email} onChange={(e) => setEmail(e.target.value)} disabled={busy} />
      <div className="add-field-row">
        <label className="t-caption" htmlFor={roleId}>
          Role
        </label>
        <select id={roleId} className="add-select" value={role} onChange={(e) => setRole(e.target.value)} disabled={busy}>
          {ROLES.map((r) => (
            <option key={r.role} value={r.role}>
              {roleLook(r.role).label}
            </option>
          ))}
        </select>
        <p className="t-caption add-team-help">{ROLES.find((r) => r.role === role)?.help}</p>
      </div>
      <Button type="submit" disabled={busy || !email.trim()}>
        {busy ? "Creating…" : "Create invitation"}
      </Button>
    </form>
  );
}

/** The one-time link. Audit AI sends no email, so the owner passes it on. */
function InviteLink({ created, onDone }: { created: InvitationCreatedOut; onDone: () => void }) {
  const [copied, setCopied] = useState<"yes" | "no" | null>(null);
  const linkId = useId();
  const link = `${window.location.origin}${created.accept_path}`;
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(link);
      setCopied("yes");
    } catch {
      setCopied("no");
    }
  };
  return (
    <div className="add-invite-link">
      <p className="t-body panel__note">
        <b>Share this link with {created.invitation.email}.</b> Audit AI doesn’t send email, so it’s up to you to pass it on.
      </p>
      <Field label="Invitation link" id={linkId} readOnly value={link} onFocus={(e) => e.currentTarget.select()} />
      <div className="add-team-manage">
        <button type="button" className="add-btn-small" onClick={copy}>
          Copy link
        </button>
        <button type="button" className="add-btn-small" onClick={onDone}>
          Done
        </button>
        <span className="t-caption" role="status">
          {copied === "yes" ? "✓ Copied" : copied === "no" ? "Couldn’t copy. Select the link and copy it yourself." : ""}
        </span>
      </div>
      <p className="t-caption add-team-help">
        This is the only time the link is shown, and it can’t be recovered. It works only for {created.invitation.email} and expires {day(created.invitation.expires_at)}.
      </p>
    </div>
  );
}
