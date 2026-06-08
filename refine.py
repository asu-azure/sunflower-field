#!/usr/bin/env python3
"""
Refine doujinshi translations using the Claude API.

Usage:
    python refine.py --dry-run --sheet manga
    python refine.py --sheet manga --output output.xlsx --limit 50
    python refine.py --sheet both --output master_translation_REFINED.xlsx
    python refine.py --sheet both --model claude-opus-4-8 --output output.xlsx
"""

import argparse
import json
import os
import signal
import sys
from pathlib import Path

from dotenv import load_dotenv
from tqdm import tqdm
import anthropic

from src.reader import load_manga_sheet, load_novel_sheet
from src.refiner import refine_batch
from src.writer import write_output

load_dotenv()

DEFAULT_INPUT = "master_translation.xlsx"
DEFAULT_OUTPUT = "master_translation_REFINED.xlsx"
DEFAULT_MODEL = "claude-sonnet-4-6"
BATCH_SIZE = 15
CONTEXT_WINDOW = 3

_interrupted = False


def _handle_sigint(sig, frame):
    global _interrupted
    _interrupted = True
    print("\n\nInterrupted — saving progress before exit...")


def _progress_path(sheet: str) -> Path:
    return Path(f".progress_{sheet}.json")


def _load_progress(sheet: str) -> dict[int, dict]:
    p = _progress_path(sheet)
    if p.exists():
        with open(p) as f:
            raw = json.load(f)
        return {int(k): v for k, v in raw.items()}
    return {}


def _save_progress(sheet: str, results: dict[int, dict]) -> None:
    with open(_progress_path(sheet), "w", encoding="utf-8") as f:
        json.dump({str(k): v for k, v in results.items()}, f, ensure_ascii=False, indent=2)


def process_sheet(
    rows: list[dict],
    sheet_type: str,
    client: anthropic.Anthropic,
    model: str,
    dry_run: bool,
    limit: int | None,
) -> dict[int, dict]:
    global _interrupted

    if limit:
        rows = rows[:limit]

    results = _load_progress(sheet_type)
    already_done = set(results.keys())
    pending_indices = [i for i in range(0, len(rows), BATCH_SIZE) if rows[i]["row_idx"] not in already_done]

    if not pending_indices:
        print(f"  All {len(rows)} rows already refined (cached). Delete .progress_{sheet_type}.json to re-run.")
        return results

    if dry_run:
        # Just do the first batch and print
        sample_batch_start = pending_indices[0]
        sample = refine_batch(rows, sample_batch_start, min(BATCH_SIZE, 5), sheet_type, client, model, CONTEXT_WINDOW)
        batch = rows[sample_batch_start : sample_batch_start + len(sample)]
        print(f"\n--- DRY RUN: {sheet_type} sheet (first {len(sample)} lines) ---")
        for orig, refined in zip(batch, sample):
            speaker = orig.get("speaker", "")
            label = f"[{speaker}] " if speaker else ""
            print(f"\n{label}")
            print(f"  TH orig:     {orig['th']}")
            print(f"  TH refined:  {refined['th']}")
            print(f"  EN orig:     {orig['en']}")
            print(f"  EN refined:  {refined['en']}")
            print(f"  JP orig:     {orig['jp']}")
            print(f"  JP refined:  {refined['jp']}")
        return {}

    desc = f"Refining {sheet_type}"
    with tqdm(total=len(pending_indices), desc=desc, unit="batch") as pbar:
        for batch_start in pending_indices:
            if _interrupted:
                break

            try:
                refined_list = refine_batch(rows, batch_start, BATCH_SIZE, sheet_type, client, model, CONTEXT_WINDOW)
            except Exception as e:
                print(f"\nError at batch {batch_start}: {e}", file=sys.stderr)
                _save_progress(sheet_type, results)
                raise

            batch = rows[batch_start : batch_start + BATCH_SIZE]
            for row, refined in zip(batch, refined_list):
                results[row["row_idx"]] = refined

            _save_progress(sheet_type, results)
            pbar.update(1)

    return results


def main():
    parser = argparse.ArgumentParser(description="Refine doujinshi translations with Claude API")
    parser.add_argument("--input", default=DEFAULT_INPUT, help="Input xlsx file")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Output xlsx file")
    parser.add_argument("--sheet", choices=["manga", "novel", "both"], default="both")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Claude model to use")
    parser.add_argument("--limit", type=int, default=None, help="Process only first N content rows (for testing)")
    parser.add_argument("--dry-run", action="store_true", help="Print sample refinements without writing output")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY not set. Copy .env.example to .env and add your key.", file=sys.stderr)
        sys.exit(1)

    if not Path(args.input).exists():
        print(f"Error: input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    signal.signal(signal.SIGINT, _handle_sigint)

    manga_results: dict[int, dict] = {}
    novel_results: dict[int, dict] = {}

    if args.sheet in ("manga", "both"):
        print(f"Loading manga sheet from {args.input}...")
        manga_rows = load_manga_sheet(args.input)
        print(f"  {len(manga_rows)} content rows to process")
        manga_results = process_sheet(manga_rows, "manga", client, args.model, args.dry_run, args.limit)

    if args.sheet in ("novel", "both") and not _interrupted:
        print(f"Loading novel sheet from {args.input}...")
        novel_rows = load_novel_sheet(args.input)
        print(f"  {len(novel_rows)} content rows to process")
        novel_results = process_sheet(novel_rows, "novel", client, args.model, args.dry_run, args.limit)

    if args.dry_run:
        print("\nDry run complete — no file written.")
        return

    if not manga_results and not novel_results:
        print("Nothing to write.")
        return

    print(f"\nWriting output to {args.output}...")
    write_output(args.input, manga_results, novel_results, args.output)
    print(f"Done! Refined file saved to: {args.output}")

    if _interrupted:
        print("(Run again to continue from where it stopped — progress is saved.)")


if __name__ == "__main__":
    main()
