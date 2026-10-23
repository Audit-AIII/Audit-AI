# Wiring the new pages (proposals only: none of these are applied)

The new pages are reachable by direct URL only. Each item below is a single change you could
approve on its own. Line numbers are from the commit that added this file; check them again
before applying.

| Page | URL |
|---|---|
| Guidelines | `/app/guidelines` |

## Guidelines

1. **Link from Sources (Panel 3, under "Next: check a draft").**
   `app/app/sources/BrandSources.tsx`, after line 273, add:
   ```tsx
   <a className="link" href="/app/guidelines">Manage versions and withdrawals →</a>
   ```

2. **Optional: a sixth item in the stage bar.** Not recommended: it changes the five-stage bar
   on every page. `components/app/stages.ts`, after the `sources` entry (line 3), add:
   ```ts
   { slug: "guidelines", n: "01b", label: "Guidelines", hint: "Upload, update or withdraw the documents drafts are checked against." },
   ```
