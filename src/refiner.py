import json
import time
import anthropic

MANGA_SYSTEM = """\
You are a literary editor and translator working on a Thai doujinshi called
"Beyond the Door Lies a Field of Sunflowers" (เปิดประตูสู่ทุ่งทานตะวัน), Sea Sparkles Arc (บทแพลงก์ตอนเรืองแสง).

Themes: coming-of-age, domestic violence, grief, quiet longing, unconditional love.

Main characters:
- Time (ไทม์): The narrator. A deadpan, self-deprecating, introspective teen who downplays
  emotion with dry humor. His internal monologue is understated and quietly sardonic.
- Teacher, Classmates, Parents: supporting cast.

Your task — for each line marked REFINE:
1. Refine Text_TH: correct any unnatural Thai phrasing, fix grammar, preserve the author's voice.
   Keep colloquial Thai where it fits the character (e.g., Time speaks casually).
2. Refine Text_EN: natural, casual English. For manga speech bubbles, aim for ≤15 words per line.
   Fix awkward literal translations. Capture the character's voice — Time sounds wry, not dramatic.
3. Refine Text_JP: natural Japanese matching the register of the Thai (casual spoken for dialogue,
   slightly more literary for narration). Preserve any existing nuance in the draft JP.

Rules:
- Do NOT change the meaning, events, or who says what.
- Do NOT add content that isn't there.
- If a line is already good, you may return it unchanged.
- Return ONLY a valid JSON array — no explanation, no markdown.
  Format: [{"th": "...", "en": "...", "jp": "..."}, ...]
  One object per REFINE line, in the same order they appear.
"""

NOVEL_SYSTEM = """\
You are a literary editor and translator working on a Thai doujinshi novel called
"Beyond the Door Lies a Field of Sunflowers" (เปิดประตูสู่ทุ่งทานตะวัน), Sea Sparkles Arc.

Themes: coming-of-age, domestic violence, grief, quiet longing, the fragility of safe spaces.

Narrator voice — Time (ไทม์): introspective, quietly sardonic, understated. He describes
painful things with a kind of detached clarity, never melodramatic.

Your task — for each paragraph marked REFINE:
1. Refine Text_TH: correct unnatural Thai phrasing, preserve the author's literary voice.
2. Refine Text_EN: natural, gently literary English for prose narration. Fix literal translations.
   Sentences should flow — vary length for rhythm. Capture the narrator's quiet tone.
3. Refine Text_JP: natural literary Japanese (やや文語的) matching the Thai register.

Rules:
- Do NOT change meaning or events.
- Do NOT add content that isn't in the original.
- If a line is already good, return it unchanged.
- Return ONLY a valid JSON array — no explanation, no markdown.
  Format: [{"th": "...", "en": "...", "jp": "..."}, ...]
  One object per REFINE paragraph, in the same order.
"""


def _build_manga_prompt(context_before: list[dict], batch: list[dict], context_after: list[dict]) -> str:
    parts = []
    if context_before:
        parts.append("CONTEXT (do not refine):")
        for r in context_before:
            parts.append(f"  [{r['speaker']}] TH: {r['th']}")
            parts.append(f"           EN: {r['en']}")
    parts.append("")
    parts.append(">>> LINES TO REFINE:")
    for i, r in enumerate(batch):
        parts.append(f"  Line {i + 1} [{r['speaker']}]")
        parts.append(f"    TH: {r['th']}")
        parts.append(f"    EN: {r['en']}")
        parts.append(f"    JP: {r['jp']}")
    parts.append("<<< END REFINE")
    if context_after:
        parts.append("")
        parts.append("CONTEXT (do not refine):")
        for r in context_after:
            parts.append(f"  [{r['speaker']}] TH: {r['th']}")
            parts.append(f"           EN: {r['en']}")
    return "\n".join(parts)


def _build_novel_prompt(context_before: list[dict], batch: list[dict], context_after: list[dict]) -> str:
    parts = []
    if context_before:
        parts.append("CONTEXT (do not refine):")
        for r in context_before:
            parts.append(f"  Para {r['para_num']} TH: {r['th']}")
            parts.append(f"               EN: {r['en']}")
    parts.append("")
    parts.append(">>> PARAGRAPHS TO REFINE:")
    for i, r in enumerate(batch):
        parts.append(f"  Para {i + 1} (#{r['para_num']})")
        parts.append(f"    TH: {r['th']}")
        parts.append(f"    EN: {r['en']}")
        parts.append(f"    JP: {r['jp']}")
    parts.append("<<< END REFINE")
    if context_after:
        parts.append("")
        parts.append("CONTEXT (do not refine):")
        for r in context_after:
            parts.append(f"  Para {r['para_num']} TH: {r['th']}")
            parts.append(f"               EN: {r['en']}")
    return "\n".join(parts)


def _call_with_retry(client: anthropic.Anthropic, model: str, system: str, prompt: str, max_retries: int = 4) -> str:
    delay = 2
    for attempt in range(max_retries + 1):
        try:
            msg = client.messages.create(
                model=model,
                max_tokens=4096,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            return msg.content[0].text
        except anthropic.RateLimitError:
            if attempt == max_retries:
                raise
            time.sleep(delay)
            delay *= 2
        except anthropic.APIStatusError as e:
            if e.status_code >= 500 and attempt < max_retries:
                time.sleep(delay)
                delay *= 2
            else:
                raise


def _parse_json_response(text: str, expected_count: int) -> list[dict]:
    text = text.strip()
    # Strip markdown fences if Claude wraps in them
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError(f"Expected JSON array, got {type(data)}")
    if len(data) != expected_count:
        raise ValueError(f"Expected {expected_count} items, got {len(data)}")
    return data


def refine_batch(
    all_rows: list[dict],
    batch_start: int,
    batch_size: int,
    sheet_type: str,
    client: anthropic.Anthropic,
    model: str,
    context_window: int = 3,
) -> list[dict]:
    batch = all_rows[batch_start : batch_start + batch_size]
    ctx_before = all_rows[max(0, batch_start - context_window) : batch_start]
    ctx_after = all_rows[batch_start + batch_size : batch_start + batch_size + context_window]

    if sheet_type == "manga":
        system = MANGA_SYSTEM
        prompt = _build_manga_prompt(ctx_before, batch, ctx_after)
    else:
        system = NOVEL_SYSTEM
        prompt = _build_novel_prompt(ctx_before, batch, ctx_after)

    raw = _call_with_retry(client, model, system, prompt)
    return _parse_json_response(raw, len(batch))
