# Setup (2 minutes)

1. Create a folder for the project, e.g. `audit-ai`, and open it in VS Code.
2. Unzip this kit into it so you have:
   ```
   audit-ai/
   ├─ CLAUDE.md                      ← Claude Code loads this automatically
   ├─ design/
   │  ├─ DESIGN.md
   │  ├─ tokens.css
   │  └─ reference/screenshots/*.jpg
   └─ prompts/
      ├─ 01-landing-and-hero.md      ← USE THIS NOW
      └─ 02-app-later.md             ← use after the landing page (review workspace)
   ```
3. VS Code terminal (Ctrl+`) → `git init` → run `claude`.
4. Paste: `Read prompts/01-landing-and-hero.md and execute it.`
5. When it stops after the hero, review its screenshots, then reply "continue".

Notes
- Keep `design/` and `prompts/` in the repo; commit them.
- Put the Next.js app in `./frontend` (Claude Code will create it).
- Hackathon rule: start writing product code inside the official build window and disclose AI-assisted code.
