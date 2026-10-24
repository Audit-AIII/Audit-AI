"use client";

import { useEffect, useState, type CSSProperties } from "react";
import { BrandBar } from "@/components/additions/BrandBar";
import { Bars, Metric, duration, pct } from "@/components/additions/Metrics";
import { EmptyState, ErrorState, LoadingState, NeedsBackend } from "@/components/additions/States";
import { Panel, Panels, StageHead } from "@/components/app/Stage";
import { verdict } from "@/components/app/reviewLabels";
import { brandRisk, type BrandRisk, type Maybe } from "@/lib/additions/analytics";
import { useBrands } from "@/lib/additions/brands";
import { lastDays, placeholderCount, statusCounts, VERDICT_KINDS, verdictMix, type VerdictKind } from "@/lib/additions/dashboard";
import { request } from "@/lib/additions/http";
import { listSources } from "@/lib/additions/sources";
import type { BrandSourceOut, ReviewOut } from "@/lib/api/types";

type Load = { state: "loading" } | { state: "ok"; result: Maybe<BrandRisk> } | { state: "error"; error: unknown };
/** The brand's latest reviews (backend page limit 100) and documents: the extra panels count these. */
type Extra = { state: "loading" } | { state: "ok"; reviews: ReviewOut[]; sources: BrandSourceOut[] } | { state: "error"; error: unknown };
const REVIEW_LIMIT = 100;

const KIND_LOOK: Record<VerdictKind, { glyph: string; label: string; tone: string }> = {
  contradicted: verdict("contradicted"),
  conflicting_sources: { glyph: "⇄", label: "Documents disagree", tone: "unverified" },
  unverified: verdict("unverified"),
  rule: { glyph: "§", label: "Brand rule", tone: "rule" },
  supported: verdict("supported"),
};

/** Plain words for the backend's category keys; unknown keys fall back to the key with spaces. */
const CATEGORY: Record<string, string> = {
  contradicted_claim: "Claims that contradict your documents",
  unsupported_claim: "Claims with no evidence yet",
  supported_claim: "Claims that match your documents",
  engine_error: "Could not be checked",
  // Brand-rule findings (check_type "rule")
  terminology: "Wording that doesn't match your terms",
  brand_compliance: "Required wording missing",
  accessibility: "Accessibility issues",
};
const categoryLabel = (key: string) => CATEGORY[key] ?? key.replace(/_/g, " ");

/** Dashboard: what gets flagged for the brand and how reviews move. Every number comes from the API. */
export function Insights() {
  const { value: brands, refresh, choose } = useBrands();
  const brandId = brands.state === "ready" ? brands.brand.id : null;
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [tick, setTick] = useState(0);
  const [extra, setExtra] = useState<Extra>({ state: "loading" });
  useEffect(() => {
    if (!brandId) return;
    let live = true;
    brandRisk(brandId)
      .then((result) => live && setLoad({ state: "ok", result }))
      .catch((error) => live && setLoad({ state: "error", error }));
    Promise.all([request<ReviewOut[]>(`/api/reviews?brand_id=${encodeURIComponent(brandId)}&limit=${REVIEW_LIMIT}`), listSources(brandId)])
      .then(([reviews, sources]) => live && setExtra({ state: "ok", reviews, sources }))
      .catch((error) => live && setExtra({ state: "error", error }));
    return () => {
      live = false;
    };
  }, [brandId, tick]);

  if (brands.state === "loading") return (<><StageHead title="Dashboard" /><LoadingState /></>);
  if (brands.state === "error") return (<><StageHead title="Dashboard" /><ErrorState message={brands.message} onRetry={refresh} /></>);
  if (brands.state === "none") return (<><StageHead title="Dashboard" /><EmptyState title="No brand yet">This account has no brand yet.</EmptyState></>);

  const data = load.state === "ok" && load.result.available ? load.result.data : null;

  return (
    <div className="add-insights">
      <StageHead title="Dashboard" />
      <BrandBar brand={brands.brand} brands={brands.brands} fallback={brands.fallback} onChoose={choose} />

      {load.state === "loading" && <LoadingState label="Loading insights…" />}
      {load.state === "error" && <ErrorState error={load.error} onRetry={() => setTick((t) => t + 1)} />}
      {load.state === "ok" && !load.result.available && (
        <NeedsBackend>
          <code className="add-mono">GET /api/analytics/brand-risk</code> is not on this server, so no numbers are shown for {brands.brand.name}.
        </NeedsBackend>
      )}

      {data && (
        <>
          <p className="add-note add-muted add-insights__basis">
            {brands.brand.name} · Based on {data.sample_size} review{data.sample_size === 1 ? "" : "s"}.
          </p>
          {data.sample_size === 0 ? (
            <EmptyState title="No reviews yet">Check a draft and its results will show up here.</EmptyState>
          ) : (
            <>
              <RiskPanels data={data} />
              {extra.state === "loading" && <LoadingState label="Loading your reviews…" />}
              {extra.state === "error" && <ErrorState error={extra.error} onRetry={() => setTick((t) => t + 1)} />}
              {extra.state === "ok" && <MorePanels data={data} reviews={extra.reviews} sources={extra.sources} />}
            </>
          )}
        </>
      )}
    </div>
  );
}

function RiskPanels({ data }: { data: BrandRisk }) {
  const max = Math.max(1, ...data.top_categories.map((c) => c.count));
  return (
    <Panels cols="2">
      <Panel n="01" label="Top issues" title="What gets flagged most">
        {data.top_categories.length ? (
          <Bars items={data.top_categories.map((c) => ({ label: categoryLabel(c.category), value: c.count, max }))} format={(v) => String(v)} />
        ) : (
          <EmptyState title="Nothing flagged yet">No checked claim has been flagged for this brand.</EmptyState>
        )}
      </Panel>
      <Panel n="02" label="Speed" title="How reviews move">
        <div className="add-metrics">
          <Metric label="Median turnaround" value={duration(data.median_turnaround_minutes)} />
          <Metric label="Sent back and re-reviewed" value={pct(data.re_review_rate)} />
          <Metric label="Queue age (median)" value={duration(data.queue_age_minutes.median)} />
          <Metric label="Oldest in queue" value={duration(data.queue_age_minutes.oldest)} />
        </div>
      </Panel>
    </Panels>
  );
}

/**
 * Counted from the reviews and documents the API returned (nothing estimated): where drafts stand,
 * what the checker said across all findings, the last 7 days, your own dismissals, your documents.
 */
function MorePanels({ data, reviews, sources }: { data: BrandRisk; reviews: ReviewOut[]; sources: BrandSourceOut[] }) {
  const statuses = statusCounts(reviews);
  const smax = Math.max(1, ...statuses.map((s) => s.count));
  const mix = verdictMix(reviews);
  const total = VERDICT_KINDS.reduce((n, k) => n + mix[k], 0);
  const days = lastDays(reviews);
  const dmax = Math.max(1, ...days.map((d) => d.count));
  const placeholders = placeholderCount(reviews);
  const dismissed = data.dismissed_finding_rate ?? null;
  const docs = { approved: sources.filter((s) => s.status === "approved").length, waiting: sources.filter((s) => s.status === "draft").length, withdrawn: sources.filter((s) => s.status !== "approved" && s.status !== "draft").length };
  const basis = `From your latest ${reviews.length} review${reviews.length === 1 ? "" : "s"}${reviews.length >= REVIEW_LIMIT ? " (the most the server returns at once)" : ""}.`;

  return (
    <>
      <Panels cols="3">
        <Panel n="03" label="Your drafts" title="Where they stand">
          <ul className="add-status-list">
            {statuses.map((s) => (
              <li key={s.key} className={s.count ? undefined : "is-zero"}>
                <span className={`add-badge add-badge--${s.tone}`}>
                  <span aria-hidden="true">{s.glyph}</span> {s.label}
                </span>
                <span className="add-bars__track" aria-hidden="true">
                  <span className="add-bars__fill" style={{ width: `${(s.count / smax) * 100}%` }} />
                </span>
                <b>{s.count}</b>
              </li>
            ))}
          </ul>
          <p className="add-note add-muted">{basis}</p>
        </Panel>

        <Panel n="04" label="Verdicts" title="What the checker said">
          {total === 0 ? (
            <EmptyState title="No checked claims yet">{placeholders ? "Every review so far is a placeholder: no AI service checked them." : "Check a draft to see results here."}</EmptyState>
          ) : (
            <>
              <div className="add-mix" role="img" aria-label={VERDICT_KINDS.map((k) => `${mix[k]} ${KIND_LOOK[k].label}`).join(", ")}>
                {VERDICT_KINDS.filter((k) => mix[k] > 0).map((k) => (
                  <span key={k} className={`add-mix__seg add-mix__seg--${k}`} style={{ flexGrow: mix[k] }} />
                ))}
              </div>
              <ul className="add-mix__legend">
                {VERDICT_KINDS.map((k) => (
                  <li key={k} className={mix[k] ? undefined : "is-zero"}>
                    <span className={`chip chip--${KIND_LOOK[k].tone}`}>
                      {KIND_LOOK[k].glyph} {KIND_LOOK[k].label}
                    </span>
                    <b>{mix[k]}</b>
                    <span className="add-muted">{Math.round((mix[k] / total) * 100)}%</span>
                  </li>
                ))}
              </ul>
            </>
          )}
          <p className="add-note add-muted">
            {total} finding{total === 1 ? "" : "s"} across these reviews{placeholders ? `; ${placeholders} placeholder review${placeholders === 1 ? "" : "s"} left out` : ""}.
          </p>
        </Panel>

        <Panel n="05" label="Activity" title="Last 7 days">
          <ol className="add-cols" aria-label="Reviews started per day, last 7 days">
            {days.map((d, i) => (
              <li key={d.key} style={{ "--i": i } as CSSProperties}>
                <span className="add-cols__n">{d.count}</span>
                <span className="add-cols__bar" aria-hidden="true">
                  <span style={{ height: `${(d.count / dmax) * 100}%` }} />
                </span>
                <span className="add-cols__day">{d.label}</span>
              </li>
            ))}
          </ol>
          <p className="add-note add-muted">
            {days.reduce((n, d) => n + d.count, 0)} reviews started this week (your local days).
          </p>
        </Panel>
      </Panels>

      <Panels cols="2">
        <Panel n="06" label="Your decisions" title="What you dismissed">
          {dismissed ? (
            <div className="add-metrics">
              <Metric label="Flagged findings you dismissed" value={pct(dismissed.value)} target={`${dismissed.numerator} of ${dismissed.denominator}`} />
            </div>
          ) : (
            <NeedsBackend>this server doesn’t send <code className="add-mono">dismissed_finding_rate</code> yet.</NeedsBackend>
          )}
          <p className="add-note add-muted">
            Your own decisions, not a measured accuracy. A high share can mean a rule or a document needs updating.
          </p>
        </Panel>
        <Panel n="07" label="Your documents" title="What drafts are checked against">
          <div className="add-metrics">
            <Metric label="Approved, used for checks" value={String(docs.approved)} />
            <Metric label="Waiting for approval" value={String(docs.waiting)} />
            <Metric label="Withdrawn or replaced" value={String(docs.withdrawn)} />
          </div>
          <a className="link" href="/app/sources">
            Manage documents →
          </a>
        </Panel>
      </Panels>
    </>
  );
}
