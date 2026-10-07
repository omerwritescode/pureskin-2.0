"""Build an AM/PM routine from a Skin Profile, the catalog and the conflict table.

Pure: no database, no FastAPI. app/api/routine.py loads the rows and calls build_routine().

1. rules.build_requirements(): the profile -> requirements (category + keywords).
2. Each requirement takes the first eligible product in rule order (keyword order, then
   product id). A product the profile's hard rules exclude is skipped, and the reason is
   recorded (Routine.left_out). Nothing is invented: a requirement no eligible product
   meets is skipped with a warning.
3. Every pair of products in the same session is checked against the conflict table,
   and the optional one (serum/treatment/exfoliant) is dropped when they clash.

The user's current products and avoid list (profile.questionnaire_tags, 7c-i c) add hard
rules; NULL tags mean no information, and the routine is then exactly as without them.
"""

import random
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from app.core.utils import normalize_ingredient_pair
from app.services.ingredients import (
    CLASS_PREFIX,
    NormalisedIngredients,
    canonical,
    memberships,
    normalise_ingredients,
)
from app.services.ingredients.ingredient_config import FRAGRANCE_CLASSES
from app.services.ingredients.normalise import TOKEN_CLASSES

from . import recommendation_config as rcfg
from . import routine_config as cfg
from .matching import keyword_matches
from .ranker import Scored, Scorer
from .rules import Requirement, base_set, build_requirements, requirement

FALLBACK = "fallback"  # the source of a core step's last-resort "any eligible product"


@dataclass(frozen=True)
class ProductRecord:
    id: int
    name: str
    category: str | None
    ingredients: NormalisedIngredients
    texture: str | None = None
    foaming: str | None = None
    spf: int | None = None


def product_record(id: int, name: str, category: str | None, ingredients: Iterable[str],
                   texture: str | None = None, foaming: str | None = None,
                   spf: int | None = None) -> ProductRecord:
    return ProductRecord(id, name, category, normalise_ingredients(ingredients), texture, foaming, spf)


@dataclass(frozen=True)
class Conflict:
    severity: str
    reason: str | None
    pair: tuple[str, str] = ("", "")  # its conflict-table key


ConflictTable = Mapping[tuple[str, str], Conflict]


def _conflict_key(name: str) -> str:
    return name if name.startswith(CLASS_PREFIX) else canonical(name)


def conflict_table(rows: Iterable[tuple[str, str, str, str | None]]) -> dict[tuple[str, str], Conflict]:
    """(ingredient_a, ingredient_b, severity, reason) rows, keyed by their canonical pair.

    A name is an ingredient token or a whole class ("class:retinoid"). The seed loader
    rejects unknown names; here an unknown one simply never matches.
    """
    table = {}
    for a, b, severity, reason in rows:
        pair = normalize_ingredient_pair(_conflict_key(a), _conflict_key(b))
        table[pair] = Conflict(severity, reason, pair)
    return table


@dataclass(frozen=True)
class RankOptions:
    """How a step orders its eligible products.

    RANKED (the default): keyword tier, then a strong active outside its step last, then
    conflict-safe first, then score, then rule order; steps choose in concern-priority
    order. RULE_ORDER reproduces 7c-i exactly (the evaluation baseline). A random seed
    picks uniformly from the eligible set (baseline). The other switches exist for the
    evaluation's ablations.
    """

    use_scores: bool = True
    conflict_safe: bool = True
    priority_order: bool = True
    strong_last: bool = True
    random_seed: int | None = None


RANKED = RankOptions()
RULE_ORDER = RankOptions(use_scores=False, conflict_safe=False, priority_order=False, strong_last=False)


def random_order(seed: int) -> RankOptions:
    return RankOptions(use_scores=False, conflict_safe=False, priority_order=False, strong_last=False,
                       random_seed=seed)


@dataclass(frozen=True)
class Ranked:
    """An eligible product for a step, with what ordered it."""

    product: "ProductRecord"
    keyword: str | None
    tier: int  # which keyword alternative it met (earlier = preferred)
    position: int  # rule order: keyword order, then product id
    scored: Scored | None  # None outside RANKED mode
    clashes_with: str | None  # an earlier pick in this session it clashes with
    strong_outside_its_step: bool = False  # has a strong active the step doesn't target

    @property
    def score(self) -> float:
        return self.scored.score if self.scored else 0.0


@dataclass(frozen=True)
class Ranking:
    ranked: tuple[Ranked, ...]  # every eligible product, best first (a permutation)
    rule_order: tuple[Ranked, ...]  # the same products in rule order

    @property
    def rule_order_pick(self) -> Ranked:
        return self.rule_order[0]


@dataclass
class Step:
    req: Requirement
    product: ProductRecord
    matched_keyword: str | None
    removed: bool = field(default=False)
    ranking: Ranking | None = None
    alternatives: tuple[Ranked, ...] = ()

    @property
    def caution(self) -> str | None:
        """A fixed caution on any step whose product lists a retinoid (strict: any trace)."""
        retinoid = memberships(self.product.ingredients, strict=True).of("retinoid")
        return cfg.RETINOID_CAUTION if retinoid else None


@dataclass(frozen=True)
class LeftOut:
    """A product the rules would have used, and why it isn't in the routine."""

    product_id: int
    product_name: str
    sessions: tuple[str, ...]
    reason: str
    code: str = ""  # which rule left it out (an Exclusion code)
    severity: str | None = None  # for a conflict


@dataclass(frozen=True)
class Unfilled:
    """A requirement no eligible product met (its warning says so). For the evaluation."""

    session: str
    req: Requirement
    excluded: bool  # a product met it, but a hard rule left it out
    fell_back: bool  # a core step: the next level of its chain was tried
    codes: tuple[str, ...] = ()  # the Exclusion codes of the products that met it (sorted)


@dataclass
class Routine:
    base_set: str
    am: list[Step]
    pm: list[Step]
    warnings: list[str]
    left_out: list[LeftOut]
    current_products_considered: bool = False  # False when the profile has no tags
    unfilled: list[Unfilled] = field(default_factory=list)


# ======================================================================================
# The user's current products and avoid list (questionnaire_tags)
# ======================================================================================


@dataclass(frozen=True)
class InUse:
    """Something the user already uses, as conflict keys (a token and its classes, or a
    class), and how the routine refers to it ("a prescription retinoid")."""

    name: str
    keys: frozenset[str]
    classes: frozenset[str]


@dataclass(frozen=True)
class CurrentUse:
    actives: tuple[InUse, ...]
    skip_categories: tuple[tuple[str, str], ...]  # (category, what the user uses)
    avoid: tuple[str, ...]  # avoid-list tags
    prescription_retinoid: bool


def _in_use(key: str, name: str) -> InUse:
    if key.startswith(CLASS_PREFIX):
        classes = frozenset({key.removeprefix(CLASS_PREFIX)})
    else:
        classes = frozenset(TOKEN_CLASSES.get(key, ()))
    return InUse(name, frozenset({key, *(CLASS_PREFIX + c for c in classes)}), classes)


def current_use(profile) -> CurrentUse | None:
    """The profile's questionnaire tags as rules (None: no tags, no information)."""
    tags = getattr(profile, "questionnaire_tags", None)
    if tags is None:
        return None
    actives = [
        _in_use(cfg.IN_USE_TAGS.get(tag, tag), cfg.IN_USE_NAMES.get(tag, tag))
        for tag in tags.get("actives_in_use", ())
    ]
    products = tags.get("products_in_use", ())
    actives += [
        _in_use(cfg.IN_USE_PRODUCT_TYPES[ptype], cfg.IN_USE_NAMES[ptype])
        for ptype in products if ptype in cfg.IN_USE_PRODUCT_TYPES
    ]
    return CurrentUse(
        actives=tuple(actives),
        skip_categories=tuple(
            (cfg.IN_USE_SKIP_CATEGORIES[ptype], cfg.IN_USE_NAMES[ptype])
            for ptype in products if ptype in cfg.IN_USE_SKIP_CATEGORIES
        ),
        avoid=tuple(tags.get("avoid", ())),
        prescription_retinoid=cfg.PRESCRIPTION_RETINOID in tags.get("actives_in_use", ()),
    )


# ======================================================================================
# Hard rules: a product the profile can't be given, whatever the step
# ======================================================================================


UNKNOWN, STRONG_ACTIVE, EXCLUDED_INGREDIENT, FRAGRANCE, SESSION = (
    "unknown_ingredients", "strong_active", "excluded_ingredient", "fragrance", "session",
)
AVOID, DUPLICATE, EXISTING_CONFLICT, CONFLICT = "avoid", "duplicate", "existing_conflict", "conflict"
# The sensitive-skin hard rules a substitution can stand in for.
SENSITIVE_HARD_RULES = (STRONG_ACTIVE, EXCLUDED_INGREDIENT)


@dataclass(frozen=True)
class Exclusion:
    code: str
    reason: str  # shown to the user; a SESSION reason is worded once the routine is known
    token: str | None = None  # SESSION: the ingredient and its class
    cls: str | None = None
    severity: str | None = None  # a conflict's severity


def session_reason(exclusion_: Exclusion, session: str, placed_elsewhere: bool) -> str:
    """The reason for a session-rule exclusion, once we know whether the product is
    in the routine in another session ("not used in the morning routine") or not at all
    ("left out")."""
    singular, plural = cfg.SHORT_CLASS_NAMES[exclusion_.cls]
    where = cfg.SESSION_NAMES[session]
    if placed_elsewhere:
        allowed = "/".join(
            cfg.SESSION_NAMES[s] for rule_cls, sessions, _ in cfg.SESSION_RULES
            if rule_cls == exclusion_.cls for s in sessions
        )
        return (f"Not used in the {where} routine because it contains {exclusion_.token} "
                f"({singular}); {plural} are {allowed}-only.")
    return (f"Left out because it contains {exclusion_.token} ({singular}), and {plural} "
            f"are not used in the {where} routine.")


def contains(token: str, cls: str) -> str:
    """'It contains lactic acid, an alpha hydroxy acid (AHA).'"""
    label = cfg.CLASS_LABELS.get(cls)
    return f"It contains {token}, {label}." if label else f"It contains {token}."


def _named(items: NormalisedIngredients, key: str, *, strict: bool) -> str | None:
    """The first ingredient of `items` that `key` (a token or "class:<name>") names."""
    if key.startswith(CLASS_PREFIX):
        members = memberships(items, strict=strict).of(key.removeprefix(CLASS_PREFIX))
        return members[0].token if members else None
    return key if key in items.tokens else None


def most_severe(found: Iterable[Conflict]) -> Conflict | None:
    return min(found, key=lambda c: cfg.SEVERITY_ORDER.index(c.severity), default=None)


def current_use_exclusion(
    current: CurrentUse, product: ProductRecord, conflicts: ConflictTable
) -> Exclusion | None:
    """The avoid list (strict), duplicates of a family already in use, and high or medium
    conflicts with an active already in use (it counts as present in both sessions). A
    low one is not an exclusion: see existing_low_conflict_notes()."""
    for tag in current.avoid:
        for key in cfg.AVOID.get(tag, ()):
            token = _named(product.ingredients, key, strict=True)
            if token is not None:
                return Exclusion(AVOID, f"You asked to avoid {cfg.AVOID_NAMES.get(tag, tag)}, and it lists {token}.")
    found = memberships(product.ingredients, strict=False)
    for in_use in current.actives:
        for cls in cfg.DUPLICATE_CLASSES:
            members = found.of(cls)
            if cls in in_use.classes and members:
                singular, _ = cfg.SHORT_CLASS_NAMES[cls]
                return Exclusion(DUPLICATE, (
                    f"It contains {members[0].token} ({singular}), and you already use {in_use.name}."
                ))
    hard = [c for c in existing_clashes(current, product, conflicts)
            if c[0].severity in cfg.EXISTING_CONFLICT_HARD_SEVERITIES]
    if hard:
        conflict, in_use = min(hard, key=lambda c: cfg.SEVERITY_ORDER.index(c[0].severity))
        return Exclusion(EXISTING_CONFLICT, (
            f"It clashes with {in_use.name}, which you already use: {conflict.reason}"
        ), severity=conflict.severity)
    return None


def existing_clashes(
    current: CurrentUse, product: ProductRecord, conflicts: ConflictTable
) -> list[tuple[Conflict, InUse]]:
    """Every conflict between the product and an active the user already uses."""
    product_keys = conflict_keys(product)
    clashes = []
    for in_use in current.actives:
        for key_a in product_keys:
            for key_b in sorted(in_use.keys):
                if key_a == key_b:
                    continue
                conflict = conflicts.get(normalize_ingredient_pair(key_a, key_b))
                if conflict is not None:
                    clashes.append((conflict, in_use))
    return clashes


def existing_low_conflict_notes(plan: "_Plan", steps: list["Step"]) -> None:
    """A note for each kept product with only a low-severity clash with an active in use
    (a medium or high one would have left it out)."""
    if plan.current is None:
        return
    for step in kept_in_order(steps):
        for conflict, in_use in existing_clashes(plan.current, step.product, plan.conflicts):
            if conflict.severity not in cfg.EXISTING_CONFLICT_HARD_SEVERITIES:
                plan.warnings.append(cfg.EXISTING_LOW_CONFLICT_NOTE.format(
                    active=in_use.name, product=step.product.name, clause=low_conflict_clause(conflict),
                ))


def low_conflict_clause(conflict: Conflict) -> str:
    """The pair's clause for the low-severity note (its reason, read as a clause)."""
    clause = cfg.EXISTING_LOW_CONFLICT_CLAUSES.get(conflict.pair)
    if clause is not None:
        return clause
    reason = conflict.reason or ""
    if len(reason) > 1 and reason[1].islower():  # "The …" -> "the …"; "AHAs …" stays
        reason = reason[0].lower() + reason[1:]
    return reason


def exclusion(profile, product: ProductRecord, session: str,
              current: CurrentUse | None = None, conflicts: ConflictTable | None = None) -> Exclusion | None:
    """Why this product can't be used for this profile in this session (None: it can)."""
    if not product.ingredients.fully_known:  # fail closed: it can't be checked
        return Exclusion(UNKNOWN, (
            "Its ingredient list has names we haven't reviewed yet, so it can't be checked."
        ))
    found = memberships(product.ingredients, strict=False)
    if profile.is_sensitive:
        for cls in cfg.SENSITIVE_STRONG_CLASSES:
            members = found.of(cls)
            if members:
                return Exclusion(STRONG_ACTIVE, (
                    f"{contains(members[0].token, cls)} Strong actives are left out for sensitive skin."
                ))
        for token in cfg.SENSITIVE_EXCLUDED_INGREDIENTS:
            if token in product.ingredients.tokens:
                return Exclusion(EXCLUDED_INGREDIENT, (
                    f"It contains {token}, which is left out for sensitive skin."
                ))
        if cfg.SENSITIVE_FRAGRANCE_FREE:
            found_strict = memberships(product.ingredients, strict=True)
            for cls in FRAGRANCE_CLASSES:  # the order fragrance_tokens() uses
                members = found_strict.of(cls)
                if members:
                    return Exclusion(FRAGRANCE, cfg.SENSITIVE_FRAGRANCE_REASONS[cls].format(token=members[0].token))
    if current is not None:
        excluded_by = current_use_exclusion(current, product, conflicts or {})
        if excluded_by is not None:
            return excluded_by
    for cls, sessions, rinse_off_too in cfg.SESSION_RULES:
        members = found.of(cls)
        if session not in sessions and members and (
            rinse_off_too or product.category not in cfg.RINSE_OFF_CATEGORIES
        ):
            return Exclusion(SESSION, "", members[0].token, cls)
    return None


@dataclass
class _LeftOutEntry:
    product: ProductRecord
    sessions: list[str]
    reason: str  # "" while a SESSION reason waits for the finished routine
    pending: Exclusion | None = None
    code: str = ""
    severity: str | None = None


@dataclass
class _Plan:
    """What planning one routine collects as it goes."""

    profile: object
    products: list[ProductRecord]
    conflicts: ConflictTable = field(default_factory=dict)
    current: CurrentUse | None = None
    options: RankOptions = RANKED
    scorer: Scorer | None = None
    warnings: list[str] = field(default_factory=list)
    unfilled: list[Unfilled] = field(default_factory=list)
    left_out: list[_LeftOutEntry] = field(default_factory=list)  # in the order they happened
    _index: dict[tuple, _LeftOutEntry] = field(default_factory=dict)

    def exclusion(self, product: ProductRecord, session: str) -> Exclusion | None:
        return exclusion(self.profile, product, session, self.current, self.conflicts)

    def leave_out(self, product: ProductRecord, session: str, excluded_by: Exclusion) -> None:
        """Record a product the rules would have used, with why (merged per product+reason)."""
        if excluded_by.code == SESSION:
            key, reason, pending = (product.id, SESSION, excluded_by.cls, excluded_by.token), "", excluded_by
        else:
            key, reason, pending = (product.id, excluded_by.reason), excluded_by.reason, None
        entry = self._index.get(key)
        if entry is None:
            entry = self._index[key] = _LeftOutEntry(
                product, [], reason, pending, excluded_by.code, excluded_by.severity
            )
            self.left_out.append(entry)
        if session not in entry.sessions:
            entry.sessions.append(session)

    def finish_left_out(self, kept: dict[str, set[int]]) -> list[LeftOut]:
        """Word the pending session reasons now that the routine is known, then return
        the entries in order (an entry whose reason matches an earlier one for the same
        product is merged into it)."""
        out: dict[tuple[int, str], LeftOut] = {}
        for entry in self.left_out:
            reason = entry.reason
            if entry.pending is not None:
                placed = any(
                    entry.product.id in kept[s] for s in (cfg.AM, cfg.PM) if s not in entry.sessions
                )
                reason = session_reason(entry.pending, entry.sessions[0], placed)
            key = (entry.product.id, reason)
            sessions = tuple(entry.sessions)
            if key in out:
                sessions = tuple(dict.fromkeys(out[key].sessions + sessions))
            out[key] = LeftOut(
                entry.product.id, entry.product.name, sessions, reason, entry.code, entry.severity
            )
        return list(out.values())


def candidates(products: list[ProductRecord], req: Requirement) -> list[tuple[ProductRecord, str | None]]:
    """Products meeting the requirement, in rule order: keyword order, then product id."""
    in_category = [p for p in products if p.category == req.category]
    if not req.keywords:
        return [(p, None) for p in in_category]
    ordered, seen = [], set()
    for keyword in req.keywords:
        for product in in_category:
            if product.id not in seen and keyword_matches(product, keyword):
                ordered.append((product, keyword))
                seen.add(product.id)
    return ordered


def step_targets_strong(req: Requirement) -> bool:
    """Does the step itself look for a strong active (e.g. salicylic acid, retinol, bha)?"""
    for keyword in req.keywords:
        for kind, value in cfg.MATCHERS[keyword]:
            classes = {value} if kind == "class" else set(TOKEN_CLASSES.get(value, ())) if kind == "ingredient" else set()
            if classes & set(rcfg.STRONG_CLASSES):
                return True
    return False


@dataclass
class _SlotLog:
    """What one step recorded; replayed in the steps' rule order, whatever order they chose in."""

    warnings: list[str] = field(default_factory=list)
    left_out: list[tuple[ProductRecord, str, Exclusion]] = field(default_factory=list)
    unfilled: list[Unfilled] = field(default_factory=list)


def choose(
    plan: _Plan, log: _SlotLog, req: Requirement, session: str,
    chosen_ids: set[int], earlier: list[ProductRecord],
) -> tuple[Ranking | None, tuple[str, ...]]:
    """Every eligible product for the requirement, ordered (None if there is none), and
    the Exclusion codes of the products a hard rule skipped (empty: none was skipped).

    Hard rules decide eligibility; the order never adds or removes a product. Skipped
    products ahead of the first eligible one in rule order are recorded (as in 7c-i).
    """
    eligible = []
    codes: set[str] = set()
    for position, (product, keyword) in enumerate(candidates(plan.products, req)):
        if product.id in chosen_ids:  # already in this session's routine
            continue
        excluded_by = plan.exclusion(product, session)
        if excluded_by is not None:
            codes.add(excluded_by.code)
            if not eligible:
                log.left_out.append((product, session, excluded_by))
            continue
        tier = req.keywords.index(keyword) if keyword is not None else 0
        eligible.append((product, keyword, tier, position))
    if not eligible:
        return None, tuple(sorted(codes))

    options = plan.options
    targets_strong = step_targets_strong(req)
    ranked = []
    for product, keyword, tier, position in eligible:
        scored = plan.scorer.score(product) if options.use_scores and plan.scorer else None
        clash = None
        if options.conflict_safe:
            clash = next((e.name for e in earlier if find_conflict(product, e, plan.conflicts)), None)
        strong = options.strong_last and not targets_strong and bool(
            memberships(product.ingredients, strict=False).classes & set(rcfg.STRONG_CLASSES))
        ranked.append(Ranked(product, keyword, tier, position, scored, clash, strong))
    rule_order = tuple(sorted(ranked, key=lambda r: r.position))
    if options.random_seed is not None:
        order = list(rule_order)
        random.Random(f"{options.random_seed}|{session}|{req.category}|{req.keywords}|{req.source}").shuffle(order)
    elif options.use_scores:
        # Keyword tier, strong active outside its step last, clashing with an earlier pick
        # last, then score (rounded), then rule order.
        order = sorted(ranked, key=lambda r: (
            r.tier, r.strong_outside_its_step, r.clashes_with is not None, -r.score, r.position))
    else:
        order = list(rule_order)
    return Ranking(tuple(order), rule_order), tuple(sorted(codes))


def _not_found(req: Requirement, excluded: bool, fallback: bool) -> str:
    then = " — using a standard one instead" if fallback else ""
    if excluded:
        return f"No suitable {req.describe()} for this step{then}"
    return f"No {req.describe()} found in the catalog for this step{then}"


def plan_session(plan: _Plan, session: str, reqs: list[Requirement]) -> list[Step]:
    session_reqs = [r for r in reqs if session in r.sessions]

    # A core category holds one product per session: a later (score-based) requirement
    # replaces the base one, which stays as a fallback; the last fallback is any eligible
    # product in the category. Every hard rule applies at every level, so a core step
    # stays empty (with a warning) only when no product in its category is eligible.
    core_choice: dict[str, list[Requirement]] = {}
    optional: list[Requirement] = []
    for req in session_reqs:
        if req.category in cfg.CORE_CATEGORIES:
            core_choice.setdefault(req.category, []).insert(0, req)
        else:
            optional.append(req)
    for category, chain in core_choice.items():
        if all(req.keywords for req in chain):
            chain.append(Requirement(category, (), (session,), None, FALLBACK))

    # Slots in rule order: the core categories, then the optional steps.
    slots = [(chain, True) for chain in core_choice.values()] + [([req], False) for req in optional]
    # The order slots choose in: in RANKED mode by concern priority (score-triggered steps
    # first, in CONCERN_PRIORITY order, then sensitive, base and fallback steps), each
    # choice seeing the earlier picks; ties keep rule order. RULE_ORDER keeps 7c-i's order.
    order = list(range(len(slots)))
    if plan.options.priority_order:
        order.sort(key=lambda i: (min(r.priority for r in slots[i][0]), i))

    logs = [_SlotLog() for _ in slots]
    picks: dict[int, Step] = {}
    chosen_ids: set[int] = set()
    earlier: list[ProductRecord] = []
    for i in order:
        chain, core = slots[i]
        for level, req in enumerate(chain):
            ranking, codes = choose(plan, logs[i], req, session, chosen_ids, earlier)
            if ranking is not None:
                best = ranking.ranked[0]
                picks[i] = Step(req, best.product, best.keyword, ranking=ranking)
                chosen_ids.add(best.product.id)
                earlier.append(best.product)
                break
            fell_back = core and level < len(chain) - 1
            logs[i].warnings.append(_not_found(req, bool(codes), fallback=fell_back))
            logs[i].unfilled.append(Unfilled(session, req, bool(codes), fell_back, codes))
    for log in logs:
        for product, where, excluded_by in log.left_out:
            plan.leave_out(product, where, excluded_by)
        plan.warnings.extend(log.warnings)
        plan.unfilled.extend(log.unfilled)
    return [picks[i] for i in sorted(picks)]


def set_alternatives(plan: _Plan, steps: list[Step]) -> None:
    """Up to MAX_ALTERNATIVES per kept step: the next products in its ranking that aren't
    already in this session and wouldn't clash with any other kept product if swapped in."""
    if not plan.options.use_scores:
        return
    kept = [s for s in steps if not s.removed]
    for step in kept:
        if step.ranking is None:
            continue
        others = [s.product for s in kept if s is not step]
        used = {p.id for p in others} | {step.product.id}
        alternatives = []
        for r in step.ranking.ranked:
            if r.product.id in used or any(find_conflict(r.product, o, plan.conflicts) for o in others):
                continue
            alternatives.append(r)
            if len(alternatives) == rcfg.MAX_ALTERNATIVES:
                break
        step.alternatives = tuple(alternatives)


# ======================================================================================
# Conflicts
# ======================================================================================


def conflict_keys(product: ProductRecord) -> list[str]:
    """What a conflict row can name in this product: its ingredients, then its classes.

    Class membership applies the preservative cutoff (a trace of lactic acid after the
    preservative doesn't make a product an AHA).
    """
    classes = memberships(product.ingredients, strict=False).classes
    return [*product.ingredients.tokens, *(CLASS_PREFIX + c for c in sorted(classes))]


def find_conflict(a: ProductRecord, b: ProductRecord, conflicts: ConflictTable) -> Conflict | None:
    """The most severe conflict between two products (the first found among equals)."""
    found = []
    for key_a in conflict_keys(a):
        for key_b in conflict_keys(b):
            if key_a == key_b:  # the same ingredient (or class) in both: not a conflict
                continue
            conflict = conflicts.get(normalize_ingredient_pair(key_a, key_b))
            if conflict is not None:
                found.append(conflict)
    return most_severe(found)


def resolve_conflicts(plan: _Plan, steps: list[Step], conflicts: ConflictTable, session: str) -> None:
    """Drop optional products that clash with another product in the same session.

    A core product always stays. When two optional products clash, the one with the
    lower concern priority goes (routine_config.CONCERN_PRIORITY; base steps rank last);
    on a tie, the later-required one goes. Every dropped product is recorded with the
    product it clashed with and why.
    """
    for i, a in enumerate(steps):
        for b in steps[i + 1:]:
            if a.removed or b.removed:
                continue
            conflict = find_conflict(a.product, b.product, conflicts)
            if conflict is None:
                continue
            a_core = a.req.category in cfg.CORE_CATEGORIES
            b_core = b.req.category in cfg.CORE_CATEGORIES
            if a_core and b_core:
                plan.warnings.append(f"{a.product.name} + {b.product.name}: {conflict.reason}")
                continue
            if a_core or b_core:
                loser, winner = (b, a) if a_core else (a, b)
            else:
                loser, winner = (a, b) if a.req.priority > b.req.priority else (b, a)
            loser.removed = True
            plan.leave_out(loser.product, session, Exclusion(
                CONFLICT, f"It clashes with {winner.product.name}: {conflict.reason}",
                severity=conflict.severity,
            ))


def kept_in_order(steps: list[Step]) -> list[Step]:
    """The steps that stay, in application order (stable: keeps priority within a category)."""
    kept = [s for s in steps if not s.removed]
    kept.sort(key=lambda s: cfg.CATEGORY_ORDER.index(s.req.category))
    return kept


def sensitive_substitutions(plan: _Plan, reqs: list[Requirement]) -> list[Requirement]:
    """Replace or drop steps for sensitive skin (routine_config.SENSITIVE_SUBSTITUTIONS).

    An "always" entry applies to every sensitive profile. An "all_excluded" entry applies
    only when the catalog has products for the step and every one of them is left out by
    a sensitive-skin hard rule; a "no_eligible" entry also applies when the catalog has
    none. Each applied entry adds its warning, and the step's
    products that a hard rule excludes are listed with their reasons. A replacement keeps
    the original step's concern priority, and isn't added twice (e.g. when redness is
    High too, the azelaic acid step is already there).
    """
    if not plan.profile.is_sensitive:
        return reqs
    out: list[Requirement] = []
    for req in reqs:
        substitution = cfg.SENSITIVE_SUBSTITUTIONS.get((req.source, req.category, req.keywords))
        if substitution is None:
            out.append(req)
            continue
        replacement, warning, when = substitution
        found = candidates(plan.products, req)
        exclusions = [plan.exclusion(product, req.sessions[0]) for product, _ in found]
        hard = [e is not None and e.code in SENSITIVE_HARD_RULES for e in exclusions]
        if when == cfg.ALL_EXCLUDED and not (found and all(hard)):
            out.append(req)
            continue
        if when == cfg.NO_ELIGIBLE and not all(hard):  # all([]) is True: none in the catalog
            out.append(req)
            continue
        plan.warnings.append(warning)
        for (product, _), excluded_by, is_hard in zip(found, exclusions, hard):
            if is_hard:
                for session in req.sessions:
                    plan.leave_out(product, session, excluded_by)
        if replacement is not None:
            new = requirement(replacement, req.source, replaces=req.keywords)
            if new not in reqs and new not in out:
                out.append(new)
    return out


def _covers(in_use: InUse, kind: str, value: str) -> bool:
    """Does something the user already uses cover a keyword's target active?"""
    if kind == "class":
        return value in in_use.classes
    shared = set(TOKEN_CLASSES.get(value, ())) & set(cfg.DUPLICATE_CLASSES) & in_use.classes
    return value in in_use.keys or bool(shared)


def current_use_duplicates(plan: _Plan, reqs: list[Requirement]) -> list[Requirement]:
    """Leave out the steps whose active the user already uses (with a note), and the
    steps of a category they already use (a ticked exfoliant)."""
    current = plan.current
    if current is None:
        return reqs
    out = []
    for req in reqs:
        covered_by = next((name for category, name in current.skip_categories if category == req.category), None)
        targets = [
            [(kind, value) for kind, value in cfg.MATCHERS[keyword] if kind in ("ingredient", "class")]
            for keyword in req.keywords
        ]
        if covered_by is None and req.keywords and all(targets):
            for in_use in current.actives:
                if all(any(_covers(in_use, kind, value) for kind, value in t) for t in targets):
                    covered_by = in_use.name
                    break
        if covered_by is None:
            out.append(req)
        else:
            plan.warnings.append(f"No {req.describe()} was added because you already use {covered_by}.")
    return out


def build_routine(
    profile, products: Iterable[ProductRecord], conflicts: ConflictTable, options: RankOptions = RANKED
) -> Routine:
    current = current_use(profile)
    catalog = sorted(products, key=lambda p: p.id)
    scorer = Scorer(profile, catalog) if options.use_scores else None
    plan = _Plan(profile, catalog, conflicts, current, options, scorer)
    if current is not None and current.prescription_retinoid:
        plan.warnings.append(cfg.PRESCRIPTION_RETINOID_NOTE)
    reqs = current_use_duplicates(plan, sensitive_substitutions(plan, build_requirements(profile)))
    am = plan_session(plan, cfg.AM, reqs)
    pm = plan_session(plan, cfg.PM, reqs)
    resolve_conflicts(plan, am, conflicts, cfg.AM)
    resolve_conflicts(plan, pm, conflicts, cfg.PM)
    existing_low_conflict_notes(plan, am)
    existing_low_conflict_notes(plan, pm)
    set_alternatives(plan, am)
    set_alternatives(plan, pm)
    kept = {cfg.AM: {s.product.id for s in am if not s.removed},
            cfg.PM: {s.product.id for s in pm if not s.removed}}
    return Routine(
        base_set=base_set(profile),
        am=am,
        pm=pm,
        warnings=list(dict.fromkeys(plan.warnings)),  # de-duplicate, keep order
        left_out=plan.finish_left_out(kept),
        current_products_considered=current is not None,
        unfilled=plan.unfilled,
    )
