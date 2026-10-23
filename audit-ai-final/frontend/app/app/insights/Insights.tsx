"use client";

import { useEffect, useState } from "react";
import { BrandBar } from "@/components/additions/BrandBar";
import { Bars, Metric, duration, pct } from "@/components/additions/Metrics";
import { EmptyState, ErrorState, LoadingState, NeedsBackend, SampleNotice } from "@/components/additions/States";
import { Panel, Panels, StageHead } from "@/components/app/Stage";
import { SAMPLE_RISK, brandRisk, type BrandRisk, type Maybe } from "@/lib/additions/analytics";
import { useBrands } from "@/lib/additions/brands";

type Load = { state: "loading" } | { state: "ok"; result: Maybe<BrandRisk> } | { state: "error"; error: unknown };

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

  if (brands.state === "loading") return (<><StageHead title="Insights" /><LoadingState /></>);
  if (brands.state === "error") return (<><StageHead title="Insights" /><ErrorState message={brands.message} onRetry={refresh} /></>);
  if (brands.state === "none") return (<><StageHead title="Insights" /><EmptyState title="No brand yet">Ask your admin to create one.</EmptyState></>);

  const real = load.state === "ok" && load.result.available ? load.result.data : null;

  return (
    <>
      <StageHead title="Insights" />
      <BrandBar brand={brands.brand} brands={brands.brands} fallback={brands.fallback} onChoose={choose} />

      {load.state === "loading" && <LoadingState label="Loading insights…" />}
      {load.state === "error" && <ErrorState error={load.error} onRetry={() => setTick((t) => t + 1)} />}

      {real && <RiskPanels data={real} n="01" />}

      {load.state === "ok" && !load.result.available && (
        <>
          <Panels cols="wide">
            <Panel n="01" label="Your numbers" title="Not available yet">
              <NeedsBackend>
                <code className="add-mono">GET /api/analytics/brand-risk</code>. The server doesn’t provide insight numbers yet, so none are
                shown for {brands.brand.name}. Nothing below is about your brand.
              </NeedsBackend>
            </Panel>
          </Panels>
          <div className="add-stack" style={{ marginTop: 22 }}>
            <SampleNotice>The panels below are made-up numbers that show what this page will look like. They are not your results.</SampleNotice>
            <RiskPanels data={SAMPLE_RISK} n="02" sample />
          </div>
        </>
      )}
    </>
  );
}

function RiskPanels({ data, n, sample = false }: { data: BrandRisk; n: string; sample?: boolean }) {
  const max = Math.max(1, ...data.top_categories.map((c) => c.count));
  const tag = sample ? " (sample)" : "";
  return (
    <Panels cols="2">
      <Panel n={n} label={`Top issues${tag}`} title="What gets flagged most">
        {data.top_categories.length ? (
          <Bars items={data.top_categories.map((c) => ({ label: c.category, value: c.count, max }))} format={(v) => String(v)} />
        ) : (
          <EmptyState title="No flagged issues yet" />
        )}
        <p className="add-note add-muted">Based on {data.sample_size} review{data.sample_size === 1 ? "" : "s"}.</p>
      </Panel>
      <Panel n={String(Number(n) + 1).padStart(2, "0")} label={`Speed${tag}`} title="How reviews move">
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
