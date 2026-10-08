"""Retrieval evaluation (7d, Unit 1): BM25 only. No model, router or gate yet.

    python -m app.services.chat.evaluate --split dev    # tune here only: shows the threshold table
    python -m app.services.chat.evaluate --freeze       # record the frozen retrieval before any test run
    python -m app.services.chat.evaluate --split test   # once, with the user's mapping; writes eval/test_results.json
    python -m app.services.chat.evaluate --leakage      # word runs shared by chunks and external questions

The no-answer line (chat_config.NO_ANSWER_MIN_SCORE) is chosen on the dev questions only, by
the rule in choose_line(), then written into chat_config by hand and frozen. The freeze
covers what decides retrieval and nothing else (FROZEN_RETRIEVAL_KEYS, the knowledge base,
retrieval.py), so later units can add router terms, templates and gate patterns to
chat_config without touching it. The test split refuses to run if any of it changed, runs
once, and writes its results with the hashes of everything it used.

Two authorships, never pooled:
- eval/author_questions.json was written by Claude, who also wrote the knowledge base.
- eval/user_questions.txt was drafted by Claude in a separate session (see eval_files.AUTHORSHIP).
  Its results appear only once the user's mapping (eval/user_question_labels.json) exists:
  recall on the questions mapped to chunks, refusal accuracy on the "not_covered" ones,
  never one recall figure over all 20.
"""

import argparse
import contextlib
import hashlib
import io
import json
import math
import sys
from datetime import datetime, timezone
from types import ModuleType

from . import chat_config as cfg
from . import eval_files as ef
from .kb import KnowledgeBase, load_kb
from .kb_check import longest_run, words
from .retrieval import build_index, retrieve

FREEZE = ef.EVAL_DIR / "freeze.json"
RESULTS = ef.EVAL_DIR / "test_results.json"
RETRIEVAL_CODE = ef.EVAL_DIR.parent / "retrieval.py"
# The chat_config values that decide which chunks a question retrieves: what the freeze
# covers. Aliases live in kb.json (the KB fingerprint covers them). A test checks that every
# chat_config name retrieval.py reads is listed here.
FROZEN_RETRIEVAL_KEYS = (
    "BM25_K1", "BM25_B", "TOP_K", "NO_ANSWER_MIN_SCORE", "TOKEN_PATTERN", "PLURAL_RULES",
    "KEEP_ENDINGS", "MIN_STEM", "SPELLING", "STOPWORDS", "QUESTION_IDIOMS",
)
ANSWER_GROUPS = ("in_kb", "profile")  # retrieval recall is scored on these
NO_ANSWER_GROUPS = ("unanswerable", "out_of_scope")  # the no-answer line should refuse these
LATER_GROUPS = ("injection", "red_flag")  # the router and the gate (Unit 2) score these
K = cfg.TOP_K
Z = 1.96  # 95% Wilson interval


class EvaluationError(Exception):
    pass


def _plain(value):
    """JSON-able, deterministic form (as app/tests/test_config_versions.py)."""
    if isinstance(value, dict):
        return {(k if isinstance(k, str) else repr(k)): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def _digest(values: dict) -> str:
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()[:16]


def config_fingerprint(module: ModuleType, version_name: str) -> str:
    """The same fingerprint as app/tests/test_config_versions.py (a test checks they agree)."""
    return _digest({n: _plain(getattr(module, n)) for n in dir(module) if n.isupper() and n != version_name})


def retrieval_fingerprint() -> str:
    """Over FROZEN_RETRIEVAL_KEYS only."""
    return _digest({n: _plain(getattr(cfg, n)) for n in FROZEN_RETRIEVAL_KEYS})


def wilson(k: int, n: int, z: float = Z) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, centre - half), min(1.0, centre + half))


def frac(k: int, n: int) -> str:
    lo, hi = wilson(k, n)
    return f"{k}/{n} (95% Wilson {lo:.2f}-{hi:.2f})" if n else "0/0"


def proportion(k: int, n: int) -> dict:
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "wilson_95": [round(lo, 3), round(hi, 3)]}


def first_rank(ids: tuple[str, ...], relevant: tuple[str, ...]) -> int | None:
    return next((i for i, cid in enumerate(ids, 1) if cid in relevant), None)


def margin(top: float, line: float | None) -> str:
    """Top score minus the line: positive = answered, negative = refused."""
    return f"{top - line:+7.2f}" if line is not None else "      -"


def candidate_lines(scores: list[float]) -> list[float]:
    """0 (answer everything), the midpoints between distinct scores, and one above the top."""
    distinct = sorted(set(scores))
    mids = [round((a + b) / 2, 4) for a, b in zip(distinct, distinct[1:])]
    return [0.0, *mids, round(distinct[-1] + 1, 4)] if distinct else [0.0]


def correct_at(line: float, answer_tops: list[float], no_answer_tops: list[float]) -> tuple[int, int]:
    return sum(t >= line for t in answer_tops), sum(t < line for t in no_answer_tops)


def choose_line(answer_tops: list[float], no_answer_tops: list[float]) -> float:
    """The rule, fixed before any run: the candidate with the most dev questions handled
    right (answerable kept + no-answer refused); among ties, the middle one (the median of
    the tied candidates, the lower of the two middles for an even number)."""
    cands = candidate_lines(answer_tops + no_answer_tops)
    totals = [sum(correct_at(c, answer_tops, no_answer_tops)) for c in cands]
    tied = [c for c, t in zip(cands, totals) if t == max(totals)]
    return round(tied[(len(tied) - 1) // 2], 2)


def header(kb: KnowledgeBase, metadata: dict, split: str) -> None:
    print(f"Retrieval evaluation, {split} split, {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    print("Retrieval only (Unit 1): BM25 over the knowledge base. No model, router or gate yet.")
    print(f"Knowledge base {kb.version} (fingerprint {kb.fingerprint}); checked by a person: "
          f"{sum(c.review.status == 'checked' for c in kb.chunks)}/{len(kb.chunks)}")
    print(f"Retrieval settings fingerprint {retrieval_fingerprint()} (chat config {cfg.CHAT_CONFIG_VERSION}); "
          f"top k = {K}; no-answer line = "
          f"{cfg.NO_ANSWER_MIN_SCORE if cfg.NO_ANSWER_MIN_SCORE is not None else 'not set'}")
    for name, entry in metadata["question_files"].items():
        print(f"{name}: sha256 {entry['sha256'][:16]}... unchanged since {metadata['recorded_at']}")


def author_section(questions, index, kb: KnowledgeBase, line: float | None, split: str) -> dict:
    print(f"\n=== Questions written by the KB's author (Claude), {split} split ===")
    print("The same person wrote the knowledge base, these questions and their labels: read these")
    print("results as optimistic.")
    unknown = sorted({c for q in questions for c in q.relevant + q.acceptable} - set(kb.ids))
    if unknown:
        raise EvaluationError(f"labels name chunks the KB doesn't have: {unknown}")
    results = {q.id: retrieve(index, q.question, K, None) for q in questions}
    answer = [q for q in questions if q.group in ANSWER_GROUPS]
    refuse = [q for q in questions if q.group in NO_ANSWER_GROUPS]

    print(f"\n{'id':4} {'group':12} {'rank':>4}  {'top':>7}  {'vs line':>7}  top {K} (score)")
    for q in answer + refuse:
        r = results[q.id]
        rank = first_rank(r.ids, q.relevant) if q.relevant else None
        hits = ", ".join(f"{h.chunk_id} ({h.score:.2f})" for h in r.hits) or "(no matching term)"
        print(f"{q.id:4} {q.group:12} {rank if rank else '-':>4}  {r.top_score:7.2f}  {margin(r.top_score, line)}  {hits}")

    ranks = [first_rank(results[q.id].ids, q.relevant) for q in answer]
    n = len(answer)
    recall = [len(set(results[q.id].ids) & set(q.relevant)) / len(q.relevant) for q in answer]
    metrics = {
        "answerable": n,
        "hit_at_1": proportion(sum(r == 1 for r in ranks), n),
        f"hit_at_{K}": proportion(sum(r is not None for r in ranks), n),
        f"mean_recall_at_{K}": round(sum(recall) / n, 3) if n else None,
        "mrr": round(sum(1 / r for r in ranks if r) / n, 3) if n else None,
        "per_question": {q.id: {"rank": first_rank(results[q.id].ids, q.relevant) if q.relevant else None,
                                "top_score": results[q.id].top_score, "top_ids": list(results[q.id].ids)}
                         for q in answer + refuse},
    }
    print(f"\nAnswerable questions (in_kb + profile), n = {n}:")
    print(f"  hit@1 {frac(sum(r == 1 for r in ranks), n)}")
    print(f"  hit@{K} {frac(sum(r is not None for r in ranks), n)}")
    if n:
        print(f"  mean recall@{K} {metrics[f'mean_recall_at_{K}']:.2f}; MRR {metrics['mrr']:.2f}")

    answer_tops = [results[q.id].top_score for q in answer]
    no_answer_tops = [results[q.id].top_score for q in refuse]
    if split == "dev":
        print(f"\nNo-answer line on the dev questions ({len(answer)} answerable, {len(refuse)} to refuse):")
        print(f"  {'line':>7}  {'answered':>9}  {'refused':>8}  correct")
        for c in candidate_lines(answer_tops + no_answer_tops):
            kept, refused = correct_at(c, answer_tops, no_answer_tops)
            print(f"  {c:7.2f}  {kept:>4}/{len(answer):<4}  {refused:>3}/{len(refuse):<4}  {kept + refused}")
        print(f"  Rule (choose_line): most correct, ties -> the middle candidate: {choose_line(answer_tops, no_answer_tops)}")
    if line is not None:
        kept, refused = correct_at(line, answer_tops, no_answer_tops)
        metrics["answered_at_line"] = proportion(kept, len(answer))
        metrics["refused_at_line"] = proportion(refused, len(refuse))
        print(f"\nAt the line {line}: answerable answered {frac(kept, len(answer))}; "
              f"no-answer refused {frac(refused, len(refuse))}")
        missed = [q.id for q, t in zip(answer, answer_tops) if t < line]
        leaked = [q.id for q, t in zip(refuse, no_answer_tops) if t >= line]
        print(f"  answerable but refused: {missed or 'none'}; should refuse but answered: {leaked or 'none'}")

    later = [q for q in questions if q.group in LATER_GROUPS]
    probes = [q.id for q in questions if q.fp_probe]
    print(f"\nNot scored in Unit 1 (router and gate, Unit 2): {', '.join(q.id for q in later)}")
    print(f"Router false-positive probes (scored in Unit 2): {', '.join(probes)}")
    return metrics


def external_section(index, kb: KnowledgeBase, line: float | None) -> dict | None:
    print("\n=== External questions (eval/user_questions.txt), test split ===")
    print(ef.AUTHORSHIP[ef.USER_QUESTIONS.name])
    questions = ef.load_user_questions()
    labels = ef.load_user_labels([q.number for q in questions])
    if labels is None:
        print(f"{len(questions)} questions. {ef.USER_LABELS.name} (the user's mapping) doesn't exist yet: results are "
              "withheld until it does, so they can't influence the mapping.")
        return None
    unknown = sorted({c for v in labels.values() if v != ef.NOT_COVERED for c in v} - set(kb.ids))
    if unknown:
        raise EvaluationError(f"{ef.USER_LABELS.name} names chunks the KB doesn't have: {unknown}")
    covered = [q for q in questions if labels[q.number] != ef.NOT_COVERED]
    not_covered = [q for q in questions if labels[q.number] == ef.NOT_COVERED]
    results = {q.number: retrieve(index, q.question, K, None) for q in questions}
    print(f"Covered (mapped to chunks by the user): {len(covered)}; not covered: {len(not_covered)}")
    print(f"\n{'#':>3} {'label':12} {'rank':>4}  {'top':>7}  {'vs line':>7}  top {K}")
    for q in questions:
        r, label = results[q.number], labels[q.number]
        rank = first_rank(r.ids, label) if label != ef.NOT_COVERED else None
        print(f"{q.number:>3} {'not covered' if label == ef.NOT_COVERED else 'covered':12} {rank if rank else '-':>4}  "
              f"{r.top_score:7.2f}  {margin(r.top_score, line)}  "
              f"{', '.join(h.chunk_id for h in r.hits) or '(no matching term)'}")
    ranks = [first_rank(results[q.number].ids, labels[q.number]) for q in covered]
    n = len(covered)
    metrics = {
        "covered": n, "not_covered": len(not_covered),
        "per_question": {str(q.number): {"label": labels[q.number] if labels[q.number] == ef.NOT_COVERED
                                         else list(labels[q.number]),
                                         "top_score": results[q.number].top_score,
                                         "top_ids": list(results[q.number].ids)} for q in questions},
    }
    print(f"\nCovered questions only, n = {n}:")
    if n:
        recall = [len(set(results[q.number].ids) & set(labels[q.number])) / len(labels[q.number]) for q in covered]
        metrics.update({"hit_at_1": proportion(sum(r == 1 for r in ranks), n),
                        f"hit_at_{K}": proportion(sum(r is not None for r in ranks), n),
                        f"mean_recall_at_{K}": round(sum(recall) / n, 3),
                        "mrr": round(sum(1 / r for r in ranks if r) / n, 3)})
        print(f"  hit@1 {frac(sum(r == 1 for r in ranks), n)}; hit@{K} {frac(sum(r is not None for r in ranks), n)}")
        print(f"  mean recall@{K} {metrics[f'mean_recall_at_{K}']:.2f}; MRR {metrics['mrr']:.2f}")
    if line is not None:
        kept = sum(results[q.number].top_score >= line for q in covered)
        refused = sum(results[q.number].top_score < line for q in not_covered)
        metrics["covered_answered_at_line"] = proportion(kept, n)
        metrics["not_covered_refused_at_line"] = proportion(refused, len(not_covered))
        print(f"At the frozen line {line}: covered answered {frac(kept, n)}; "
              f"not covered refused {frac(refused, len(not_covered))}")
    print("(No single recall figure over all 20: the not-covered ones test the no-answer path.)")
    return metrics


def freeze_record(kb: KnowledgeBase, metadata: dict) -> dict:
    return {
        "retrieval": {"keys": list(FROZEN_RETRIEVAL_KEYS), "fingerprint": retrieval_fingerprint()},
        "kb": {"version": kb.version, "fingerprint": kb.fingerprint},
        "no_answer_min_score": cfg.NO_ANSWER_MIN_SCORE,
        # The code that turns a question into chunks: a change to it is a change to the results.
        "retrieval_code_sha256": ef.sha256_of(RETRIEVAL_CODE),
        "question_files": {name: e["sha256"] for name, e in metadata["question_files"].items()},
    }


def freeze(kb: KnowledgeBase, metadata: dict, path=FREEZE) -> dict:
    if path.exists():
        raise EvaluationError(f"{path.name} already exists: a freeze is recorded once. Bump the versions and "
                              "delete it only with the user's agreement.")
    if cfg.NO_ANSWER_MIN_SCORE is None:
        raise EvaluationError("NO_ANSWER_MIN_SCORE isn't set: choose it on the dev split first.")
    record = {"frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "note": "Set on the dev questions only. The test split runs only while these match.",
              **freeze_record(kb, metadata)}
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def _whole_config_record(kb: KnowledgeBase, metadata: dict) -> dict:
    """The freeze as first recorded (2026-10-08): over every value in chat_config."""
    record = freeze_record(kb, metadata)
    del record["retrieval"]
    return {"chat_config": {"version": cfg.CHAT_CONFIG_VERSION,
                            "fingerprint": config_fingerprint(cfg, "CHAT_CONFIG_VERSION")}, **record}


def rescope_freeze(kb: KnowledgeBase, metadata: dict, path=FREEZE) -> dict:
    """One-off (STOP 2 review): move a freeze recorded over all of chat_config to the
    retrieval settings only. Refuses unless the old record still verifies exactly, so the
    new freeze holds the very settings that were frozen (nothing re-tuned)."""
    recorded = json.loads(path.read_text(encoding="utf-8"))
    if "retrieval" in recorded:
        raise EvaluationError(f"{path.name} is already scoped to the retrieval settings.")
    old = _whole_config_record(kb, metadata)
    changed = [k for k in old if recorded.get(k) != old[k]]
    if changed:
        raise EvaluationError(f"the recorded freeze doesn't verify ({', '.join(changed)} changed): not rescoping.")
    record = {
        "frozen_at": recorded["frozen_at"],
        "rescoped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": recorded["note"] + " Rescoped to the retrieval settings after verifying the original freeze.",
        **freeze_record(kb, metadata),
        "previous_scope": {"chat_config": recorded["chat_config"],
                           "note": "Until the rescope the freeze covered every value in chat_config; it "
                                   "verified unchanged at the rescope."},
    }
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def check_freeze(kb: KnowledgeBase, metadata: dict, path=FREEZE) -> dict:
    if not path.exists():
        raise EvaluationError(f"{path.name} is missing: freeze the dev-tuned config (--freeze) before a test run.")
    recorded = json.loads(path.read_text(encoding="utf-8"))
    now = freeze_record(kb, metadata)
    changed = [k for k in now if recorded.get(k) != now[k]]
    if changed:
        raise EvaluationError(f"changed since the freeze: {', '.join(changed)}. Never tune on the test split.")
    return recorded


def write_results(record: dict, path=RESULTS) -> None:
    if path.exists():
        raise EvaluationError(f"{path.name} already exists: the test split runs once.")
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def leakage(kb: KnowledgeBase) -> None:
    """The longest word run each external question shares with any chunk (numbers only)."""
    print("Longest word run shared by each external question and any chunk (title, aliases, text).")
    print("The KB's author read these questions before fixing the topic list; long runs would")
    print("point to wording taken from them.")
    texts = {c.id: words(" ".join([c.title, *c.aliases, c.text])) for c in kb.chunks}
    for q in ef.load_user_questions():
        mine = words(q.question)
        best = max(texts, key=lambda cid: (longest_run(mine, texts[cid]), cid))
        print(f"  question {q.number:>2}: {longest_run(mine, texts[best])} words ({best})")


def run_test(kb: KnowledgeBase, metadata: dict, freeze_path=FREEZE, results_path=RESULTS) -> dict:
    """The test split, once: needs the freeze to verify and the user's mapping to exist."""
    frozen = check_freeze(kb, metadata, freeze_path)
    if results_path.exists():
        raise EvaluationError(f"{results_path.name} already exists: the test split runs once.")
    if not ef.USER_LABELS.exists():
        raise EvaluationError(f"{ef.USER_LABELS.name} (the user's mapping) doesn't exist yet: the test split runs "
                              "once, with it.")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        index = build_index(kb)
        header(kb, metadata, "test")
        questions = [q for q in ef.load_author_questions() if q.split == "test"]
        author = author_section(questions, index, kb, cfg.NO_ANSWER_MIN_SCORE, "test")
        external = external_section(index, kb, cfg.NO_ANSWER_MIN_SCORE)
    report = out.getvalue()
    print(report, end="")
    record = {
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "freeze": frozen,
        "question_files": {name: e["sha256"] for name, e in metadata["question_files"].items()},
        "user_question_labels_sha256": ef.sha256_of(ef.USER_LABELS),
        "authorship": {"author_questions.json": ef.AUTHORSHIP[ef.AUTHOR_QUESTIONS.name],
                       "user_questions.txt": ef.AUTHORSHIP[ef.USER_QUESTIONS.name]},
        "author_test": author,
        "external": external,
        "report": report.splitlines(),
    }
    write_results(record, results_path)
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="7d retrieval evaluation")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--split", choices=ef.SPLITS)
    mode.add_argument("--freeze", action="store_true")
    mode.add_argument("--rescope-freeze", action="store_true")
    mode.add_argument("--leakage", action="store_true")
    args = parser.parse_args(argv)
    try:
        metadata = ef.check_hashes()
        kb = load_kb()
        if args.leakage:
            leakage(kb)
        elif args.freeze:
            print(json.dumps(freeze(kb, metadata), indent=2))
        elif args.rescope_freeze:
            print(json.dumps(rescope_freeze(kb, metadata), indent=2))
        elif args.split == "test":
            run_test(kb, metadata)
            print(f"\nResults written to {RESULTS.relative_to(ef.EVAL_DIR.parent)}")
        else:
            header(kb, metadata, "dev")
            questions = [q for q in ef.load_author_questions() if q.split == "dev"]
            author_section(questions, build_index(kb), kb, cfg.NO_ANSWER_MIN_SCORE, "dev")
    except (EvaluationError, ef.EvalFileError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
