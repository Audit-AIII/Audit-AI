"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";
import { BrandBar } from "@/components/additions/BrandBar";
import { ConfirmDialog } from "@/components/additions/ConfirmDialog";
import { EmptyState, ErrorState, LoadingState } from "@/components/additions/States";
import { Panel, Panels, StageHead } from "@/components/app/Stage";
import { Button } from "@/components/primitives/Button";
import { useBrands } from "@/lib/additions/brands";
import { ApiError, api } from "@/lib/api/client";
import type { BrandRules, BrandRulesOut } from "@/lib/api/types";

/**
 * Brand rules editor: GET / PUT /api/brands/{id}/rules (services/api/API.md "Brand rules").
 * Schema: services/verification/schemas/brand_rules.schema.json. rule_set_id and version are set
 * by the server and never sent. A 422 is shown exactly as returned: it names fields and rule ids only.
 */

type Item = Record<string, unknown>;
const LISTS: { key: string; label: string; describe: (r: Item) => string }[] = [
  { key: "prohibited_terms", label: "Prohibited terms", describe: (r) => `Never say “${r.term}”${r.approved_alternative ? `, say “${r.approved_alternative}” instead` : ""}` },
  { key: "required_terms", label: "Required terms", describe: (r) => `Always include “${r.term}”` },
  { key: "preferred_terms", label: "Preferred terms", describe: (r) => `Say “${r.preferred}” instead of ${list(r.discouraged)}` },
  { key: "product_names", label: "Product names", describe: (r) => `Write it as “${r.approved_name}”${Array.isArray(r.variants) && r.variants.length ? `, not ${list(r.variants)}` : ""}` },
  { key: "spelling", label: "Spelling", describe: (r) => `“${r.correct}”, not ${list(r.incorrect)}` },
  { key: "consistency", label: "Consistent wording", describe: (r) => `Pick one of ${list(r.variants)} and stick to it` },
  { key: "disclaimers", label: "Required disclaimers", describe: (r) => `Include “${r.disclaimer}”${Array.isArray(r.trigger_terms) && r.trigger_terms.length ? ` when mentioning ${list(r.trigger_terms)}` : ""}` },
  { key: "numeric_limits", label: "Number limits", describe: (r) => `${r.subject}: ${r.minimum ?? "any"} to ${r.maximum ?? "any"} ${list(r.units)}` },
];
const list = (v: unknown) => (Array.isArray(v) && v.length ? v.map((x) => `“${x}”`).join(", ") : "(none)");
const SEVERITIES = ["low", "medium", "high", "critical"] as const;

/** Server-set fields are not editable and never sent. */
function editable(rules: BrandRules | null): Item {
  if (!rules) return {};
  const { rule_set_id: _id, version: _v, ...rest } = rules;
  void _id;
  void _v;
  return rest;
}
const pretty = (o: Item) => JSON.stringify(o, null, 2);

/** A rule_id matching ^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$, unique in the rule set. */
function newRuleId(prefix: string, term: string, taken: Set<string>) {
  const slug = term.toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60) || "rule";
  let id = `${prefix}-${slug}`;
  for (let n = 2; taken.has(id); n++) id = `${prefix}-${slug}-${n}`;
  return id;
}
function allRuleIds(o: Item): Set<string> {
  const ids = new Set<string>();
  for (const v of Object.values(o)) if (Array.isArray(v)) for (const r of v) if (r && typeof r === "object" && typeof (r as Item).rule_id === "string") ids.add((r as Item).rule_id as string);
  return ids;
}

type Load = { state: "loading" } | { state: "ok"; data: BrandRulesOut } | { state: "error"; error: unknown };

export function RulesEditor() {
  const { value: brands, refresh, choose } = useBrands();
  const brandId = brands.state === "ready" ? brands.brand.id : null;
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [tick, setTick] = useState(0);
  const [text, setText] = useState("{}");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  // quick add
  const [kind, setKind] = useState<"prohibited_terms" | "required_terms">("prohibited_terms");
  const [term, setTerm] = useState("");
  const [alt, setAlt] = useState("");
  const [sev, setSev] = useState<(typeof SEVERITIES)[number]>("medium");

  useEffect(() => {
    if (!brandId) return;
    let live = true;
    api
      .brandRules(brandId)
      .then((data) => {
        if (!live) return;
        setLoad({ state: "ok", data });
        setText(pretty(editable(data.rules)));
      })
      .catch((error) => live && setLoad({ state: "error", error }));
    return () => {
      live = false;
    };
  }, [brandId, tick]);

  const parsed = useMemo((): { ok: true; value: Item } | { ok: false; error: string } => {
    try {
      const v = JSON.parse(text);
      if (!v || typeof v !== "object" || Array.isArray(v)) return { ok: false, error: "The rules must be one JSON object, like { \"prohibited_terms\": [...] }." };
      return { ok: true, value: v as Item };
    } catch (e) {
      return { ok: false, error: `That isn’t valid JSON yet: ${(e as Error).message}` };
    }
  }, [text]);
  const saved = load.state === "ok" ? pretty(editable(load.data.rules)) : "{}";
  const dirty = text.trim() !== saved.trim();

  const save = async (rules: Item | null) => {
    if (!brandId) return;
    setBusy(true);
    setMsg(null);
    try {
      const data = await api.saveBrandRules(brandId, rules as BrandRules | null);
      setLoad({ state: "ok", data });
      setText(pretty(editable(data.rules)));
      setMsg({
        ok: true,
        text: data.rules
          ? `Saved${data.rules.version ? ` as version ${data.rules.version}` : ""}. New checks use these rules; earlier reviews keep the rules they ran with.`
          : "Rules removed. The default accessibility checks still run on every draft.",
      });
    } catch (err) {
      // 422: the server's message names fields and rule ids only, so show it exactly.
      setMsg({ ok: false, text: err instanceof ApiError && err.status === 422 ? err.message : err instanceof ApiError ? err.userMessage : "Something went wrong. Please try again." });
    } finally {
      setBusy(false);
      setConfirmClear(false);
    }
  };

  const quickAdd = (e: FormEvent) => {
    e.preventDefault();
    if (!parsed.ok) return setMsg({ ok: false, text: "Fix the JSON in “Edit all rules” first, then add the rule." });
    const t = term.trim();
    if (!t) return;
    const next: Item = { ...parsed.value };
    const items = Array.isArray(next[kind]) ? [...(next[kind] as Item[])] : [];
    const rule: Item = { rule_id: newRuleId(kind === "prohibited_terms" ? "no" : "req", t, allRuleIds(next)), term: t, severity: sev };
    if (kind === "prohibited_terms" && alt.trim()) rule.approved_alternative = alt.trim();
    items.push(rule);
    next[kind] = items;
    setText(pretty(next));
    setTerm("");
    setAlt("");
    setMsg({ ok: true, text: `Added “${t}”. Not saved yet: press Save rules.` });
  };

  if (brands.state === "loading") return (<><StageHead title="Brand rules" /><LoadingState /></>);
  if (brands.state === "error") return (<><StageHead title="Brand rules" /><ErrorState message={brands.message} onRetry={refresh} /></>);
  if (brands.state === "none") return (<><StageHead title="Brand rules" /><EmptyState title="No brand yet">This account has no brand yet.</EmptyState></>);

  const current = parsed.ok ? parsed.value : load.state === "ok" ? editable(load.data.rules) : {};
  const shown = LISTS.filter((l) => Array.isArray(current[l.key]) && (current[l.key] as Item[]).length);
  const server = load.state === "ok" ? load.data.rules : null;

  return (
    <div className="add-insights">
      <StageHead title="Brand rules" status={server ? `Version ${server.version ?? "–"}` : load.state === "ok" ? "No rules set" : undefined} />
      <BrandBar brand={brands.brand} brands={brands.brands} fallback={brands.fallback} onChoose={choose} />
      {msg && (
        <p className={`app-alert ${msg.ok ? "app-alert--ok" : "app-alert--bad"}`} role={msg.ok ? "status" : "alert"}>
          {msg.text}
        </p>
      )}
      {load.state === "loading" && <LoadingState label="Loading the rules…" />}
      {load.state === "error" && <ErrorState error={load.error} onRetry={() => setTick((t) => t + 1)} />}

      {load.state === "ok" && (
        <>
          <Panels cols="2">
            <Panel n="01" label="Your rules" title={dirty ? "Your rules (unsaved changes)" : "Your rules"}>
              {shown.length === 0 && !current.style ? (
                <EmptyState title="No brand rules yet">Drafts are still checked for accessibility (all capitals, emoji runs, vague links and more) with the default settings.</EmptyState>
              ) : (
                <div className="add-stack">
                  {shown.map((l) => (
                    <div key={l.key}>
                      <p className="t-caption">{l.label}</p>
                      <ul className="rows">
                        {(current[l.key] as Item[]).map((r, i) => (
                          <li key={String(r.rule_id ?? i)} className="rows__item">
                            <div>
                              <p className="rows__title">{l.describe(r)}</p>
                              <p className="rows__meta">
                                {String(r.severity ?? "medium")} · <span className="add-mono">{String(r.rule_id ?? "")}</span>
                              </p>
                            </div>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                  {current.style ? <p className="add-note">Accessibility settings are customised (see “Edit all rules”).</p> : null}
                </div>
              )}
            </Panel>

            <Panel n="02" label="Add a rule" title="Quick add">
              <form className="add-stack" onSubmit={quickAdd}>
                <label className="add-field-row">
                  <span className="field__label">Kind</span>
                  <select className="add-select" value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>
                    <option value="prohibited_terms">Never say this word</option>
                    <option value="required_terms">Always include this word</option>
                  </select>
                </label>
                <label className="add-field-row">
                  <span className="field__label">Word or phrase</span>
                  <input className="field__input" value={term} onChange={(e) => setTerm(e.target.value)} maxLength={500} placeholder={kind === "prohibited_terms" ? "e.g. guaranteed" : "e.g. Lumen Goods"} />
                </label>
                {kind === "prohibited_terms" && (
                  <label className="add-field-row">
                    <span className="field__label">Say instead (optional)</span>
                    <input className="field__input" value={alt} onChange={(e) => setAlt(e.target.value)} maxLength={500} placeholder="e.g. designed" />
                  </label>
                )}
                <label className="add-field-row">
                  <span className="field__label">How serious</span>
                  <select className="add-select" value={sev} onChange={(e) => setSev(e.target.value as (typeof SEVERITIES)[number])}>
                    {SEVERITIES.map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ))}
                  </select>
                </label>
                <button type="submit" className="add-btn-small" disabled={!term.trim()}>
                  + Add to the rules below
                </button>
                <p className="add-note add-muted">Other kinds (spelling, product names, disclaimers, number limits, accessibility settings) can be edited in “Edit all rules”.</p>
              </form>
            </Panel>
          </Panels>

          <section className="rule-checks card" aria-labelledby="rules-json-title" style={{ marginTop: 22 }}>
            <h2 id="rules-json-title" className="panel__title">
              Edit all rules
            </h2>
            <p className="add-note">
              Every rule kind, as JSON. The server sets the rule set id and version, so leave those out. Saving checks the rules; if something is
              wrong, the message names the field or rule.
            </p>
            <textarea className="add-editor__text add-rules-json" value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} aria-label="All rules as JSON" />
            {!parsed.ok && <p className="app-alert app-alert--bad" role="alert">{parsed.error}</p>}
            <div className="add-row">
              <Button type="button" onClick={() => parsed.ok && save(parsed.value)} disabled={busy || !parsed.ok || !dirty} aria-busy={busy}>
                {busy ? "Saving…" : "Save rules"}
              </Button>
              <button type="button" className="add-btn-small" onClick={() => setText(saved)} disabled={busy || !dirty}>
                Undo changes
              </button>
              <button type="button" className="add-btn-small" onClick={() => setConfirmClear(true)} disabled={busy || !server}>
                Remove all rules
              </button>
            </div>
          </section>
        </>
      )}

      <ConfirmDialog
        open={confirmClear}
        title="Remove all brand rules?"
        confirmLabel="Remove rules"
        busy={busy}
        onConfirm={() => save(null)}
        onCancel={() => setConfirmClear(false)}
      >
        <p>New drafts will no longer be checked against your terminology and compliance rules. The default accessibility checks still run. Earlier reviews keep the rules they ran with.</p>
      </ConfirmDialog>
    </div>
  );
}
