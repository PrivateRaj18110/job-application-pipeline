"""
Evaluation harness: retrieval hit rate and MRR against hand-labelled source documents,
plus answer checks (expected facts present, sentences grounded in a passage, abstention on out-of-scope questions).
An expected fact may list accepted alternatives separated by "|", e.g. "anthropic|claude".
"""

import json
from datetime import datetime
from typing import Dict, List

from .config import EVAL_FILE, INDEX_DIR
from .pipeline import Copilot

PUBLIC_SUMMARY = EVAL_FILE.with_name("eval_summary.json")


def _hit_rank(sources: List[Dict[str, object]], expected_paths: List[str]) -> int:
    for rank, s in enumerate(sources, start=1):
        if any(e.lower() in f"{s['source']}/{s['path']}".lower() for e in expected_paths):
            return rank
    return 0


def run(answer: bool = True, log=print) -> Dict[str, object]:
    cases = json.loads(EVAL_FILE.read_text(encoding="utf-8"))
    copilot = Copilot()
    results = []
    for case in cases:
        if answer:
            out = copilot.ask(case["question"])
            sources = out["sources"]
        else:
            out, sources = {}, copilot.retrieve(case["question"])
        rank = _hit_rank(sources, case.get("expected_sources", []))
        row = {"question": case["question"], "in_scope": case.get("in_scope", True), "hit_rank": rank}
        if answer:
            text = out["raw_answer"].lower()
            facts = case.get("expected_facts", [])
            row.update({
                "answer": out["answer"],
                "abstained": out["abstained"],
                "facts_found": sum(1 for f in facts if any(alt.lower() in text for alt in f.split("|"))),
                "facts_total": len(facts),
                "cited": bool(out["citations"]),
                "sentences": out["grounding"]["sentences"],
                "supported_sentences": out["grounding"]["supported"],
                "unsupported": out["grounding"]["unsupported"],
                "seconds": out["generation_seconds"],
            })
        results.append(row)
        log(f"[eval] rank={rank} {case['question'][:70]}")

    scoped = [r for r in results if r["in_scope"]]
    summary = {
        "evaluated_at": datetime.now().isoformat(timespec="seconds"),
        "questions": len(results),
        "hit_at_1": round(sum(1 for r in scoped if r["hit_rank"] == 1) / len(scoped), 3),
        "hit_at_5": round(sum(1 for r in scoped if r["hit_rank"] >= 1) / len(scoped), 3),
        "mrr": round(sum(1 / r["hit_rank"] for r in scoped if r["hit_rank"]) / len(scoped), 3),
    }
    if answer:
        out_scope = [r for r in results if not r["in_scope"]]
        facts_total = sum(r["facts_total"] for r in scoped) or 1
        answered = [r for r in scoped if r["sentences"]]
        summary.update({
            "fact_recall": round(sum(r["facts_found"] for r in scoped) / facts_total, 3),
            "cited_answers": round(sum(1 for r in scoped if r["cited"]) / len(scoped), 3),
            # Averaged per answer, so one long bullet list cannot dominate the score
            "supported_sentences": round(sum(r["supported_sentences"] / r["sentences"] for r in answered)
                                         / (len(answered) or 1), 3),
            "unsupported_sentences": sum(len(r["unsupported"]) for r in scoped),
            "abstained_out_of_scope": f"{sum(1 for r in out_scope if r['abstained'])}/{len(out_scope)}",
            "false_abstentions": sum(1 for r in scoped if r["abstained"]),
            "median_answer_seconds": sorted(r["seconds"] for r in results)[len(results) // 2],
        })
    report = {"summary": summary, "results": results}
    (INDEX_DIR / "eval_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    write_public_summary(report)
    return report


def write_public_summary(report: Dict[str, object]) -> None:
    """Scores per question without answer text: answers quote private docs, so only the full report stays local."""
    keep = ("question", "in_scope", "hit_rank", "abstained", "facts_found", "facts_total",
            "sentences", "supported_sentences", "seconds")
    public = {"summary": report["summary"],
              "results": [{k: r[k] for k in keep if k in r} for r in report["results"]]}
    PUBLIC_SUMMARY.write_text(json.dumps(public, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
