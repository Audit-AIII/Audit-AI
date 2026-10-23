// GET /api/brands is part of the onboarding contract but may not be merged on the backend yet.
// Asks the real backend first; only if it answers 404 is the list built from live data
// (the given brand, approved_source_count counted from its real sources, with the caller's token).
// Once Member 3's route lands this does nothing.
export async function shimBrandsList(target, { api = "http://localhost:8000", web = "http://localhost:3000", brandId, name }) {
  const stats = { real: 0, shimmed: 0 };
  await target.route(`${api}/api/brands`, async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    const real = await route.fetch();
    if (real.status() !== 404) {
      stats.real++;
      return route.fulfill({ response: real });
    }
    stats.shimmed++;
    const auth = route.request().headers().authorization;
    const res = await fetch(`${api}/api/brands/${brandId}/sources`, { headers: { Authorization: auth } });
    // Same auth outcome as the real route would give (e.g. 401 for an expired token).
    if (!res.ok)
      return route.fulfill({ status: res.status, contentType: "application/json", headers: { "Access-Control-Allow-Origin": web }, body: await res.text() });
    const sources = await res.json();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "Access-Control-Allow-Origin": web },
      body: JSON.stringify([
        { id: brandId, name, description: null, approved_source_count: sources.filter((s) => s.status === "approved").length, created_at: "2026-10-23T00:00:00Z" },
      ]),
    });
  });
  return stats;
}
