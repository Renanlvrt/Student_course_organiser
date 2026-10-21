"""python -m study <command> <Module> ...   (see study/prompts/README.md for the steps)"""
import argparse
import sys

from organiser.config import load_config


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m study")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("convert", help="Step 0: PDFs -> lectures_markdown (local, free)")
    c.add_argument("module")
    c.add_argument("--force", action="store_true", help="reconvert unchanged PDFs too")
    f = sub.add_parser("fix", help="Step 1: rewrite flagged pages from page images (vision model)")
    f.add_argument("module")
    f.add_argument("--runner", default="claude", choices=["claude", "agy"])
    f.add_argument("--model", default="sonnet")
    f.add_argument("--limit", type=int, help="stop after this many model calls")
    args = ap.parse_args(argv)

    cfg = load_config()
    module = cfg.module(args.module)
    if not module:
        sys.exit(f"Unknown module {args.module!r}. Known: {', '.join(m.key for m in cfg.modules)}")
    if args.cmd == "convert":
        from .convert import convert_module
        convert_module(cfg, module, force=args.force)
    elif args.cmd == "fix":
        from .fix_pages import fix_module
        print(f"{fix_module(cfg, module, args.runner, args.model, args.limit)} model call(s)")


if __name__ == "__main__":
    main()
