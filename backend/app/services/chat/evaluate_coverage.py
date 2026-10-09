"""Choosing the term-coverage minimum (7d, Unit 2): dev questions only.

    python -m app.services.chat.evaluate_coverage

Uses the 7 answerable author dev questions (d01-d07, which must all still pass) and the 15
dev_uncovered.txt questions (all not covered; drafted by Claude in a chat session after
seeing the KB topic list and eight chunks, so not independent). The author test questions
and the 20 external questions are never read here.

A question is answered only if its best chunk clears the frozen BM25 line AND covers at
least the minimum share of its content words. The rule, fixed before the run: among the
candidates that keep all 7 answerable questions, the one that refuses the most of the 15;
ties -> the middle candidate (the lower of two middles).
"""

import sys

from . import chat_config as cfg
from . import eval_files as ef
from .coverage import coverage
from .evaluate import frac
from .kb import load_kb
from .retrieval import build_index, retrieve


def rows():
    kb = load_kb()
    index = build_index(kb)
    out = []
    answerable = [q for q in ef.load_author_questions() if q.split == "dev" and q.group in ("in_kb", "profile")]
    sources = [("answerable", q.id, q.question) for q in answerable]
    sources += [("uncovered", f"u{q.number}", q.question) for q in ef.load_dev_uncovered()]
    sources += [("author_no_answer", q.id, q.question) for q in ef.load_author_questions()
                if q.split == "dev" and q.group in ("unanswerable", "out_of_scope")]
    for kind, qid, text in sources:
        r = retrieve(index, text, cfg.TOP_K, None)
        top = r.hits[0].chunk_id if r.hits else None
        cov = coverage(text, kb.get(top)) if top else 0.0
        out.append({"kind": kind, "id": qid, "top": top, "score": r.top_score, "coverage": round(cov, 4)})
    return out


def passes(row, minimum: float) -> bool:
    return row["score"] >= cfg.NO_ANSWER_MIN_SCORE and row["coverage"] >= minimum


def candidates(values: list[float]) -> list[float]:
    distinct = sorted(set(values))
    return [0.0, *[round((a + b) / 2, 4) for a, b in zip(distinct, distinct[1:])], 1.01]


def choose(table: list[dict]) -> float:
    answerable = [r for r in table if r["kind"] == "answerable"]
    uncovered = [r for r in table if r["kind"] == "uncovered"]
    feasible = [c for c in candidates([r["coverage"] for r in answerable + uncovered])
                if all(passes(r, c) for r in answerable)]
    refused = {c: sum(not passes(r, c) for r in uncovered) for c in feasible}
    best = max(refused.values())
    tied = [c for c in feasible if refused[c] == best]
    return tied[(len(tied) - 1) // 2]


def main() -> int:
    ef.check_hashes()
    ef.check_dev_uncovered()
    table = rows()
    answerable = [r for r in table if r["kind"] == "answerable"]
    uncovered = [r for r in table if r["kind"] == "uncovered"]
    print("Term coverage on the dev questions only (n is small; 95% Wilson).")
    print(f"BM25 line (frozen): {cfg.NO_ANSWER_MIN_SCORE}\n")
    print(f"{'id':5} {'kind':16} {'score':>6} {'cover':>6}  top chunk")
    for r in table:
        print(f"{r['id']:5} {r['kind']:16} {r['score']:6.2f} {r['coverage']:6.2f}  {r['top']}")
    print(f"\n{'minimum':>8}  answerable kept  uncovered refused")
    for c in candidates([r["coverage"] for r in answerable + uncovered]):
        kept = sum(passes(r, c) for r in answerable)
        refused = sum(not passes(r, c) for r in uncovered)
        print(f"{c:8.4f}  {kept:>6}/{len(answerable):<8} {refused:>6}/{len(uncovered)}")
    chosen = choose(table)
    kept = sum(passes(r, chosen) for r in answerable)
    refused = sum(not passes(r, chosen) for r in uncovered)
    line_only = sum(not passes(r, 0.0) for r in uncovered)
    print(f"\nRule -> minimum {chosen}: answerable kept {frac(kept, len(answerable))}; "
          f"uncovered refused {frac(refused, len(uncovered))} (the BM25 line alone: {frac(line_only, len(uncovered))})")
    other = [r for r in table if r["kind"] == "author_no_answer"]
    print(f"For information (not used to choose): author dev no-answer questions refused at it: "
          f"{frac(sum(not passes(r, chosen) for r in other), len(other))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
