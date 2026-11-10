# One annotated step: what was sent, what came back, what our code did

Source: `logs/run_02.jsonl` (chat calls 18–19 and the `step` events 17–19). The submitted run is run_03, which passed
25/25 on the first write; run_02 is in the submission too and shows the loop *recovering from a failed check*,
which is the more instructive step. The diagram of the whole loop is in [diagram.png](diagram.png).

## Context: steps 16 and 17

- **Step 16** – the model sent `{"action": "write_site", "args": {}}` without the HTML block.
  Our parser (`parse_response`) raised a `ProtocolError`; the observation was
  `ERROR: write_site needs the complete page in a ```html code block directly after the JSON.` (counts as a step).
- **Step 17** – the model sent the full page. `_write_site` embedded the images and ran `check_site(mode="full")`:
  `[FAIL] theme mechanism: the theme is not switched the way the style guide requires (check both CSS and JavaScript)` – **24/25**.

## Step 18 – annotated

**1. What was sent to the model** (chat call 18, 36 messages, **12,404 prompt tokens**, of which 7,978 came from the gateway's prompt cache)

```
[system]    protocol, the 4 actions, working rules            (no style guide text)
[user]      task: build the team website ...                   (step budget 25)
[assistant] {"thought": ..., "action": "read_profiles", ...}
[user]      Observation: === krish.md === ...
   ... 14 searches and their observations ...
[assistant] {"thought": "I'm creating the complete standalone page ...", "action": "write_site", "args": {}}
            ```html  <!doctype html> ... (the page, ~4.9K tokens) ```
[user]      Observation:
            Saved index.html (136 KB). Checker report:
            [FAIL] theme mechanism: the theme is not switched the way the style guide requires (check both CSS and JavaScript)
            24/25 checks passed.

            (Step 17/25 used, 8 left.)
```

**2. What came back** (119 output tokens, 58 of them hidden reasoning)

```json
{"thought": "The checker flagged theme switching, so I'll recheck the guide's exact theme mechanism before correcting it.",
 "action": "search_style_guide",
 "args": {"query": "What exact root data-theme attribute selectors and JavaScript attribute-changing method are required for theme switching?"}}
```

**3. What our code did**

| step | code | result |
|---|---|---|
| parse | `parse_response()`: decode the first `{...}`, action is known, `query` is a non-empty string, no extra args | valid action |
| repeat check | `_execute()`: same action + args as an earlier step? | no |
| search | `index.search(query, k=4)`: embed the query with the qwen3 instruction prefix, cosine similarity against the 66 cached chunk vectors | top 4 chunks |
| budget | `format_results(chunks, max_tokens=1000)`: add best-first, skip a chunk that would not fit | about 440 tokens |
| log | `log_event({"event": "step", "step": 18, ...})` | written to `logs/run_02.jsonl` |
| observation | append `Observation: ...` + `(Step 18/25 used, 7 left.)` as a user message | |

The observation started with:

```
[SG-20] Theme switching mechanics | Status: ACTIVE
The theme is controlled by one attribute on the root element.
- The <html> element MUST carry the attribute data-theme with the value light or dark.
- JavaScript switches the theme by changing this attribute, not by toggling classes on the body.
- The CSS MUST define the colors for each theme with attribute selectors ...
---
[SG-22] Theme toggle control | Status: ACTIVE ...
```

## Step 19 – the result

The model rewrote the page ("I'll make theme changes explicitly with `setAttribute` on `<html>`") → **25/25 checks passed**.
Before sending the next request, `_compact_old_pages()` replaced the step-17 page in the history by
`[older version omitted, N tokens]`: chat call 20 sent 12,993 prompt tokens, only 70 more than call 19 although a
4.4K-token page had just been added.

**Why this matters:** nobody told the model the answer. The checker only said "theme mechanism"; the model decided
what to look up, our code retrieved the rule (with its source and status), and the fix followed. In a fixed pipeline
the search queries and the number of writes would be hard-coded.
