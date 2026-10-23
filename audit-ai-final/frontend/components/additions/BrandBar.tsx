"use client";

import type { BrandChoice } from "@/lib/additions/brands";

/** Brand name line under the page title. A picker only when there is more than one brand. */
export function BrandBar({
  brand,
  brands,
  fallback,
  onChoose,
}: {
  brand: BrandChoice;
  brands: BrandChoice[];
  fallback: boolean;
  onChoose: (id: string) => void;
}) {
  return (
    <div className="add-brandline">
      <span className="t-caption add-muted">Brand</span>
      {brands.length > 1 ? (
        <select className="add-select" aria-label="Brand" value={brand.id} onChange={(e) => onChoose(e.target.value)}>
          {brands.map((b) => (
            <option key={b.id} value={b.id}>
              {b.name}
            </option>
          ))}
        </select>
      ) : (
        <span className="add-brandline__name">{brand.name}</span>
      )}
      {fallback && <span className="add-note add-muted">Brand list isn’t available from the server yet, so this uses the brand you last opened.</span>}
    </div>
  );
}
