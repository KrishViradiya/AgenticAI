# Video script – Part 1 (Intro) + Part 2 (Task 1)

Not part of the submission ZIP. Target: Intro ~0:30, Task 1 ~1:30.
All numbers below come from `task1_opencode/conversation/session_0X.json` (reproducible).

---

## Part 1 – Intro (~0:30) · Speaker: ______

**On screen:** site hero (desktop, day mode).

> Hi, we are "The Prompt Engineers Who Can't Center a Div": Nirav, Krish, Harsh, Keval and Nevil.
> In Lab 1 we went from using a coding agent, to building our own, to looking under the hood at RAG and tool calling.
> This is the team website that OpenCode built for us in Task 1, without us writing a single line of HTML, CSS or JavaScript.

---

## Part 2 – Task 1: Using an agent (~1:30) · Speaker: ______

### 1. Screenshots (~20 s)
**On screen:** 4 screenshots in a 2×2 grid: desktop day, desktop night, mobile day, mobile night.

> One standalone file: HTML, CSS and JavaScript only, nothing loaded from the internet, all five photos embedded.
> It's responsive – on the phone the cards stack in one column – and it has a day/night toggle.
> check_site.py passes all 7 checks.

### 2. How we steered the agent (~20 s)
**On screen:** AGENTS.md (Images section).

> We didn't put the rules into every prompt. We wrote them once in AGENTS.md, which OpenCode reads automatically.
> The most important rule: never write image data. A base64 photo is hundreds of thousands of characters –
> the model would burn tokens and get it wrong. So the agent writes `{{image:krish.jpg}}` placeholders into
> index.src.html, and runs embed_images.py, which inserts the images. The agent never reads the 138 KB final file.

### 3. Session statistics (~25 s)
**On screen:** this table + the "context per call" line chart.

| Session | Prompts | Model calls | Input | Output | Reasoning | Cache read | Cost |
|---|---|---|---|---|---|---|---|
| 01 – build the site | 1 | 12 | 18,970 | 6,339 | 689 | 150,718 | $0.0069 |
| 02 – tagline + hover effects | 1 | 9 | 18,501 | 2,598 | 1,305 | 121,022 | $0.0050 |
| **Total** | **2** | **21** | | | | | **≈ $0.012** |

Context sent per model call, session 01:
8.6K → 8.8K → 9.7K → 12.4K → … → 18.0K → 18.9K tokens

> We needed only 2 prompts, but behind them were 21 model calls: the agent reads files, writes, runs commands, reads the output.
> Every call re-sends the whole conversation, so the context grows from 8.6K to 19K tokens within one session.
> That's why about 85% of all tokens were cache reads – cheap, but it shows why we start a new session (/new) for each change.
> The whole website cost about one cent.

### 4. What OpenCode did on its own (~10 s)
> On its own, OpenCode listed and read our content files, made a todo list, wrote the file with a patch and ran shell commands.
> Every file edit and every command needed our approval, because opencode.json is set to "ask".
> The model only proposes a tool call; OpenCode the program executes it and asks us first.

### 5. Where it went wrong, and how it was fixed (~15 s)
**On screen:** screenshots/image.png (the UnicodeEncodeError).

> The first embed command crashed: a UnicodeEncodeError, because the Windows console can't print the "→" character.
> The agent read the traceback and reran the command with PYTHONIOENCODING=utf-8 – that worked.
> But in session 2 it made exactly the same mistake again: the agent has no memory between sessions.
> The fix would be one line in AGENTS.md – the place where knowledge survives between sessions.

> *(If you add a session 3 where you steer the agent yourself – e.g. "Use option 2 for the tagline" or
> "the tilt is too strong" – use that example here instead, or in addition.)*

---

## Checklist before recording
- [ ] Real photos for every member (currently all five files are the same picture), then ask OpenCode to re-embed
- [ ] Each member has checked/rewritten their own profile
- [ ] Every teammate has their own `screenshots/hello_<firstname>.png`
- [ ] 4 site screenshots: desktop/mobile × day/night
- [ ] Every new OpenCode session exported to `conversation/` and added to the table in PROMPTS.md
- [ ] AI usage statement (wrap-up): Claude Code helped with setup, AGENTS.md, prompt drafts and profile drafts; all site code came from OpenCode
