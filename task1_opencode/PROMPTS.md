# OpenCode prompts for the team website

Start OpenCode in `task1_opencode/` (so it reads `AGENTS.md`). Send one prompt at a time.
After each session: `/export` → `conversation/session_XX.md`, and write down prompts, tokens and cost below.

## Session 1 – build the site

**Prompt 1 (build)**
```
Read AGENTS.md and everything in content/. Then build the team website exactly as AGENTS.md describes: write site/index.src.html with image placeholders, run the embed command and the checker, and fix any failures.
```

**Prompt 2 (fix what you see)** – open `site/index.html` in your browser first, then describe the problems:
```
I opened the site. Please fix: <what looks wrong, e.g. "cards overlap on phone width", "night mode text is unreadable">. Edit only site/index.src.html, then embed and check again.
```

**Prompt 3 (make it fun)**
```
Make the site more fun and creative without breaking the checks: <your idea, e.g. "a random hot take button", "a funny loading message", "confetti when switching to night mode">. Then embed and check again.
```

## Later sessions (any team member)

Use `/new`, then:
```
Read AGENTS.md. Change site/index.src.html: <your change>. Then embed and check again.
```

## If the agent goes wrong (steer it back)
- Writes base64 or reads an image: `Stop. Never write image data. Follow the Images section of AGENTS.md.`
- Opens site/index.html: `Don't read site/index.html. Edit site/index.src.html instead.`
- Checker fails: `Run the checker again, read the failure message and fix only that.`

Note these moments down – the video needs one example of the agent going wrong and how you steered it back.

## Session log

| Session | Member | Prompts | Tokens (in / out / reasoning / cache) | Cost (USD) | Notes |
|---|---|---|---|---|---|
| 01 | Krish | 1 (12 model calls) | 18,970 / 6,339 / 689 / 150,718 | 0.0069 | Built the site. Agent hit a Windows encoding error in embed_images.py and fixed it itself (PYTHONIOENCODING=utf-8). 7/7 checks. |
| 02 | Krish | 1 (9 model calls) | 18,501 / 2,598 / 1,305 / 121,022 | 0.0050 | New tagline (3 options, picked 1) + hover effects + reduced motion. Same encoding error again: the agent has no memory between sessions. 7/7 checks. |
| 03 | Krish | 1 (10 model calls) | 19,187 / 1,877 / 422 / 141,404 | 0.0045 | New avatars (PNG, new file names) + new study background. Agent updated only the 5 placeholders and study lines. `ls` failed (Windows cmd), it used its glob tool instead; the encoding error came a third time and it fixed it again. 7/7 checks. |

## Screenshots of the site (for the video)

Taken automatically with headless Edge from `site/index.html` (no site code was changed; night mode by clicking the toggle):

| | day | night |
|---|---|---|
| desktop (1366 px) | `screenshots/site_desktop_day.png` | `screenshots/site_desktop_night.png` |
| mobile (390 px) | `screenshots/site_mobile_day.png` | `screenshots/site_mobile_night.png` |

The agent going wrong: `screenshots/image.png` shows the UnicodeEncodeError of the embed command in session 01; the
agent fixed it itself with `PYTHONIOENCODING=utf-8`, and made the same mistake again in sessions 02 and 03.
