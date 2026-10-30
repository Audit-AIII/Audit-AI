"use client";

import { Metric } from "@/components/additions/Metrics";
import { Panel, Panels } from "@/components/app/Stage";
import { measured, NOT_EVALUATED, providerModeText, ratioText, type Ratio, type RunEvaluation } from "@/lib/additions/evaluationRun";

/**
 * One stored evaluation run (EvaluationOut from GET /api/evaluations/latest or POST /api/evaluations).
 * Every number is the backend's: nothing is computed, merged, defaulted or judged here. No pass/fail
 * verdict and no target: the backend sends neither. Nothing measured reads "Not evaluated", and a
 * real 0 stays 0%. Fields the API doesn't send read "Not provided".
 */
const SPLIT_LABEL: Record<string, string> = { dev: "Development set (tuned on this data)", heldout: "Held-out set (never used for tuning)" };
const NOT_PROVIDED = "Not provided";
const words = (k: string) => k.replace(/_/g, " ");

function NotEvaluated() {
  return (
    <span className="add-badge add-badge--dashed">
      <span aria-hidden="true">◌</span> {NOT_EVALUATED}
    </span>
  );
}

const RateCell = ({ text }: { text: string | null }) => (text === null ? <NotEvaluated /> : <>{text}</>);
const RatioCell = ({ r }: { r: Ratio }) => <RateCell text={ratioText(r)} />;

export function RunReport({ run }: { run: RunEvaluation }) {
  const mode = providerModeText(run.provider_mode);
  const head = run.headline;
  const catchText = head ? ratioText(head.catch_rate) : measured(run.catch_rate);
  const falseText = head ? ratioText(head.false_positive_rate) : measured(run.false_positive_rate);
  // The API has no counts for its combined rates, so they aren't worked out here.
  const headTarget = head ? `${SPLIT_LABEL[head.split] ?? words(head.split)}, ${head.n} claims` : "Counts not supplied";
  return (
    <div className="add-stack add-run">
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
          <Metric label="Catch rate" value={catchText ?? NOT_EVALUATED} absent={catchText === null} target={headTarget} />
          <Metric label="False-positive rate" value={falseText ?? NOT_EVALUATED} absent={falseText === null} target={headTarget} />
        </div>
        {!head && (
          <p className="add-note">
            <b>These two rates combine every split, across {run.sample_size} labelled claims.</b>{" "}
            {run.by_split === null ? "This run has no separate numbers per split." : run.by_split.heldout ? "The development set was used to tune the checker, so the held-out row below is the fairer read." : ""}
          </p>
        )}
        <p className="add-note add-muted">How to read this: look at both rates together, because a checker can catch everything by flagging everything.</p>
        <details className="add-details">
          <summary>What do these mean?</summary>
          <dl className="spec">
            <Row k="Catch rate" v="Of the claims that really were wrong or had no evidence, how many the checker flagged." />
            <Row k="False-positive rate" v="Of the claims that were fine, how many it flagged anyway." />
            <Row k="Sample size" v="How many labelled test claims were used." />
            <Row k="Held-out" v="Test claims never used to tune the checker." />
            <Row k={NOT_EVALUATED} v="There was nothing of that kind to measure. It is different from 0%, which is a real result." />
            <Row k="No answer" v="A claim the AI provider didn’t answer counts as not flagged. See the provider failure rate below." />
          </dl>
        </details>
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
                      <td>
                        <RateCell text={measured(c.catch_rate, c.n)} />
                      </td>
                      <td>
                        <RateCell text={measured(c.false_positive_rate, c.n)} />
                      </td>
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
          <Row k="Run at" v={new Date(run.run_at).toLocaleString()} title={run.run_at} />
          <Row k="AI model" v={mode.label} />
          <Row k="Status" v={run.status === "partial" ? "partial (some claims got no answer from the AI provider)" : run.status} />
          <Row k="Sample size" v={`${run.sample_size} labelled claims`} />
          <Row k="Coverage" v={run.coverage} mono />
          <Row k="Typical answer time (p50)" v={run.latency_ms_p50 === null ? NOT_PROVIDED : `${Math.round(run.latency_ms_p50)} ms`} />
          <Row k="Provider failure rate" v={measured(run.provider_failure_rate) ?? NOT_PROVIDED} />
          <Row k="Dataset version" v={run.dataset_version} mono />
          <Row k="Engine prompt version" v={run.engine_prompt_version ?? NOT_PROVIDED} mono={run.engine_prompt_version !== null} />
          <Row k="Run id" v={run.id} mono />
        </dl>
      </Panel>
    </div>
  );
}

function Row({ k, v, mono = false, title }: { k: string; v: string; mono?: boolean; title?: string }) {
  return (
    <div className="spec__row">
      <dt>{k}</dt>
      <dd className={mono ? "add-mono" : undefined} title={title}>
        {v}
      </dd>
    </div>
  );
}
