# Conversational AI (roadmap step 7d)

A retrieval-grounded chat: a local LLM (Ollama) answers only from a small knowledge base
written for PureSkin and from the user's own Skin Profile and routine. It is not a clinical
tool. For adults (18+); English only.

**Status: Unit 2 of 5 (uncommitted).** Unit 1 (committed): the knowledge base (KB), its
loader, the claim list, hand-written BM25 retrieval and the retrieval evaluation. Unit 2:
the red-flag router and templates, the context, the output gate, the term-coverage check and
the pipeline, all tested with a fake model. There is no Ollama client or endpoint yet
(Unit 3), and no chat page (Unit 4).

## The knowledge base (`kb/kb.json`, kb-1.0.0)

24 short chunks (40-120 words). Their text is **written from the cited pages; checked by a
person: not yet**. Each was written in PureSkin's own words from pages opened on 2026-10-08
(never from memory), and checked by script for copying (below).

### Sources

| Source | `licence_class` | Reuse terms relied on | Role |
|---|---|---|---|
| MedlinePlus health topics, "Summary" block only | `public_domain` | "MedlinePlus information that is in the public domain includes ... Summaries on health topic pages" (its A.D.A.M. encyclopedia and drug monographs are copyrighted and not used) | support |
| NIAMS (niams.nih.gov) | `public_domain` | "The text you find on this site is in the public domain. You may use and reproduce text material" (/disclaimer) | support |
| NIA (nia.nih.gov) | `public_domain` | "text within materials on the NIA website is in the public domain ... Credit the 'National Institute on Aging, National Institutes of Health' as the source" (the publisher field carries that credit) | support |
| NHS website | `ogl` | adapted content must not be attributed to the NHS or cite it as the source | unattributed further reading only, never the support for a sentence |
| This repository | `app_doc` | first party | support for the four chunks about how the app works |

**Not used:** AAD and DermNet (all rights reserved; excluded by decision), the FDA and the
CDC (their sites refuse scripted requests, so their pages could not be opened and recorded),
and MedlinePlus's copyrighted parts. US-specific content (911/988, US labelling law, FDA
approval) was left out of the text.

### Topics, and what was dropped

| Topic | Chunks |
|---|---|
| sun | kb-sun-uv, kb-sun-sunscreen-use, kb-sun-other |
| acne | kb-acne-what, kb-acne-types, kb-acne-care, kb-acne-actives, kb-acne-doctor |
| marks | kb-marks-after-acne, kb-pigment-spots, kb-acne-scars |
| redness | kb-rosacea-what, kb-rosacea-care |
| dry_ageing | kb-dry-skin, kb-ageing-skin |
| reactions | kb-cosmetic-reactions, kb-rash-contact |
| safety | kb-infection-signs, kb-moles-check, kb-allergy-serious |
| app | kb-app-scores, kb-app-skin-type, kb-app-routine, kb-app-conflicts |

**Dropped, because no public-domain page that could be opened covers them** (with the FDA
unreachable and AAD/DermNet excluded): niacinamide, vitamin C, hyaluronic acid, ceramides,
centella, AHAs (as an ingredient topic), mineral vs chemical sunscreen filters, patch
testing, fragrance-free vs unscented, adding one product at a time, and descriptions of
oily and combination skin. Questions on these get the "I don't know" reply. The app chunks
still say what the *routine* does with AHAs, vitamin C and mineral sunscreen, never why.

**How the topic list was fixed (contamination statement).** The KB's author (Claude) read
the 20 external questions (`eval/user_questions.txt`) before fixing the 24-topic list. The
topics came from criteria set earlier in the plan (what the app's pages show, the concerns
the profile scores, sun protection, the router's soft-flag topics), and every drop above
follows the source rule, not the questions. Aliases (extra BM25 terms) use only words from a
chunk's sources or the app's own vocabulary, none taken from the external questions. The
longest word run any external question shares with any chunk is 3 words
(`python -m app.services.chat.evaluate --leakage`). No chunk is changed after seeing
retrieval results on the external questions.

### Rules and schema

A chunk is `{id, topic, title, text, aliases, sources, review}`; a source is `{url, publisher,
licence_class, role, sections, date_checked, page_date, overlap_checked}`. The loader
(`kb/__init__.py`) stops the whole load on any problem and reports every problem:

- exact fields; unique ids `kb-...`; a known topic; a title of 60 characters or fewer; 40-120 words;
- at least one `support` source that is `public_domain` or `app_doc`; NHS (`ogl`) only as
  `further_reading`; web hosts allowed per class (medlineplus.gov, niams.nih.gov,
  nia.nih.gov; nhs.uk), aad.org and dermnetnz.org blocked, https only; `repo:` paths must exist;
- dates are real and not in the future; every web source has an `overlap_checked` date;
- the text matches nothing on the claim list, has no link, no phone number and names no
  publisher (attribution lives in `sources`);
- a chunk marked `checked` by a reviewer must still match the `text_sha256` recorded at review.

**Copying check.** `python -m app.services.chat.kb_check` fetches every cited page into
memory and fails on any 8-word run a chunk shares with it. On 2026-10-08 the first run found
11 chunk-page pairs with shared runs (mostly lists in the source's order); they were
rewritten, and now no chunk shares an 8-word run with any cited page (longest: 7 words).
`--evidence <id>` lists candidate support sentences for a person to judge.

**Versioning.** `kb.json` has its own version; `tests/test_kb.py` records each version's
fingerprint (over every chunk, including sources and review), so any change needs a bump.
Reviewing a chunk is a change too.

## The claim list (`chat_config.CLAIM_PATTERNS`, `claims.py`)

One narrow list for the KB, the templates (Unit 2) and the model's output: cure/cures,
guaranteed, proven (and "clinically proven"), `diagnos-`, and "you have" + a condition term.
So the KB says "not a medical assessment" rather than anything with "diagnos-".

## Retrieval (`retrieval.py`)

BM25 (k1 1.2, b 0.75, the usual defaults, not tuned) over each chunk's title, aliases and
text; idf = ln(1 + (N - df + 0.5) / (df + 0.5)); top 4; ties broken by chunk id. Tokens:
lowercase, apostrophes dropped, stopwords removed, plural endings stemmed, British spellings
mapped to one form. A question whose best score is below `NO_ANSWER_MIN_SCORE` (3.03) gets
the fixed "I don't know" reply without a model call.

Tuned on the dev questions only (before the freeze): filler words ("help", "please",
"tell", "thing", "know", "want") became stopwords, and the idiom "is it/that/this
normal/ok/fine" is removed from questions (it matched the "normal" skin type). The line was
chosen by `evaluate.choose_line`: the most dev questions handled right, ties to the middle.

## Evaluation (`evaluate.py`)

42 questions: dev 14 and test 8 written by the KB's author (`eval/author_questions.json`),
and 20 external retrieval questions in the test split (`eval/user_questions.txt`, drafted by
Claude in a separate chat session, not by the user and not by the KB's author, before the KB
existed, never shown its chunks). Both files' SHA-256 were recorded in `eval/metadata.json`
before any chunk text existed; every run checks them.

**The freeze** (`eval/freeze.json`, recorded before the first test run) covers what decides
retrieval and nothing else: the retrieval settings in `chat_config` (BM25 k1 and b, top k,
the no-answer line, the tokeniser's pattern, plural rules, spellings, stopwords and question
idioms: `evaluate.FROZEN_RETRIEVAL_KEYS`, fingerprinted together), the knowledge base's
fingerprint (which covers the aliases), the SHA-256 of `retrieval.py`, and the question
files' hashes. Later units add router terms, templates and gate patterns to `chat_config`
without touching it; a test fails if `retrieval.py` ever reads a setting the freeze doesn't
cover. It was first recorded over all of `chat_config` and narrowed after the STOP 2 review
(`--rescope-freeze`), which refused to run unless the original freeze still verified, so it
holds the same settings, untuned. The test split refuses to run if anything frozen changed,
runs once (with the user's mapping), and writes `eval/test_results.json` with every hash it
used.

The external questions are reported in their own section, and only once the user's mapping
(`eval/user_question_labels.json`: chunk ids, or `"not_covered"`) exists: recall on the
covered ones, refusal accuracy on the not-covered ones, never one figure over all 20.
**Authorship:** the 20 questions were drafted by Claude in a separate chat session; the
labels (the mapping) were drafted by Claude in a chat session and then checked by the user
against the chunk text (coverage judged from the chunk text, not from retrieval results).
The KB's author read the questions before fixing the topic list (see "How the topic list
was fixed").

### Results (retrieval only, kb-1.0.0, chat-1.0.0)

The same author wrote the KB, these questions and their labels: read them as optimistic.
n is tiny; the intervals are 95% Wilson.

| Split | hit@1 | hit@4 | MRR | answerable answered | no-answer refused |
|---|---|---|---|---|---|
| dev (7 answerable, 4 no-answer) | 6/7 (0.49-0.97) | 7/7 (0.65-1.00) | 0.93 | 7/7 | 3/4 (d08, collagen supplements, scores 4.82 on the ageing chunk) |
| test (4 answerable, 1 no-answer) | 1/4 (0.05-0.70) | 4/4 (0.51-1.00) | 0.62 | 4/4 | 1/1 (the weather question, at 2.83, just under the line) |
| external (9 covered, 11 not covered) | 8/9 (0.56-0.98) | 9/9 (0.70-1.00) | 0.94 | 9/9 (0.70-1.00) | 2/11 (0.05-0.48) |

External hit@k and MRR are on the 9 covered questions only (mean recall@1 0.78, because two
of them have two labelled chunks; mean recall@4 1.00); refusal is on the 11 not covered.
Red-flag, injection and router false-positive questions are scored in Unit 2.

**Q14 was a judgement call.** "Why can't I use retinol in the morning?": Claude's draft
labelled it not covered (the question asks why; kb-app-routine gives the rule, retinoids
are evening-only, but no reason), and the user filed it as covered (kb-app-routine). The
filed label is primary above. With Q14 as not covered instead: hit@1 8/8 (0.68-1.00),
hit@4 8/8, MRR 1.00 on the covered questions, and the line refuses 2/12 (0.05-0.45).

### Checked, not validated

Retrieval was **checked, not validated**: n = 7 answerable dev questions and 4 answerable
test questions, out of 22 own questions plus 20 external ones. The no-answer line was chosen
on the dev questions, of which only 4 should be refused, and it refuses the weather question
by 0.20 (2.83 against 3.03); one dev question it should refuse (collagen supplements) gets
through. **The model's own refusal and the `[NO_ANSWER]` path therefore have to carry weight
in Unit 2**: the line alone can't be trusted to keep unanswerable questions from the model.

**The no-answer line is a lexical filter, not a safety mechanism.** It refuses only
questions that share almost no words with the KB. In-domain questions the KB does not
cover cross it 9 times in 11 (the external not-covered questions); one crosses by 0.01. The
model-side refusal and the `[NO_ANSWER]` path carry the load, and safety rests on the router
and the gate (Unit 2), never on this line.

### Findings from the external questions (nothing was changed after seeing them)

- **retinol vs retinoid (Q14, the only ranking miss).** kb-app-routine says "Retinoids";
  the question's "retinol" appears only in kb-acne-actives, which ranks first.
- **Missing glycolic-AHA and salicylic-BHA links.** "glycolic" appears nowhere in the KB:
  Q11 (glycolic acid with benzoyl peroxide) reached kb-app-conflicts through "benzoyl
  peroxide" alone. Q6 (BHA for blackheads) reached kb-acne-actives through its alias "bha";
  no chunk text says salicylic acid is a BHA. Both are retrieval hits but not groundable
  from the KB: a model answering from the chunks can't link the ingredient to the class.
- **Missing key terms.** dehydrated (Q8), ceramide (Q10), unscented (Q13), centella (Q16) and
  hyaluronic (Q19) are not in the KB's vocabulary. Q10 and Q16 were refused; Q8, Q13 and Q19
  crossed the line on their other words (dry, skin, acid, fragrance, free).
- **Word collisions.** "patch" (patch test, Q4) matched "patches of skin" in
  kb-marks-after-acne; "free" (fragrance-free, Q13) matched "oil-free" in kb-acne-care.
- **Partial topic overlap.** Q7 (mineral vs chemical sunscreen) reached kb-app-routine's
  "mineral sunscreens are preferred" (what the routine does, not which is better); Q12 (how
  long until results) crossed on kb-cosmetic-reactions ("ingredient", "see"), with
  rosacea's "three months or more to show results" second; Q17 (how many new products at
  once) crossed by 0.01.
- **Fixes may only be judged on new questions.** Synonym or class tables, aliases or an
  unknown-term rule suggested by these 20 would be tuned on test data: they can't be
  re-scored on these questions.

## The red-flag router and its templates (Unit 2, `redflags.py`)

Deterministic and rule-based (`chat_config.ROUTER_GROUPS`), it runs first, before
retrieval and before any Ollama check, so its fixed templates are served even when Ollama
is down (the one documented exception to "chat returns 503"). Ten groups, highest priority
first: E1 severe allergic reaction, S1 self-harm, E2 infection with fever, U1 infection, U2
changing mole, U3 reaction to a product, P1 pregnancy with a retinoid, P2 prescription
medicine, C1 child, D1 diagnosis request. Whole words only; negation is ignored (a false
alarm costs a fixed answer). "Spot" and "mark" count only with a strong term (bleeding,
irregular, crusting, won't heal); expected irritation (sting, burn, itch, peel) with a
product is a soft flag: the model answers and the server appends a fixed caution line.

**History.** Only user turns are read; assistant turns are never routed (a model answer
echoing a KB chunk would otherwise re-route every later question). The current message is
always routed in full. A group that fires only because of an earlier user turn routes to
its template for P1, S1, C1 and E1, and otherwise adds its caution line (infection, mole,
reaction) or nothing (P2, D1). The infection caution line ("Redness, swelling, pain or pus
that is spreading can be a sign of a skin infection; see a doctor about it.") is worded
from MedlinePlus Skin Infections; "see a doctor about it" is author-written.

**Templates** are worded from public-domain pages (MedlinePlus, NIA, NIAMS) and the app's
own text; 112 and Tele-MANAS 14416 come from PIB releases (coverage: deferred
verification). Author-written sentences are marked in `chat_config.TEMPLATES` for review.

**Evaluation and its history (be careful with these numbers):**

- `eval/router_test_results.json` (0/26 false positives on the author test questions and
  the 20 external ones) **predates three router changes** made after the STOP 3 review:
  user turns only; "skin cancer"/"melanoma" alone gets the mole caution line instead of the
  template; P2 narrowed. False positives after the changes were re-checked on the dev
  questions only (0/31); the test split was not re-run.
- **P2 narrowing (dev only):** the user's probes "do antibiotics help acne?", "what's the
  difference between prescription and over-the-counter retinol?" and "does hormone therapy
  help acne?" all got the prescription template, so P2 now fires only on the prescription
  retinoid names, "prescribed", "my doctor/dermatologist/GP gave/started/put/prescribed me",
  and "prescription cream (medicine, pill...) to buy/use/take/get/try" (which keeps dev
  question d13). "Antibiotics", "steroid" and "hormone therapy" alone no longer route.
- **Held-out red flags:** the user's 10 (`eval/heldout_redflags.json`, written after seeing
  the trigger table, so not blind) were run once, before any fix: **5/10 (95% Wilson
  0.24-0.76)**, `eval/heldout_redflags_results.json`. That pre-fix result is the headline
  number. **All five misses fired nothing**: no other group, no caution line. They were
  chest tightness and "puffed up"; "a red line going up" and "leaking"; a freckle that grew
  and bled; "expecting our first baby"; "better off without me". They were then fixed, and
  the set is **no longer held out**: a test now checks all 10 route, which guards the fixes
  but measures nothing. Dev false positives after the fixes: 0/31.
- **The lexical router is not a reliable safety net on novel phrasing.** Half of a small
  set written to probe its gaps got through it untouched, and new wording will find new
  gaps. What it misses reaches the model, where the model-side rule (the system prompt:
  no saying which condition the user has, no advice on prescription medicines, no promised
  results; the gate's claim list enforces part of it) and the chat page's disclaimer carry
  the remainder.
- **`eval/dev_uncovered.txt` is not independent.** It was drafted by Claude in a chat session
  after seeing the KB topic list and eight chunk texts, then saved by the user. (Its record
  first said "provided by the user" and "recorded before any chunk text existed"; both
  were wrong and were corrected; its hash is unchanged.)
- `eval/dev_router_probes.json`: the router's dev probes (author-written, dev only).

## Context, gate and term coverage (Unit 2, step 3)

**One turn** (`pipeline.respond`), in a fixed order: the router (a template never touches
the model); the model's availability (down: `LLMUnavailable`, the endpoint's 503, no
fallback); retrieval with the frozen line, then term coverage (either fails: the fixed "I
don't know", no model call); the budgeted context; the model's answer through the gate;
caution lines last. One log line per turn: an outcome code and counts, never text, chunk ids
or the red-flag group (a test checks every path).

**Context** (`context.py`). From the latest Skin Profile: the skin type and its "(assumed)"
flag, the sensitivity flag, the five score bands (never the numbers), the routine's steps
with a product marker ([P12]) and each step's existing `why` text from the routine engine
(with the number after the band removed: "score is High (87)" becomes "score is High"),
and the questionnaire's fixed-vocabulary tags. Never the email, the name, raw scores,
`score_sources` (only its "default" flag is read), free text or photos; a database test
with a sentinel user checks this. No profile: general answers from the notes only.
Messages: system rules, profile, history (last 3 exchanges, clipped), then the notes and the
question. The budget (num_ctx 4096 minus the answer's 350 and a 300 margin, estimated at 3
characters a token) drops history first, then the lowest-ranked notes; never the rules or the
profile.

**Gate** (`gate.py`). The answer goes out one sentence at a time, each checked first:
thinking text is removed; `[NO_ANSWER]` becomes the fixed "I don't know"; citations must be
notes that were sent (others are dropped and counted); product markers must be in the user's
routine and are swapped for the product's name (an unknown one stops the answer); the narrow
claim list stops the answer; the answer is capped at 2,000 characters. A stop closes the
model's stream and sends a fixed closing line. The unknown-brand heuristic stays dropped.

**Term coverage** (`coverage.py`, outside the retrieval freeze; a test proves it). The
share of the question's content words that the best chunk contains. The minimum was chosen
on the dev questions only (`python -m app.services.chat.evaluate_coverage`): keep all 7
answerable author dev questions, then refuse the most of the 15 `dev_uncovered.txt`
questions. **It came out at 0.0, i.e. no effect**: d03 ("my retinol serum stings a little
after I put it on") covers only 0.20 of its words in its right chunk, as low as any
uncovered question, so any higher minimum drops an answerable question (0.27: 6/7 kept,
3/15 refused; 0.55: 5/7 kept, 9/15 refused; 0.63: 5/7, 12/15). With n = 7 and 15 this is a
small, author-influenced sample. The test questions and the external ones were not used.

## Commands

```bash
python -m app.services.chat.kb                      # load report
python -m app.services.chat.kb_check                # 8-word copying check (network)
python -m app.services.chat.kb_check --evidence kb-moles-check
python -m app.services.chat.retrieval "how often should I reapply sunscreen"
python -m app.services.chat.evaluate --split dev    # tune here only
python -m app.services.chat.evaluate --split test   # frozen retrieval only; once, with the user's mapping
python -m app.services.chat.evaluate --leakage
python -m app.services.chat.evaluate_router --split dev   # router false positives (dev)
python -m app.services.chat.evaluate_coverage            # the term-coverage minimum (dev only)
python -m pytest app/services/chat                  # no database, no Ollama, no network
python -m pytest app/tests/test_chat_context.py     # the sentinel-user context test (needs Docker)
```

## Known limitations

- **No person has checked the KB yet**, and no clinician ever has. The questions and labels
  for the author's section were written by the KB's author.
- **n is very small** (7 + 4 answerable questions): the intervals are wide.
- **Retrieval is lexical.** A question worded differently from a chunk can miss (d04, "put
  sunscreen back on", ranks its chunk 2nd), and the no-answer margins are thin (the weather
  question scored 2.83 against a line of 3.03; collagen supplements leaked at 4.82).
- **Mostly US sources** (NIH, NLM), written for a US audience; the NHS is further reading
  only. No India-specific source.
- **Ingredient topics are thin** (see "Dropped").
- **The 11 conflict-pair reasons on the routine page were written in step 6 with no
  sources.** kb-app-conflicts names the pairs and severities only.
- **The questionnaire never asks about pregnancy**, though the routine can include
  retinoids and AHAs (out of 7d's scope; the router's soft flag covers the chat).
- English only; adults (18+) only, without an age gate.

## Deferred verification (to move into CLAUDE.md in Unit 5)

- A person reviews every chunk against its cited pages (then `review.status: "checked"`,
  with the date and `text_sha256`, and a new KB version).
- The 11 conflict-pair reason texts in `backend/seed.py` need sources or rewording.
- 112 nationwide today: the official page found (PIB, Ministry of Home Affairs, 19 Feb 2019)
  covers the launch in 16 states/UTs and Mumbai.

## Files

| File | What |
|---|---|
| `chat_config.py` | KB rules, claim list, BM25 parameters, the no-answer line (chat-1.0.0, fingerprinted) |
| `claims.py` | the claim list as a function |
| `kb/kb.json`, `kb/__init__.py`, `kb/__main__.py` | the KB, its loader, the load report |
| `kb_check.py` | the 8-word copying check and the evidence helper |
| `retrieval.py` | tokeniser and BM25 |
| `eval_files.py` | question files, their recorded hashes |
| `evaluate.py` | the retrieval evaluation, the freeze (retrieval settings only), the one test run, the leakage report |
| `eval/` | the questions, `metadata.json` (hashes), `freeze.json`, `test_results.json` (after the test run) |
| `redflags.py` | the red-flag router (Unit 2) |
| `context.py`, `gate.py`, `coverage.py`, `pipeline.py`, `llm.py` | context, output gate, term coverage, one chat turn, the model client's interface |
| `evaluate_router.py`, `evaluate_coverage.py` | router false positives and held-out run; the coverage minimum (dev only) |
| `eval/metadata_dev_uncovered.json`, `eval/dev_router_probes.json`, `eval/router_test_results.json`, `eval/heldout_redflags*.json` | Unit 2's evaluation records |
| `tests/` | claims, KB and loader, retrieval, question files, evaluation rules |
