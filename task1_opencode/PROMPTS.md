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
