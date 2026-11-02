import argparse
import json
import sys

from .pipeline import Copilot, build_index


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="research_copilot", description="RAG over my project docs with a local open-source LLM")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build", help="Index the sources in copilot_sources.json")
    ask = sub.add_parser("ask", help="Ask a question")
    ask.add_argument("question")
    ev = sub.add_parser("eval", help="Run the evaluation set")
    ev.add_argument("--retrieval-only", action="store_true", help="Skip answer generation (fast)")
    args = parser.parse_args()

    if args.command == "build":
        build_index()
    elif args.command == "ask":
        out = Copilot().ask(args.question)
        print(out["answer"])
        g = out["grounding"]
        if not out["abstained"]:
            print(f"\nGrounding check: {g['supported']} of {g['sentences']} sentences matched a retrieved passage.")
            for sentence in g["unsupported"]:
                print(f"  Not found in the sources: {sentence}")
        print()
        for i, s in enumerate(out["sources"], start=1):
            print(f"[{i}] {s['source']} · {s['path']}" + (f" · {s['heading']}" if s["heading"] else ""))
        print(f"\n{out['model']} · {out['generation_seconds']}s · {out['tokens_per_second']} tok/s")
    else:
        from .evaluate import run
        report = run(answer=not args.retrieval_only)
        print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
