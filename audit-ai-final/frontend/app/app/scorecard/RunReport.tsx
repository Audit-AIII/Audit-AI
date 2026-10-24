"use client";

import { Metric } from "@/components/additions/Metrics";
import { Panel, Panels } from "@/components/app/Stage";
import { formatRate, formatRatio, providerModeText, type Ratio, type RunEvaluation } from "@/lib/additions/evaluationRun";

/**
 * One stored evaluation run (EvaluationOut from GET /api/evaluations/latest or POST /api/evaluations).
 * Every number is the backend's: nothing is computed, merged, defaulted or judged here. No pass/fail
 * verdict and no target: the backend sends neither. null is "–".
 */
const SPLIT_LABEL: Record<string, string> = { dev: "Development set (dev)", heldout: "Held-out set (heldout)" };
const words = (k: string) => k.replace(/_/g, " ");

function RatioCell({ r }: { r: Ratio }) {
  return (
    <>
      {formatRate(r.value)} <span className="add-muted">({formatRatio(r)})</span>
    </>
  );
}

export function RunReport({ run }: { run: RunEvaluation }) {
  const mode = providerModeText(run.provider_mode);
  return (
    <div className="add-stack">
      <section className="app-alert app-alert--placeholder" role="note" aria-label="What this measures">
        <b>What this measures.</b> This tests the claim checker on a small labelled set. It is not the accuracy of every review.
        <br />
        <span>
          Coverage: <span className="add-mono">{run.coverage}</span>
        </span>
        <br />
        <span>{run.limits_note}</span>
      </section>
      {!mode.live && (
        <div className="app-alert app-alert--bad" role="note">
          <b>{mode.label}</b>
        </div>
      )}

      <Panel n="01" label="Headline" title="Latest evaluation run">
        <div className="add-metrics">
          <Metric label="Catch rate" value={formatRate(run.catch_rate)} target={`Sample: ${run.sample_size} labelled claims`} />
          <Metric label="False-positive rate" value={formatRate(run.false_positive_rate)} target={`Sample: ${run.sample_size} labelled claims`} />
        </div>
        <p className="add-note add-muted">
          <b>Catch rate:</b> claims labelled contradicted or no-evidence that the checker flagged. <b>False-positive rate:</b> claims
          labelled supported that it flagged anyway. A claim that got no answer counts as not flagged (see provider failure rate). “–”
          means there were no claims of that kind to measure. Read the two together.
        </p>
      </Panel>

      <Panels cols="2">
        <Panel n="02" label="By split" title="Development and held-out, kept apart">
          {run.by_split === null ? (
            <p className="add-note">This run was stored before per-split numbers were recorded, so none are shown.</p>
          ) : (
            <div className="add-table__wrap">
              <table className="add-table">
                <caption className="add-sr">Each split measured on its own; the splits are never added together.</caption>
                <thead>
                  <tr>
                    <th scope="col">Split</th>
                    <th scope="col">Claims</th>
                    <th scope="col">Catch rate</th>
                    <th scope="col">False-positive rate</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(run.by_split).map(([name, s]) => (
                    <tr key={name}>
                      <th scope="row">{SPLIT_LABEL[name] ?? words(name)}</th>
                      <td>{s.n}</td>
                      <td>
                        <RatioCell r={s.catch_rate} />
                      </td>
                      <td>
                        <RatioCell r={s.false_positive_rate} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="add-note add-muted">Held-out claims were never used to tune the checker. The splits are small, so one claim moves a rate a lot.</p>
        </Panel>

        <Panel n="03" label="Per check" title="Each check on its own">
          {run.per_check.length === 0 ? (
            <p className="add-note">This run recorded no per-check numbers.</p>
          ) : (
            <div className="add-table__wrap">
              <table className="add-table">
                <caption className="add-sr">Catch and false-positive rate for each check, with the number of labelled claims it covered.</caption>
                <thead>
                  <tr>
                    <th scope="col">Check</th>
                    <th scope="col">Claims</th>
                    <th scope="col">Catch rate</th>
                    <th scope="col">False-positive rate</th>
                  </tr>
                </thead>
                <tbody>
                  {run.per_check.map((c) => (
                    <tr key={c.check}>
                      <th scope="row">{words(c.check)}</th>
                      <td>{c.n}</td>
                      <td>{formatRate(c.catch_rate)}</td>
                      <td>{formatRate(c.false_positive_rate)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </Panels>

      <Panel n="04" label="Run details" title="How and when it ran">
        <dl className="spec">
          <Row k="Run at" v={new Date(run.run_at).toLocaleString()} />
          <Row k="AI model" v={mode.label} />
          <Row k="Status" v={run.status === "partial" ? "partial (some claims got no answer from the AI provider)" : run.status} />
          <Row k="Typical answer time (p50)" v={run.latency_ms_p50 === null ? "–" : `${Math.round(run.latency_ms_p50)} ms`} />
          <Row k="Provider failure rate" v={formatRate(run.provider_failure_rate)} />
          <Row k="Dataset version" v={run.dataset_version} mono />
          <Row k="Engine prompt version" v={run.engine_prompt_version ?? "–"} mono />
          <Row k="Run id" v={run.id} mono />
        </dl>
      </Panel>
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
