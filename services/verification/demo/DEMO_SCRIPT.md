# Demo script, pre-demo checks, fallback plan, and fallback video

A five-minute demo of the real application. Every result shown is real application output. It's
either a live model run, or the seeded demo data that the real engine produced with the **offline
scripted provider**, which the UI labels **"Checked by fallback · scripted/demo-v1"** and whose
account is labelled **"[SEEDED]"**. Never present a scripted result as a live model's answer.

Rehearsed on 2026-10-24 with `demo/demo-check.mjs`: every scene below passed in the real UI.

## 1. Pre-demo checks (15 minutes before)

1. **Database up:** `cd services/api && docker compose up -d`.
2. **Fresh demo data:** `python scripts/seed.py --reset`. It prints the demo logins
   (`asha@seed.inkloom.demo`) and the demo password.
3. **Backend up:** `python -m uvicorn inkloom_api.main:app --port 8000`. Check that
   `http://localhost:8000/health` returns `{"status":"ok"}`.
4. **Frontend up:** `cd audit-ai-final/frontend && npm run build && npm run start`, built with
   `NEXT_PUBLIC_API_URL` pointing at the backend.
5. **Rehearsal:** from `services/verification`, run
   `AUDIT_PASSWORD=<demo password> node demo/demo-check.mjs <screenshot dir>`. All lines must say
   PASS.
6. **Live provider check (optional):** submit one short draft. If its findings say "engine error",
   or "Checked by …" shows no real model, the live provider is unavailable: use the fallback path
   (§3). Known today: the configured free model is refused by the privacy setting
   (`data_collection: deny`). See `HANDOFF_STEPS_6_8.md` and `EVAL.md`, "Live evaluation status".
7. **Rules demo:** `.venv/Scripts/python demo/rules_demo.py` prints nine findings.

## 2. Script (about 5 minutes)

| Time | Show | Say |
|---|---|---|
| 0:00 | Landing page, then sign in as `asha@seed.inkloom.demo` | "Audit AI checks content before it's published, against the brand's own approved documents. A person makes every final call." |
| 0:30 | **Sources:** the Lumen Audio fact sheet (approved, versioned) | "Only approved documents are evidence. Nothing else is searched." |
| 1:00 | **Review "[SEEDED] Lumen Pods launch post"**: click "Lumen Pods offer up to 24 hours…" | **CONTRADICTED.** The panel shows the approved quote "up to 12 hours of playback per charge" and the suggestion "Lumen Pods offer up to 12 hours of playback per charge." "The fix uses only words from the quote and was re-checked before it was offered." |
| 1:45 | Same review: "Every pair comes with a 2-year warranty." | **SUPPORTED** ("Matches") with the quote "Warranty: 2 years." |
| 2:15 | **Review "[SEEDED] Lumen Pods summer ad"**: "best-selling earbuds in Europe" | **NOT_ENOUGH_EVIDENCE**, shown as "Not proven yet", never "false": no approved document mentions sales rankings. |
| 2:45 | Point at "Checked by fallback · scripted/demo-v1" | "This demo data was produced by the real engine with a scripted stand-in for the model, labelled so it can't be mistaken for a live model." |
| 3:00 | **Choose what to do** (Decide): approve / send back / reject | "The tool proposes; the owner decides. Every decision is recorded with who, when and which version." |
| 3:30 | **Queue**, and the "source changed" review | "Source Watch: replacing an approved document sends dependent approvals back for review." |
| 4:00 | Terminal: `demo/rules_demo.py` | "Terminology and accessibility rules are deterministic: no model. They're built and tested in the engine, but not yet shown in the app." Point at `not_checkable`: "no data is never reported as passed." |
| 4:30 | Limitations (§4) | Be explicit. |

## 3. Fallback plan if the live provider fails

- **During the live part:** say so plainly ("the model provider is unavailable right now, so here
  is the same flow on seeded data"), then switch to the seeded reviews in §2. They need no network.
- **If the app itself fails:** play the fallback video (§5).
- **Never** edit a result, replay a scripted result as live, or relax `data_collection: deny` to
  make a provider answer.

## 4. Limitations to state

- **No live model accuracy has been established.** The only live run (2026-10-24) answered 30 of 80
  records before rate limits stopped it, and it found 3 wrong approvals; one is fixed, two are open
  guard limitations (EVAL.md).
- **The deterministic guard isn't a semantic check.** A real quote with the right figure for the
  wrong property, or half of a compound claim, can still pass.
- **Not wired into the app yet:** terminology and accessibility rules, the separate "safer wording"
  field, the conflicting-sources status, and server-side Intent-lock (HANDOFF_STEPS_6_8.md).
- **Not built:** comments on findings and per-finding Dismiss.
- **The app isn't deployed.**

## 5. Recording the fallback video

1. **Prepare:** run the pre-demo checks (§1) first. Screen 1920×1080, browser zoom 100%,
   notifications off, only the app and one terminal open.
2. **Record:** Windows Game Bar (`Win+Alt+R`) or OBS Studio, at 1080p and 30 fps, with microphone
   narration following §2. Keep the "scripted/demo-v1" and "[SEEDED]" labels visible on screen.
3. **Length and file:** about 5 minutes. Save as `inkloom-demo-fallback-<date>.mp4` outside the
   repository; don't commit videos.
4. **Title card:** "Recorded on <date> with seeded demo data produced by the offline scripted
   provider; not a live model run."
5. **Check:** watch it once end to end, and confirm no password, API key or personal data is
   visible.

No video has been recorded yet. This is the plan; recording needs a person at the machine.
