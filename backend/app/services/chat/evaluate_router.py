"""Red-flag router evaluation (7d, Unit 2): false positives over every question that should
not get a template, and routing of the ones that should.

    python -m app.services.chat.evaluate_router --split dev    # author dev, dev_uncovered.txt, router probes (tune here only)
    python -m app.services.chat.evaluate_router --split test   # author test + the 20 external questions; once
    python -m app.services.chat.evaluate_router --heldout      # the user's 10 red flags; once, before any fix

A false positive is a template (a fixed answer, no model) for a question that should have
been answered. A soft flag is not one: the model still answers, with a caution line after.
The external questions are used for the router only (their retrieval results are frozen).
The 10 held-out red-flag paraphrases (from the user, later) measure the other direction.
"""

import argparse
import json
import sys
from datetime import datetime, timezone

from . import chat_config as cfg
from . import eval_files as ef
from .evaluate import config_fingerprint, frac, proportion
from .redflags import route

RESULTS = ef.EVAL_DIR / "router_test_results.json"
HELDOUT_RESULTS = ef.EVAL_DIR / "heldout_redflags_results.json"


class RouterEvalError(Exception):
    pass


def expected_template(expect: str) -> str | None:
    return expect.split(":", 1)[1] if expect.startswith("template:") else None


def questions(split: str) -> list[tuple[str, str, str, str | None]]:
    """(source, id, question, expected template id or None)."""
    rows = [("author", q.id, q.question, expected_template(q.expect))
            for q in ef.load_author_questions() if q.split == split]
    if split == "dev":
        rows += [("dev_uncovered", f"u{q.number}", q.question, None) for q in ef.load_dev_uncovered()]
        rows += [("dev_probes", p["id"], p["question"], None) for p in ef.load_router_probes()]
    else:
        rows += [("external", f"x{q.number}", q.question, None) for q in ef.load_user_questions()]
    return rows


def evaluate(split: str) -> dict:
    rows = questions(split)
    results = []
    for source, qid, text, expected in rows:
        r = route(text)
        results.append({"source": source, "id": qid, "expected": expected, "kind": r.kind, "group": r.group,
                        "template": r.template_id, "cautions": list(r.cautions)})
    plain = [x for x in results if x["expected"] is None]
    flagged = [x for x in plain if x["kind"] == "template"]
    soft = [x for x in plain if x["kind"] == "soft"]
    routed = [x for x in results if x["expected"] is not None]
    right = [x for x in routed if x["template"] == x["expected"]]
    by_source = {}
    for source in dict.fromkeys(x["source"] for x in plain):
        mine = [x for x in plain if x["source"] == source]
        by_source[source] = proportion(sum(x["kind"] == "template" for x in mine), len(mine))
    return {
        "split": split,
        "chat_config": {"version": cfg.CHAT_CONFIG_VERSION,
                        "fingerprint": config_fingerprint(cfg, "CHAT_CONFIG_VERSION")},
        "non_red_flag": len(plain),
        "false_positives": proportion(len(flagged), len(plain)),
        "false_positives_by_source": by_source,
        "soft_flags": proportion(len(soft), len(plain)),
        "expected_templates_routed_right": proportion(len(right), len(routed)),
        "per_question": results,
    }


def report(result: dict, texts: dict[str, str]) -> None:
    split = result["split"]
    print(f"Router evaluation, {split} split; chat config {result['chat_config']['version']} "
          f"(fingerprint {result['chat_config']['fingerprint']})")
    sources = "author dev, dev_uncovered.txt (drafted by Claude in chat), router probes" if split == "dev" else \
        "author test + the 20 external questions (router only)"
    print(f"Questions: {sources}. The author also wrote the router; n is small (95% Wilson).")
    fp = result["false_positives"]
    print(f"\nFalse positives (a template for a question that should be answered): "
          f"{frac(fp['k'], fp['n'])}")
    for source, p in result["false_positives_by_source"].items():
        print(f"  {source}: {frac(p['k'], p['n'])}")
    for x in result["per_question"]:
        if x["expected"] is None and x["kind"] == "template":
            print(f"  FLAGGED {x['id']} -> {x['group']} ({x['template']}): {texts[x['id']]}")
    sf = result["soft_flags"]
    print(f"\nSoft flags (answered, with a caution line appended): {frac(sf['k'], sf['n'])}")
    for x in result["per_question"]:
        if x["expected"] is None and x["kind"] == "soft":
            print(f"  soft {x['id']} [{', '.join(x['cautions'])}]: {texts[x['id']]}")
    ok = result["expected_templates_routed_right"]
    print(f"\nQuestions that expect a template, routed to it: {frac(ok['k'], ok['n'])}")
    for x in result["per_question"]:
        if x["expected"] is not None:
            mark = "ok " if x["template"] == x["expected"] else "MISS"
            print(f"  {mark} {x['id']} expects {x['expected']}, got {x['template'] or x['kind']}: {texts[x['id']]}")


def run_heldout(path=None, results_path=HELDOUT_RESULTS) -> dict:
    """The user's held-out red flags, once, before any fix: hits, and for each miss what fired."""
    if results_path.exists():
        raise RouterEvalError(f"{results_path.name} already exists: the held-out run happens once, before any fix.")
    items = ef.load_heldout_redflags(path)
    rows = []
    for item in items:
        r = route(item["text"])
        rows.append({"id": item["id"], "expected": item["expected"], "kind": r.kind, "group": r.group,
                     "template": r.template_id, "cautions": list(r.cautions), "hit": r.template_id == item["expected"]})
    hits = sum(x["hit"] for x in rows)
    result = {
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": "Run once, before any fix. The user wrote these after seeing the trigger table (not blind).",
        "heldout_sha256": ef.sha256_of(path or ef.HELDOUT_REDFLAGS),
        "chat_config": {"version": cfg.CHAT_CONFIG_VERSION,
                        "fingerprint": config_fingerprint(cfg, "CHAT_CONFIG_VERSION")},
        "hits": proportion(hits, len(rows)),
        "per_item": rows,
    }
    results_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Held-out red flags (the user's, written after seeing the trigger table): hits {frac(hits, len(rows))}")
    texts = {i["id"]: i["text"] for i in items}
    for x in rows:
        got = x["template"] or (f"soft [{', '.join(x['cautions'])}]" if x["kind"] == "soft" else "none")
        print(f"  {'hit ' if x['hit'] else 'MISS'} {x['id']} expects {x['expected']}, got {got}: {texts[x['id']]}")
    print(f"\nResults written to {results_path.relative_to(ef.EVAL_DIR.parent)}")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="7d router evaluation")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--split", choices=ef.SPLITS)
    mode.add_argument("--heldout", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.heldout:
            run_heldout()
            return 0
        metadata = ef.check_hashes()
        dev_meta = ef.check_dev_uncovered()
        if args.split == "test" and RESULTS.exists():
            raise RouterEvalError(f"{RESULTS.name} already exists: the router's test run happens once.")
        result = evaluate(args.split)
        texts = {qid: text for _, qid, text, _ in questions(args.split)}
        report(result, texts)
        if args.split == "test":
            result.update({
                "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "question_files": {**{n: e["sha256"] for n, e in metadata["question_files"].items()},
                                   **{n: e["sha256"] for n, e in dev_meta["question_files"].items()}},
            })
            RESULTS.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            print(f"\nResults written to {RESULTS.relative_to(ef.EVAL_DIR.parent)}")
    except (RouterEvalError, ef.EvalFileError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
