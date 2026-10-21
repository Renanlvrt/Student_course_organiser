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
    f.add_argument("--runner", default="agy", choices=["claude", "agy"])
    f.add_argument("--model", default="sonnet")
    f.add_argument("--limit", type=int, help="stop after this many model calls")
    n = sub.add_parser("mapnotes", help="Step 1b: assign every page of module-wide notes to a lecture")
    n.add_argument("module")
    lec = sub.add_parser("lecture", help="Steps 2, 3, 3b for one lecture")
    lec.add_argument("module")
    lec.add_argument("part")
    lec.add_argument("number", type=int)
    lec.add_argument("--steps", default="capture,audit,registry,teaching,exercises,visuals,videos")
    lec.add_argument("--runner", default="auto", choices=["auto", "claude", "agy"],
                     help="auto: Claude for visuals, Antigravity for everything else")
    st = sub.add_parser("site", help="Build Website/<Part>/ from the pipeline output")
    st.add_argument("module")
    st.add_argument("part")
    ck = sub.add_parser("check", help="Coverage check: is every concept fully built?")
    ck.add_argument("module")
    ck.add_argument("part")
    pb = sub.add_parser("publish", help="Push the built sites to the module's GitHub repo + Pages (phone access)")
    pb.add_argument("module")
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
    elif args.cmd == "mapnotes":
        from .lecture import map_notes
        map_notes(cfg, module)
    elif args.cmd == "lecture":
        from .lecture import run_lecture
        run_lecture(cfg, module, args.part, args.number, args.steps.split(","), args.runner)
    elif args.cmd == "site":
        from .site import build_site
        build_site(cfg, module, args.part)
    elif args.cmd == "publish":
        from .publish import publish
        publish(cfg, module)
    elif args.cmd == "check":
        from .check import check_part
        sys.exit(1 if check_part(cfg, module, args.part) else 0)


if __name__ == "__main__":
    main()
