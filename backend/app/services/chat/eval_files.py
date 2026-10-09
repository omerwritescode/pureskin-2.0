"""The evaluation's question files and the hashes recorded for them (7d).

- eval/author_questions.json: 22 questions written by the knowledge base's author
  (dev 14, test 8), before any chunk text existed.
- eval/user_questions.txt: 20 retrieval questions drafted by Claude in a separate chat
  session (not the user, not the KB author), before the KB existed, never shown its
  chunks. Read only through this module, and never edited.
- eval/user_question_labels.json: the user's mapping of those 20 questions to chunk ids,
  or "not_covered". Written by the user; absent until then.
- eval/metadata.json: the SHA-256 of the two question files, recorded once (before any
  chunk text existed) and never rewritten. Every evaluation run checks the files still
  match it, so a question can't be edited after the fact.

    python -m app.services.chat.eval_files --record-hashes   # once
    python -m app.services.chat.eval_files --check
"""

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent / "eval"
AUTHOR_QUESTIONS = EVAL_DIR / "author_questions.json"
USER_QUESTIONS = EVAL_DIR / "user_questions.txt"
USER_LABELS = EVAL_DIR / "user_question_labels.json"
METADATA = EVAL_DIR / "metadata.json"
# Unit 2: the user's dev questions the KB doesn't cover (all "not_covered"). Its hash has its
# own record, so metadata.json (which the retrieval freeze checks) is never rewritten.
DEV_UNCOVERED = EVAL_DIR / "dev_uncovered.txt"
METADATA_DEV_UNCOVERED = EVAL_DIR / "metadata_dev_uncovered.json"
# Unit 2: the router's dev probes (author-written, dev only) and the user's held-out red flags.
DEV_ROUTER_PROBES = EVAL_DIR / "dev_router_probes.json"
HELDOUT_REDFLAGS = EVAL_DIR / "heldout_redflags.json"

SPLITS = ("dev", "test")
GROUPS = ("in_kb", "profile", "unanswerable", "out_of_scope", "injection", "red_flag")
EXPECT = re.compile(r"^(answer|no_answer|gate|template:[a-z_]+)$")
QUESTION_FIELDS = {"id", "split", "group", "question", "relevant", "acceptable", "expect", "fp_probe"}
NOT_COVERED = "not_covered"

AUTHORSHIP = {
    AUTHOR_QUESTIONS.name: (
        "Written by Claude, the author of the knowledge base, on 2026-10-08 before any chunk "
        "text existed."
    ),
    USER_QUESTIONS.name: (
        "Drafted by Claude in a separate chat session: not by the user and not by the KB "
        "author. Written before the KB existed and never shown its chunks. The KB author read "
        "this file before fixing the 24-chunk topic list (STOP 1)."
    ),
    DEV_UNCOVERED.name: (
        "Drafted by Claude in a chat session after seeing the KB topic list and eight chunk "
        "texts, then saved by the user (2026-10-08, Unit 2). Not independent of the KB. Dev "
        "questions, all not covered by the KB; used for tuning (router false positives, term "
        "coverage)."
    ),
}


class EvalFileError(Exception):
    pass


@dataclass(frozen=True)
class Question:
    id: str
    split: str
    group: str
    question: str
    relevant: tuple[str, ...]
    acceptable: tuple[str, ...]
    expect: str
    fp_probe: bool


@dataclass(frozen=True)
class UserQuestion:
    number: int
    question: str


def sha256_of(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def record_hashes(metadata: Path = METADATA, files: tuple[Path, ...] = (AUTHOR_QUESTIONS, USER_QUESTIONS),
                  note: str = "Recorded before any knowledge-base chunk text existed.") -> dict:
    """Write a record of each question file's SHA-256. Once only: never overwrites."""
    if metadata.exists():
        raise EvalFileError(f"{metadata.name} already exists: the hashes are recorded once and never rewritten.")
    data = {
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": note,
        "question_files": {
            f.name: {"sha256": sha256_of(f), "authorship": AUTHORSHIP.get(f.name, "")} for f in files
        },
    }
    metadata.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data


def check_hashes(metadata: Path = METADATA, eval_dir: Path = EVAL_DIR) -> dict:
    """The recorded metadata, after checking every question file still has its recorded hash."""
    if not metadata.exists():
        raise EvalFileError(f"{metadata.name} is missing: record the question hashes first (--record-hashes).")
    data = json.loads(metadata.read_text(encoding="utf-8"))
    changed = [
        name for name, entry in data["question_files"].items()
        if not (eval_dir / name).exists() or sha256_of(eval_dir / name) != entry["sha256"]
    ]
    if changed:
        raise EvalFileError(f"question file(s) changed since their hashes were recorded: {', '.join(changed)}")
    return data


def check_dev_uncovered(record: Path | None = None, eval_dir: Path | None = None) -> dict:
    """check_hashes() for dev_uncovered.txt's own record."""
    return check_hashes(record or METADATA_DEV_UNCOVERED, eval_dir or EVAL_DIR)


def load_dev_uncovered(path: Path | None = None) -> tuple[UserQuestion, ...]:
    """The user's dev questions not covered by the KB ("N. text" lines, as user_questions.txt)."""
    return load_user_questions(path or DEV_UNCOVERED)


def load_router_probes(path: Path | None = None) -> tuple[dict, ...]:
    """The router's dev probes: {id, question, expect ("no_template")}."""
    return tuple(json.loads(Path(path or DEV_ROUTER_PROBES).read_text(encoding="utf-8"))["probes"])


def load_heldout_redflags(path: Path | None = None) -> tuple[dict, ...]:
    """The user's held-out red flags: [{id, expected (a template id), text}]."""
    items = json.loads(Path(path or HELDOUT_REDFLAGS).read_text(encoding="utf-8"))
    if not (isinstance(items, list) and all(set(i) == {"id", "expected", "text"} for i in items)):
        raise EvalFileError(f"{HELDOUT_REDFLAGS.name}: expected a list of {{id, expected, text}}")
    return tuple(items)


def load_author_questions(path: Path | None = None) -> tuple[Question, ...]:
    data = json.loads(Path(path or AUTHOR_QUESTIONS).read_text(encoding="utf-8"))
    problems, out, seen = [], [], set()
    for i, q in enumerate(data["questions"]):
        where = q.get("id", f"#{i}")
        if set(q) != QUESTION_FIELDS:
            problems.append(f"{where}: fields {sorted(set(q) ^ QUESTION_FIELDS)} missing or unknown")
            continue
        if q["id"] in seen:
            problems.append(f"{where}: duplicate id")
        seen.add(q["id"])
        if q["split"] not in SPLITS:
            problems.append(f"{where}: unknown split {q['split']!r}")
        if q["group"] not in GROUPS:
            problems.append(f"{where}: unknown group {q['group']!r}")
        if not EXPECT.match(q["expect"]):
            problems.append(f"{where}: bad expect {q['expect']!r}")
        if not isinstance(q["fp_probe"], bool):
            problems.append(f"{where}: fp_probe must be true or false")
        out.append(Question(q["id"], q["split"], q["group"], q["question"], tuple(q["relevant"]),
                            tuple(q["acceptable"]), q["expect"], q["fp_probe"]))
    if problems:
        raise EvalFileError("; ".join(problems))
    return tuple(out)


def load_user_questions(path: Path | None = None) -> tuple[UserQuestion, ...]:
    """The numbered lines ("1. text"), exactly as written. Any other non-blank line is an error."""
    path = path or USER_QUESTIONS
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        m = re.match(r"^\s*(\d+)\.\s+(.+?)\s*$", line)
        if not m:
            raise EvalFileError(f"{Path(path).name}: a line isn't of the form 'N. question'")
        out.append(UserQuestion(int(m.group(1)), m.group(2)))
    if [q.number for q in out] != list(range(1, len(out) + 1)):
        raise EvalFileError(f"{Path(path).name}: questions aren't numbered 1..{len(out)} in order")
    return tuple(out)


def load_user_labels(numbers: list[int], path: Path | None = None) -> dict[int, tuple[str, ...] | str] | None:
    """The user's mapping {number: chunk ids or "not_covered"}, or None while it doesn't exist."""
    path = path or USER_LABELS
    if not Path(path).exists():
        return None
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    labels = raw.get("labels", raw)
    out, problems = {}, []
    for n in numbers:
        value = labels.get(str(n))
        if value == NOT_COVERED:
            out[n] = NOT_COVERED
        elif isinstance(value, list) and value and all(isinstance(v, str) for v in value):
            out[n] = tuple(value)
        else:
            problems.append(f"question {n}: expected a list of chunk ids or {NOT_COVERED!r}")
    extra = set(labels) - {str(n) for n in numbers}
    if extra:
        problems.append(f"unknown question numbers: {sorted(extra)}")
    if problems:
        raise EvalFileError(f"{Path(path).name}: " + "; ".join(problems))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--record-hashes", action="store_true", help="write eval/metadata.json (once)")
    group.add_argument("--record-dev-uncovered", action="store_true",
                       help="write eval/metadata_dev_uncovered.json (once)")
    group.add_argument("--check", action="store_true", help="check the question files against it")
    args = parser.parse_args(argv)
    try:
        if args.record_hashes:
            data = record_hashes()
        elif args.record_dev_uncovered:
            data = record_hashes(METADATA_DEV_UNCOVERED, (DEV_UNCOVERED,),
                                 note="Recorded when the file was first used (Unit 2), after the KB existed.")
        else:
            data = check_hashes()
    except EvalFileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for name, entry in data["question_files"].items():
        print(f"{name}: sha256 {entry['sha256']}")
    recorded_now = args.record_hashes or args.record_dev_uncovered
    print("recorded" if recorded_now else "unchanged since recorded", data["recorded_at"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
