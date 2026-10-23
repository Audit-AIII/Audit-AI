"use client";

import { useEffect, useState } from "react";
import { Bars, Metric, pct } from "@/components/additions/Metrics";
import { ErrorState, LoadingState, NeedsBackend, SampleNotice } from "@/components/additions/States";
import { roleName } from "@/components/app/roles";
import { Panel, Panels, StageHead } from "@/components/app/Stage";
import { Button } from "@/components/primitives/Button";
import { SAMPLE_EVAL, TARGETS, latestEvaluation, runEvaluation, type Evaluation, type Maybe } from "@/lib/additions/analytics";
import { errorText } from "@/lib/additions/http";
import { useSession } from "@/lib/session";

type Load = { state: "loading" } | { state: "ok"; result: Maybe<Evaluation> } | { state: "error"; error: unknown };

export function Scorecard() {
  const role = useSession()?.role ?? "";
  const admin = role === "admin";
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [tick, setTick] = useState(0);
  const [running, setRunning] = useState(false);
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => {
    let live = true;
    latestEvaluation()
      .then((result) => live && setLoad({ state: "ok", result }))
      .catch((error) => live && setLoad({ state: "error", error }));
    return () => {
      live = false;
    };
  }, [tick]);

  const run = async () => {
    setRunning(true);
    setNote(null);
    try {
      const r = await runEvaluation();
      if (r.available) {
        setLoad({ state: "ok", result: r });
        setNote({ ok: true, text: "Evaluation finished." });
      } else {
        setNote({ ok: false, text: "The server can’t run evaluations yet. Today they’re run by the engine team with eval/run_eval.py." });
      }
    } catch (err) {
      setNote({ ok: false, text: errorText(err) });
    } finally {
      setRunning(false);
    }
  };

  const real = load.state === "ok" && load.result.available ? load.result.data : null;

  return (
    <>
      <StageHead title="Trust Scorecard" />
      {note && (
        <p className={`app-alert ${note.ok ? "app-alert--ok" : "app-alert--bad"}`} role={note.ok ? "status" : "alert"}>
          {note.text}
        </p>
      )}
      {load.state === "loading" && <LoadingState label="Loading the latest evaluation…" />}
      {load.state === "error" && <ErrorState error={load.error} onRetry={() => setTick((t) => t + 1)} />}

      {load.state === "ok" && (
        <Panels cols="2">
          <Panel n="01" label="Your measured results" title={real ? "Latest evaluation" : "Not measured yet"}>
            <div className="add-metrics">
              <Metric label="Catch rate" value={real ? pct(real.catch_rate) : "Not measured"} target={`Target ${pct(TARGETS.catchRate)} or more`} />
              <Metric label="False positives" value={real ? pct(real.false_positive_rate) : "Not measured"} target={`Target ${pct(TARGETS.falsePositiveRate)} or less`} />
              <Metric label="Sample size" value={real ? String(real.sample_size) : "–"} />
            </div>
            {real ? (
              <>
                <Bars items={real.per_check.map((c) => ({ label: `${c.check} (n=${c.n})`, value: c.catch_rate ?? 0, max: 1 }))} format={pct} />
                <p className="add-note add-muted">Run {new Date(real.run_at).toLocaleString()}.</p>
              </>
            ) : (
              <NeedsBackend>
                <code className="add-mono">GET /api/evaluations/latest</code> and <code className="add-mono">POST /api/evaluations</code>. The engine’s own
                notes (services/verification/EVAL.md) say no verifier results exist yet, so no number is shown here.
              </NeedsBackend>
            )}
            <div className="add-row">
              <Button type="button" onClick={run} disabled={!admin || running} aria-busy={running}>
                {running ? "Running…" : "Run evaluation"}
              </Button>
              {!admin && <span className="add-note add-muted">⊘ Only an admin can run an evaluation (you are {roleName(role)}).</span>}
            </div>
          </Panel>

          <Panel n="02" label="Read this first" title="What these numbers mean">
            <dl className="spec">
              <div className="spec__row">
                <dt>Catch rate</dt>
                <dd>Of the problems planted in the test drafts, how many were flagged.</dd>
              </div>
              <div className="spec__row">
                <dt>False positives</dt>
                <dd>Of the flags raised, how many were on text that was actually fine.</dd>
              </div>
              <div className="spec__row">
                <dt>Limits</dt>
                <dd>A small test set shows testing, not universal accuracy. Results can differ on your own content.</dd>
              </div>
              <div className="spec__row">
                <dt>Not proven yet</dt>
                <dd>Counted separately: a claim with no evidence is never scored as false.</dd>
              </div>
            </dl>
          </Panel>
        </Panels>
      )}

      {load.state === "ok" && !real && (
        <div className="add-stack" style={{ marginTop: 22 }}>
          <SampleNotice>The panel below uses made-up numbers to show the layout. It is not a measurement of Audit AI.</SampleNotice>
          <Panels cols="2">
            <Panel n="03" label="Example (sample)" title="Per check">
              <div className="add-metrics">
                <Metric label="Catch rate (sample)" value={pct(SAMPLE_EVAL.catch_rate)} />
                <Metric label="False positives (sample)" value={pct(SAMPLE_EVAL.false_positive_rate)} />
                <Metric label="Sample size (sample)" value={String(SAMPLE_EVAL.sample_size)} />
              </div>
              <Bars items={SAMPLE_EVAL.per_check.map((c) => ({ label: `${c.check} (n=${c.n})`, value: c.catch_rate ?? 0, max: 1 }))} format={pct} />
            </Panel>
          </Panels>
        </div>
      )}
    </>
  );
}
