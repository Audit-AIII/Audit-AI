# Round 3 demo script

A 5-minute walkthrough following one draft from check to published. Set up before the audience arrives; the invitations take a couple of minutes.

## Before you start

1. Start Postgres, then from `services/api` run `.venv/Scripts/python scripts/seed.py --reset` and start the API.
2. From `audit-ai-final/frontend`, run `npm run dev`.
3. Sign in at `http://localhost:3000/login` as `asha@seed.inkloom.demo`. The password is `DEMO_PASSWORD` in `scripts/seed.py`.
4. Build the team. Use a separate browser profile for each person, because a browser holds one session:
   1. As Asha, open **Team** and invite a writer, a reviewer and an approver, using made-up addresses.
   2. Copy each link into a new profile, choose **Create an account** with that exact email, then **Accept invitation**.
5. As the writer, check one draft so it's waiting at step 4. Keep the writer, reviewer and approver windows open.

**Which steps need a provider key:**

| Step | Without a key | With a key |
|---|---|---|
| 1 and 2, seeded findings | Works, labelled as a scripted demo | Works |
| A new draft | Shows a clearly labelled placeholder, because nothing is really checked | Real AI findings |
| 3 to 5, workflow | Works. Approving needs ticking "I understand no real check ran" | Works |
| 6, Scorecard | Krish's published benchmark, and the no-provider message if you press Run | Same, but pressing Run replaces it for that workspace with a smaller verifier-only run, so don't press it in the demo |

**No key is set up today**, so new drafts show the placeholder. To use real AI, put a key in `services/api/.env` (`services/api/AI_PROVIDER_KEYS.md` lists the options), restart the API, and run `node qa/live-ai-check.mjs` from `audit-ai-final/frontend`. Practise with it first, because this script hasn't been run with a live provider yet.

## The script

### 1. The result at a glance (45 seconds)

Open a seeded draft with a contradicted claim from **Queue**.

Say: "This is what a brand manager sees after a check. These counts come from the server. Every problem is marked in the draft itself."

### 2. Why it was flagged (60 seconds)

Select the contradicted finding.

Point at each part: the marked words, the verdict and severity, the quote from the approved document with its version, the explanation, and the suggested correction.

Then select a "Not proven yet" finding.

Say: "Here there's no proof either way, so we don't show a quote or call it false. A person decides. Nothing is ever changed automatically."

Open **Brand rule checks** at the bottom if the audience asks about terminology or accessibility.

### 3. The writer can't approve their own work (45 seconds)

In the writer's window, open **Decide** on their draft.

Say: "This draft is theirs, so Approve isn't offered. And hiding the button isn't the protection: the server refuses it too." Point at the status, risk and "Why this needs review".

Click **Send for review**. The status changes to In review, from the server's answer.

### 4. Reviewer, then approver (60 seconds)

- **As Asha,** assign the reviewer on Decide.
- **As the reviewer,** add a note and click **Mark as reviewed**.
- **As the approver,** click **Approve**, then **Mark as published**.

Say: "Each person sees only what their role allows on this draft right now, and it changes as the draft moves."

### 5. The record (30 seconds)

Open **Record**, and scroll to **History**.

Say: "Every step, who did it, and the reviewer's note. This log can't be edited." As Asha, open **Workspace > Audit log** to show who joined and when.

### 6. Trust Scorecard (60 seconds)

Open **Workspace > Scorecard**.

It shows the published benchmark from Krish's live runs. Point at where the answers came from, then the metrics, the dataset and the limitations. Quote the held-out numbers from `docs/round3/results/FINAL_RESULTS.md`, not the combined ones.

Say: "This is a recorded benchmark, and it says so. The labels were written by AI and no person has reviewed them yet, so we show these numbers with their limits."

## If you're asked

- **Does it check tone?** Not yet. It has brand rules for capitals and emoji, and the page is ready to show brand voice findings, but only ones that cite a guideline passage. No such checker exists yet, so don't demo this as working.
- **Does it send invitation emails?** No. The owner shares a one-time link.
- **Does it publish for you?** No. "Mark as published" records that this exact version went out.

## If something goes wrong

- **A new draft shows "Placeholder":** the API has no provider key. Use the seeded drafts for steps 1 and 2.
- **"Too many sign-ups":** the API allows 5 per 10 minutes from one address by default. Set the team up well ahead, or start the API with `RATE_LIMIT_REGISTRATIONS_PER_IP` raised.
- **An invite says it was sent to a different email:** sign up with exactly the address you invited.
