# Team website – instructions for the agent

## Goal
Build ONE standalone file `site/index.html` that introduces our team.

## Content (read these, don't invent facts)
- `content/<name>.md` – one profile per team member (ignore files starting with `_template`).
- `content/_team.md` – team name and our shared view on AI and the future of software engineering.
- `content/images/` – one picture per member. Run `ls content/images` to get the exact file names.

## Requirements
- HTML + CSS + JavaScript only, all inline. Nothing loaded from the internet (no CDNs, web fonts, external images).
- Introduce the team and every member: name, study background, interests, fun fact, AI views, hot take.
- Responsive for phone and desktop (use `@media` width queries and `<meta name="viewport">`).
- Day/night mode toggle (a button + JavaScript that switches the theme).
- A section with the team's shared view on AI and the future of software engineering.
- Funny and creative, but readable.

## Images – IMPORTANT (saves tokens)
- NEVER write base64 or image data yourself. NEVER open or read image files.
- Write the page in `site/index.src.html`. For each picture use a placeholder:
  `<img src="{{image:<file name>}}" alt="Photo of <name>">`
- Generate the final page with:
  `uv run python embed_images.py site/index.src.html --images content/images --out site/index.html`
- NEVER read or edit `site/index.html` (it is huge). Always edit `site/index.src.html`, then embed again.

## Check
After every change run the embed command, then:
`uv run python check_site.py site/index.html --content content`
Fix all failures before you say you are done.

## Working style
- Keep answers short. Don't print the whole file in chat.
- Only edit files inside `site/`. Never touch `content/`, the Python scripts or `opencode.json`.
