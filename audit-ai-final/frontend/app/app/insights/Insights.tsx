"use client";

import { useEffect, useState } from "react";
import { BrandBar } from "@/components/additions/BrandBar";
import { Bars, Metric, duration, pct } from "@/components/additions/Metrics";
import { EmptyState, ErrorState, LoadingState, NeedsBackend } from "@/components/additions/States";
import { Panel, Panels, StageHead } from "@/components/app/Stage";
import { brandRisk, type BrandRisk, type Maybe } from "@/lib/additions/analytics";
import { useBrands } from "@/lib/additions/brands";

type Load = { state: "loading" } | { state: "ok"; result: Maybe<BrandRisk> } | { state: "error"; error: unknown };

/** Plain words for the backend's category keys; unknown keys fall back to the key with spaces. */
const CATEGORY: Record<string, string> = {
  contradicted_claim: "Claims that contradict your documents",
  unsupported_claim: "Claims with no evidence yet",
  supported_claim: "Claims that match your documents",
  engine_error: "Could not be checked",
  // Brand-rule findings (check_type "rule")
  terminology: "Wording that breaks your brand rules",
  brand_compliance: "Missing disclaimers or numbers out of range",
  accessibility: "Hard-to-read or inaccessible text",
};
const categoryLabel = (key: string) => CATEGORY[key] ?? key.replace(/_/g, " ");

/** Dashboard: what gets flagged for the brand and how reviews move. Every number comes from the API. */
export function Insights() {
  const { value: brands, refresh, choose } = useBrands();
  const brandId = brands.state === "ready" ? brands.brand.id : null;
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!brandId) return;
    let live = true;
    brandRisk(brandId)
      .then((result) => live && setLoad({ state: "ok", result }))
      .catch((error) => live && setLoad({ state: "error", error }));
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
            <RiskPanels data={data} />
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
