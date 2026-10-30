"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { ConfirmDialog } from "@/components/additions/ConfirmDialog";
import { Metric } from "@/components/additions/Metrics";
import { EmptyState, ErrorState, LoadingState, NeedsBackend } from "@/components/additions/States";
import { Panel, Panels, StageHead } from "@/components/app/Stage";
import { Thinking } from "@/components/app/Thinking";
import { Button } from "@/components/primitives/Button";
import { ApiError } from "@/lib/api/client";
import {
  latestEvaluation,
  runEvaluation,
  type EvalCase,
  type EvalGate,
  type EvaluationResponse,
  type EvaluationSummary,
  type LatestEvaluation,
  type Limitation,
  type Maybe,
} from "@/lib/additions/analytics";
import { RunReport } from "./RunReport";

/**
 * Trust Scorecard: the latest evaluation report of the verification engine (EVAL.md Phase 8).
 * Every number comes from GET /api/evaluations/latest: a stored run (EvaluationOut, see RunReport)
 * or the older evaluation-summary-v1 report. Nothing is computed or invented here.
 * Benchmark results on a labelled, synthetic dataset: never live production statistics.
 */
type Load = { state: "loading" } | { state: "ok"; result: Maybe<LatestEvaluation> } | { state: "error"; error: unknown };

/**
 * Run evaluation (POST /api/evaluations). Synchronous on the server, bounded by its call budget
 * (eval_deadline_seconds, 300 s), so the request has no client timeout. One run per user per
 * eval_min_interval_seconds (600 s), counted for discarded runs too.
 * "failed" keeps the backend's message as-is; `retryAt` keeps Retry disabled while a retry could only
 * hit the interval limit; `check` offers "Check for a result" (a run may still be going).
 */
type Run =
  | { phase: "idle" }
  | { phase: "confirm" }
  | { phase: "running" }
  | { phase: "failed"; message: string; retryAt: number | null; check: boolean };
const RUN_INTERVAL_MS = 10 * 60_000;
const RUNNING_TEXT = "Running... this can take up to 5 minutes. Keep this tab open.";
const NETWORK_TEXT = "Could not reach the server. The run may still be going; check again in a few minutes.";

function failure(err: unknown): Extract<Run, { phase: "failed" }> {
  const later = Date.now() + RUN_INTERVAL_MS;
  if (!(err instanceof ApiError)) return { phase: "failed", message: "Something went wrong. Please try again.", retryAt: null, check: false };
  if (err.status === 0) return { phase: "failed", message: NETWORK_TEXT, retryAt: later, check: true };
  if (err.status === 429) {
    if (/already running/i.test(err.message)) return { phase: "failed", message: err.message, retryAt: later, check: true };
    const minutes = Number(/every (\d+) minutes?/i.exec(err.message)?.[1]);
    return { phase: "failed", message: err.message, retryAt: minutes > 0 ? Date.now() + minutes * 60_000 : later, check: false };
  }
  // 409 after the provider was called (run discarded): it still counts toward the interval.
  if (err.status === 409 && /could not answer/i.test(err.message)) return { phase: "failed", message: err.message, retryAt: later, check: false };
  // 409 no provider / dataset problem: nothing ran, so a retry is allowed straight away.
  if (err.status === 409) return { phase: "failed", message: err.message, retryAt: null, check: false };
  return { phase: "failed", message: err.userMessage, retryAt: null, check: false };
}

const VERDICT: Record<string, { glyph: string; label: string; tone: string }> = {
  SUPPORTED: { glyph: "✓", label: "Supported", tone: "ok" },
  CONTRADICTED: { glyph: "≠", label: "Contradicted", tone: "bad" },
  NOT_ENOUGH_EVIDENCE: { glyph: "?", label: "Not enough evidence", tone: "warn" },
  ERROR: { glyph: "!", label: "Error (no verdict)", tone: "none" },
};
const OUTCOME: Record<string, { glyph: string; label: string; tone: string }> = {
  passed: { glyph: "✓", label: "Passed", tone: "ok" },
  failed: { glyph: "≠", label: "Failed", tone: "bad" },
  incomplete: { glyph: "…", label: "Incomplete", tone: "warn" },
};
const LIMITATION_GROUPS: { status: Limitation["status"]; title: string }[] = [
  { status: "measured", title: "Known and measured" },
  { status: "suspected", title: "Suspected, needs testing" },
  { status: "unsupported", title: "Not supported" },
  { status: "not_implemented", title: "Not implemented yet" },
];

function Badge({ kind, map }: { kind: string; map: Record<string, { glyph: string; label: string; tone: string }> }) {
  const v = map[kind] ?? { glyph: "?", label: kind.replace(/_/g, " "), tone: "none" };
  return (
    <span className={`add-badge add-badge--${v.tone}`}>
      <span aria-hidden="true">{v.glyph}</span> {v.label}
    </span>
  );
}

const num = (v: number | null) => (v === null ? "—" : Number.isInteger(v) ? String(v) : v.toFixed(3));
const entries = (r: Record<string, unknown> | null | undefined) => Object.entries(r ?? {});
const show = (v: unknown) => (v === null || v === undefined ? "not recorded" : typeof v === "object" ? JSON.stringify(v) : String(v));

export function Scorecard() {
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [tick, setTick] = useState(0);
  const [run, setRun] = useState<Run>({ phase: "idle" });
  const [now, setNow] = useState(() => Date.now());
  const sending = useRef(false);
  const retryAt = run.phase === "failed" ? run.retryAt : null;
  useEffect(() => {
    if (retryAt === null) return;
    const t = setInterval(() => setNow(Date.now()), 5_000);
    return () => clearInterval(t);
  }, [retryAt]);

  async function start() {
    if (sending.current) return; // no double submit
    sending.current = true;
    setRun({ phase: "running" });
    try {
      const result = await runEvaluation();
      setLoad({ state: "ok", result: { available: true, data: { kind: "run", run: result } } });
      setRun({ phase: "idle" });
      latestEvaluation() // refresh the latest state quietly; the returned run is already on screen
        .then((latest) => latest.available && latest.data.kind === "run" && setLoad({ state: "ok", result: latest }))
        .catch(() => {});
    } catch (err) {
      setNow(Date.now());
      setRun(failure(err));
    } finally {
      sending.current = false;
    }
  }
  const running = run.phase === "running";
  const waiting = retryAt !== null && now < retryAt;
  const openConfirm = () => setRun({ phase: "confirm" });
  const runButton = (
    <Button onClick={openConfirm} disabled={running || waiting} aria-busy={running}>
      {running ? "Running…" : "Run evaluation"}
    </Button>
  );

  useEffect(() => {
    let live = true;
    latestEvaluation()
      .then((result) => live && setLoad({ state: "ok", result }))
      .catch((error) => live && setLoad({ state: "error", error }));
    return () => {
      live = false;
    };
  }, [tick]);

  return (
    <>
      <StageHead title="Trust Scorecard" status="Benchmark results · not live statistics">
        {runButton}
      </StageHead>
      <p className="add-sr" role="status" aria-live="polite">
        {running ? RUNNING_TEXT : ""}
      </p>
      {running && <Thinking label="Running the evaluation" detail="This can take up to 5 minutes. Keep this tab open." announce={false} />}
      {run.phase === "failed" && (
        <div className="app-alert app-alert--bad add-stack" role="alert">
          <span>
            <b>The evaluation did not run.</b> {run.message}
          </span>
          <span className="add-row">
            <button type="button" className="add-btn-small" onClick={openConfirm} disabled={waiting}>
              Retry
            </button>
            {run.check && (
              <button type="button" className="add-btn-small" onClick={() => setTick((t) => t + 1)}>
                Check for a result
              </button>
            )}
            {waiting && retryAt !== null && (
              <span className="add-note">
                Retry is available from {new Date(retryAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} (one run every 10 minutes).
              </span>
            )}
          </span>
        </div>
      )}
      <ConfirmDialog
        open={run.phase === "confirm"}
        title="Run evaluation?"
        confirmLabel="Run evaluation"
        onConfirm={start}
        onCancel={() => setRun({ phase: "idle" })}
      >
        <p>
          This sends the labelled benchmark test claims to the AI provider. It takes 1 to 5 minutes, uses provider quota, and can be run once
          every 10 minutes.
        </p>
      </ConfirmDialog>
      {load.state === "loading" && <LoadingState label="Loading the latest evaluation…" />}
      {load.state === "error" && <ErrorState error={load.error} onRetry={() => setTick((t) => t + 1)} />}
      {load.state === "ok" && !load.result.available && (
        <NeedsBackend>
          <code className="add-mono">GET /api/evaluations/latest</code> is not on this server. No evaluation number is shown without it.
        </NeedsBackend>
      )}
      {load.state === "ok" && load.result.available &&
        (load.result.data.kind === "run" ? <RunReport run={load.result.data.run} /> : <Result data={load.result.data.summary} runButton={runButton} />)}
    </>
  );
}

function Result({ data, runButton }: { data: EvaluationResponse; runButton: ReactNode }) {
  if (data.state === "none") {
    return (
      <EmptyState title="No evaluation yet">
        <p className="add-note">Results appear here after an evaluation is run. These are benchmark results, not live statistics.</p>
        {data.how_to_run && <code className="add-mono">{data.how_to_run}</code>}
        <div style={{ marginTop: 12 }}>{runButton}</div>
      </EmptyState>
    );
  }
  if (data.state === "incomplete") {
    return (
      <div className="add-stack">
        <div className="app-alert app-alert--bad" role="alert">
          <b>The latest evaluation run did not finish</b> ({new Date(data.generated_at).toLocaleString()}). No result is shown for it.
          <br />
          <span className="add-mono">{data.error}</span>
        </div>
        <Limitations items={data.limitations} />
      </div>
    );
  }
  return <Summary s={data} />;
}

function Summary({ s }: { s: EvaluationSummary }) {
  const policy = s.decision_policy?.policy;
  const retrieval = s.retrieval?.retrieval ?? {};
  const chunking = s.retrieval?.chunking ?? {};
  return (
    <div className="add-stack">
      {!s.source.is_model_quality && (
        <div className="app-alert app-alert--placeholder" role="note">
          <b>Not a measure of model accuracy.</b> These answers came from a {s.source.kind} ({s.source.verdict_source}), not a live
          model. They show what the engine’s own checks let through; real-model accuracy has not been measured.
        </div>
      )}
      {s.stale && (
        <div className="app-alert app-alert--bad" role="alert">
          <b>Stale report.</b> {s.stale_reason}. Run the evaluation again for current numbers.
        </div>
      )}

      <Panels cols="2">
        <Panel n="01" label="Run" title="Latest evaluation">
          <div className="add-row">
            <Badge kind={s.outcome.status} map={OUTCOME} />
            <span className="add-note add-muted">{new Date(s.generated_at).toLocaleString()}</span>
          </div>
          {s.outcome.reasons.length > 0 && (
            <ul className="add-note">
              {s.outcome.reasons.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          )}
          <dl className="spec">
            <Row k="Report" v={s.report_id ?? "not recorded"} mono />
            <Row k="Answers from" v={`${s.source.kind} (${s.source.verdict_source})`} />
            <Row k="Provider" v={s.model.provider ?? "none"} />
            <Row k="Model" v={s.model.model_ids.length ? s.model.model_ids.join(", ") : "not recorded"} />
            <Row k="Prompt versions" v={entries(s.prompt_versions).map(([k, v]) => `${k}: ${v}`).join(" · ") || "not recorded"} />
            <Row k="Engine" v={`${show(s.source.engine_version)} · commit ${show(s.source.git_commit).slice(0, 10)}`} />
          </dl>
        </Panel>

        <Panel n="02" label="Dataset and configuration" title="What was evaluated">
          <dl className="spec">
            <Row k="Dataset" v={`${show(s.dataset.path)} · ${show(s.dataset.records)} records${s.dataset.locked ? "" : " · not the locked set"}`} />
            <Row k="Labels" v={entries(s.dataset.labels).map(([k, v]) => `${VERDICT[k]?.label ?? k} ${v}`).join(" · ") || "not recorded"} />
            <Row k="Class mix" v={entries(s.dataset.groups).map(([k, v]) => `${k.replace(/_/g, " ").toLowerCase()} ${v}`).join(" · ") || "not recorded"} />
            <Row k="Reviewed by a person" v={`${show(s.dataset.human_reviewed)} of ${show(s.dataset.records)} labels`} />
            <Row k="Dataset hash" v={show(s.dataset.sha256).slice(0, 16)} mono />
            <Row k="Retrieval" v={`top ${show(retrieval.top_k)} · ${show(chunking.strategy)} chunks · min term coverage ${show(retrieval.min_term_coverage)}`} />
            <Row
              k="Decision policy"
              v={`${show(policy?.version)} · ${entries(policy?.thresholds).map(([k, v]) => `${k.replace(/_/g, " ")} ${show(v)}`).join(" · ")}`}
            />
            <Row k="Calibration" v={`${show(s.decision_policy?.calibration?.status)} (${show(s.decision_policy?.calibration?.split)} split)`} />
          </dl>
        </Panel>
      </Panels>

      <Panel n="03" label="Eight required metrics" title="How the engine did">
        <div className="add-metrics">
          {s.metrics.map((m) => (
            <Metric key={m.key} label={m.label} value={m.value === null ? "—" : m.display} target={m.unavailable_reason ? `Unavailable: ${m.unavailable_reason}` : undefined} />
          ))}
        </div>
        <dl className="spec" style={{ marginTop: 16 }}>
          {s.metrics.map((m) => (
            <Row key={m.key} k={m.label} v={m.explanation} />
          ))}
        </dl>
        <p className="add-note add-muted">
          Positive class: Contradicted. TP {s.counts.tp} · FP {s.counts.fp} · FN {s.counts.fn} · TN {s.counts.tn}. No single score is shown:
          read the metrics together. Small sets move a lot per record.
        </p>
      </Panel>

      <Panel n="04" label="Confusion matrix" title="Expected versus predicted">
        <Confusion s={s} />
      </Panel>
      <Panel n="05" label="Baseline" title="Comparison with the agreed baseline">
        <Gates gates={s.gates} />
      </Panel>

      <Panel n="06" label="Representative cases" title="Real records from this run">
        {s.cases.length === 0 ? (
          <p className="add-note">This run has no per-case outcomes (it did not run the full pipeline), so no case can be shown.</p>
        ) : (
          <div className="add-stack">
            {s.cases.map((c) => (
              <Case key={c.record_id} c={c} />
            ))}
          </div>
        )}
      </Panel>

      <Limitations items={s.limitations} />
    </div>
  );
}

function Row({ k, v, mono = false }: { k: string; v: string; mono?: boolean }) {
  return (
    <div className="spec__row">
      <dt>{k}</dt>
      <dd className={mono ? "add-mono" : undefined}>{v}</dd>
    </div>
  );
}

function Confusion({ s }: { s: EvaluationSummary }) {
  const rows = Object.keys(s.confusion);
  const cols = rows.length ? Object.keys(s.confusion[rows[0]]) : [];
  const auto = s.review.auto_cleared_but_not_supported ?? [];
  return (
    <>
      <div className="add-table__wrap">
        <table className="add-table">
          <caption className="add-sr">Rows are the expected labels, columns the engine’s predictions.</caption>
          <thead>
            <tr>
              <th scope="col">Expected ↓ / predicted →</th>
              {cols.map((c) => (
                <th key={c} scope="col">{VERDICT[c]?.label ?? c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r}>
                <th scope="row">{VERDICT[r]?.label ?? r}</th>
                {cols.map((c) => {
                  const wrongApproval = c === "SUPPORTED" && r !== "SUPPORTED" && s.confusion[r][c] > 0;
                  return (
                    <td key={c}>
                      {s.confusion[r][c]}
                      {wrongApproval && <span className="add-badge add-badge--bad"> wrong approval</span>}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="add-note add-muted">
        A <b>wrong approval</b> is a claim predicted Supported when it is not: the costly mistake. An <b>unnecessary review</b> is a Supported
        claim sent to a person anyway: it costs time, not trust. In this run {show(s.review.routed_by_label?.SUPPORTED ?? 0)} Supported records
        went to review, and {auto.length ? `${auto.length} non-Supported record(s) were cleared without review (${auto.join(", ")})` : "no non-Supported record was cleared without review"}.
      </p>
    </>
  );
}

function GateTable({ gates, caption }: { gates: EvalGate[]; caption: string }) {
  return (
    <div className="add-table__wrap">
      <table className="add-table">
        <caption className="add-sr">{caption}</caption>
        <thead>
          <tr>
            <th scope="col">Gate</th>
            <th scope="col">Now</th>
            <th scope="col">Baseline</th>
            <th scope="col">Change</th>
            <th scope="col">Status</th>
          </tr>
        </thead>
        <tbody>
          {gates.map((g) => (
            <tr key={g.name}>
              <td>{g.name}</td>
              <td>{num(g.current)}</td>
              <td>{g.baseline === null ? "no baseline" : `${g.op} ${num(g.baseline)}`}</td>
              <td>{num(g.change)}</td>
              <td>
                <span className={`add-badge add-badge--${g.violated ? "bad" : g.status === "PASS" ? "ok" : "none"}`}>
                  {g.status === "NOT APPLICABLE" ? "Not applicable" : g.status === "NOT ENFORCED" ? "No baseline" : g.status}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Enforced gates first (failures on top); the ones that did not apply to this run stay one click away. */
function Gates({ gates }: { gates: EvalGate[] }) {
  if (gates.length === 0) return <p className="add-note">No baseline comparison was recorded for this run.</p>;
  const enforced = [...gates.filter((g) => g.enforced)].sort((a, b) => Number(b.violated) - Number(a.violated));
  const skipped = gates.filter((g) => !g.enforced);
  const failed = enforced.filter((g) => g.violated).length;
  return (
    <div className="add-stack">
      <p className="add-note">
        {enforced.length} gates checked against eval/baseline.json: {failed ? `${failed} failed` : "none failed"}.
      </p>
      <GateTable gates={enforced} caption="Gates enforced for this run, with this run's value and the agreed baseline." />
      {skipped.length > 0 && (
        <details className="add-details">
          <summary>{skipped.length} gates did not apply to this run or have no baseline yet</summary>
          <GateTable gates={skipped} caption="Gates that did not apply to this run." />
        </details>
      )}
    </div>
  );
}

function Case({ c }: { c: EvalCase }) {
  return (
    <article className="add-doc" aria-label={`Case ${c.record_id}`}>
      <div className="add-doc__top">
        <span className="add-doc__title add-mono">{c.record_id}</span>
        <span className="add-doc__meta">{c.split} split · outcome {c.outcome}{c.reason ? ` (${c.reason})` : ""}</span>
      </div>
      <div className="add-row">
        <span className="add-note">Expected</span> <Badge kind={c.expected} map={VERDICT} />
        <span className="add-note">Predicted</span> <Badge kind={c.predicted} map={VERDICT} />
        <span className={`add-badge add-badge--${c.agrees ? "ok" : "bad"}`}>
          <span aria-hidden="true">{c.agrees ? "=" : "≠"}</span> {c.agrees ? "Agrees with the label" : "Disagrees with the label"}
        </span>
      </div>
      <p className="add-note">
        <b>Submitted content:</b> {c.content}
      </p>
      <ul className="add-note">
        {c.claims.map((cl, i) => (
          <li key={i}>
            <b>Extracted claim:</b> {cl.text} → <Badge kind={cl.verdict} map={VERDICT} />{" "}
            {cl.requires_human_review ? `sent to a person (${cl.review_reasons.join(", ").replace(/_/g, " ")})` : "cleared without review"}
          </li>
        ))}
      </ul>
      {c.passages.map((p, i) => (
        <div className="add-window" key={i}>
          <span className="add-window__src">{p.title ?? p.doc_id}{p.truncated ? " (excerpt)" : ""}</span>
          <span className="add-window__quote">{p.text}</span>
        </div>
      ))}
      <p className="add-note">
        <b>Citations:</b>{" "}
        {c.citations.length === 0
          ? "none given"
          : c.citations.map((ct, i) => (
              <span key={i}>
                “{ct.quote}” ({ct.resolves ? "found verbatim in the reference" : "not found in the reference"};{" "}
                {ct.supports ? "supports the labelled verdict" : "does not support the labelled verdict"}){i < c.citations.length - 1 ? " · " : ""}
              </span>
            ))}
      </p>
      <p className="add-note">
        <b>Correction:</b>{" "}
        {c.corrections.length === 0
          ? "none (not applicable or not attempted)"
          : c.corrections.map((co) => `${co.status.replace(/_/g, " ")}${co.replacement_text ? `: “${co.replacement_text}”` : ""}`).join(" · ")}
        {" · "}
        <b>Human review:</b> {c.requires_human_review ? "required" : "not required"}
      </p>
    </article>
  );
}

function Limitations({ items }: { items: Limitation[] }) {
  return (
    <Panel n="07" label="Known limitations" title="What this evaluation does not show">
      <div className="add-stack">
        {LIMITATION_GROUPS.map(({ status, title }) => {
          const group = items.filter((l) => l.status === status);
          if (group.length === 0) return null;
          return (
            <section key={status} aria-label={title}>
              <h3 className="t-caption">{title}</h3>
              <ul className="add-note">
                {group.map((l) => (
                  <li key={l.topic}>
                    <b>{l.topic}.</b> {l.finding}
                    {l.evidence.length > 0 && (
                      <details className="add-details">
                        <summary>Evidence</summary>
                        <ul>
                          {l.evidence.map((e) => (
                            <li key={e} className="add-mono">{e}</li>
                          ))}
                        </ul>
                      </details>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
      </div>
    </Panel>
  );
}
