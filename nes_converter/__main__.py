import argparse
import json
import sys
from pathlib import Path

from .api import MODES, render_input
from .batch import run_batch
from .instinct import adapt
from .patch import apply_patch, make_patch
from .selection import CONTEXT_MODES, select_and_render


def main():
    parser = argparse.ArgumentParser(description="Offline source-only NES handoff; no default prompt mode")
    commands = parser.add_subparsers(dest="command", required=True)
    render = commands.add_parser("render", help="Render an input-only canonical object, never its target")
    render.add_argument("--mode", choices=MODES, required=True)
    render.add_argument("--input", type=Path, required=True)
    render.add_argument("--output", type=Path, required=True)
    native = commands.add_parser("adapt", help="Adapt one pinned Instinct source record without model rendering")
    native.add_argument("--input", type=Path, required=True)
    native.add_argument("--output", type=Path, required=True)
    unified = commands.add_parser("convert", help="Render one input using explicit structured/raw/auto context selection")
    unified.add_argument("--context-mode", choices=CONTEXT_MODES, required=True)
    unified.add_argument("--input", type=Path, required=True)
    unified.add_argument("--output", type=Path, required=True)
    batch = commands.add_parser("batch", help="Build full views from accepted/canonical records and existing memberships")
    batch.add_argument("--context-mode", choices=CONTEXT_MODES, required=True)
    batch.add_argument("--canonical", type=Path, required=True)
    batch.add_argument("--accepted", type=Path, required=True)
    for view in ("all", "provisional"):
        batch.add_argument(f"--{view}-selected", type=Path, required=True)
        batch.add_argument(f"--{view}-excluded", type=Path, required=True)
    batch.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise FileExistsError("Output already exists; use a new path")
        if args.command == "batch":
            summary = run_batch(
                canonical_path=args.canonical, accepted_path=args.accepted,
                policies={
                    "all": (args.all_selected, args.all_excluded),
                    "provisional": (args.provisional_selected, args.provisional_excluded),
                }, output=args.output, context_mode=args.context_mode,
            )
            print(json.dumps(summary, indent=2))
            return 0
        data = json.loads(args.input.read_text(encoding="utf-8"))
        if args.command == "convert":
            result = select_and_render(data, context_mode=args.context_mode)
        elif args.command == "render":
            result = render_input(data, mode=args.mode)
        else:
            canonical = adapt(data)
            path = next(iter(canonical.input_context["files"]))
            info = canonical.metadata["source_adapter"]
            start = info["region_start_line_zero_based"]
            patch = make_patch(canonical.input_context["files"], canonical.expected_result,
                               editable_regions={path: (start, start + info["region_line_count"])})
            if apply_patch(canonical.input_context["files"], patch) != canonical.expected_result:
                raise ValueError("Generated patch does not reach the independent expected result")
            result = {
                "sample_id": data["sample_id"], "input_context": canonical.input_context,
                "assistant_label": {"role": "assistant", "content": patch},
                "expected_result": canonical.expected_result, "metadata": canonical.metadata,
            }
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    except (ValueError, KeyError, TypeError, OSError, RuntimeError) as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
