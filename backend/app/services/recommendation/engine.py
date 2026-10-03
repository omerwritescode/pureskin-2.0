"""Build an AM/PM routine from a Skin Profile, the catalog and the conflict table.

Pure: no database, no FastAPI. app/api/routine.py loads the rows and calls build_routine().

1. rules.build_requirements(): the profile -> requirements (category + keywords).
2. Each requirement takes the first eligible product in rule order (keyword order, then
   product id). A product the profile's hard rules exclude is skipped, and the reason is
   recorded (Routine.left_out). Nothing is invented: a requirement no eligible product
   meets is skipped with a warning.
3. Every pair of products in the same session is checked against the conflict table,
   and the optional one (serum/treatment/exfoliant) is dropped when they clash.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from app.core.utils import normalize_ingredient_pair
from app.services.ingredients import (
    CLASS_PREFIX,
    NormalisedIngredients,
    canonical,
    fragrance_tokens,
    memberships,
    normalise_ingredients,
)

from . import routine_config as cfg
from .matching import keyword_matches
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


ConflictTable = Mapping[tuple[str, str], Conflict]


def _conflict_key(name: str) -> str:
    return name if name.startswith(CLASS_PREFIX) else canonical(name)


def conflict_table(rows: Iterable[tuple[str, str, str, str | None]]) -> dict[tuple[str, str], Conflict]:
    """(ingredient_a, ingredient_b, severity, reason) rows, keyed by their canonical pair.

    A name is an ingredient token or a whole class ("class:retinoid"). The seed loader
    rejects unknown names; here an unknown one simply never matches.
    """
    return {
        normalize_ingredient_pair(_conflict_key(a), _conflict_key(b)): Conflict(severity, reason)
        for a, b, severity, reason in rows
    }


@dataclass
class Step:
    req: Requirement
    product: ProductRecord
    matched_keyword: str | None
    removed: bool = field(default=False)

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


@dataclass
class Routine:
    base_set: str
    am: list[Step]
    pm: list[Step]
    warnings: list[str]
    left_out: list[LeftOut]


# ======================================================================================
# Hard rules: a product the profile can't be given, whatever the step
# ======================================================================================


UNKNOWN, STRONG_ACTIVE, EXCLUDED_INGREDIENT, FRAGRANCE, SESSION = (
    "unknown_ingredients", "strong_active", "excluded_ingredient", "fragrance", "session",
)
# The sensitive-skin hard rules a substitution can stand in for.
SENSITIVE_HARD_RULES = (STRONG_ACTIVE, EXCLUDED_INGREDIENT)


@dataclass(frozen=True)
class Exclusion:
    code: str
    reason: str  # shown to the user; a SESSION reason is worded once the routine is known
    token: str | None = None  # SESSION: the ingredient and its class
    cls: str | None = None


def session_reason(exclusion_: Exclusion, session: str, placed_elsewhere: bool) -> str:
    """The reason for a session-rule exclusion, once we know whether the product is
    in the routine in another session ("not used in the morning routine") or not at all
    ("left out")."""
    singular, plural = cfg.SESSION_CLASS_NAMES[exclusion_.cls]
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


def exclusion(profile, product: ProductRecord, session: str) -> Exclusion | None:
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
            fragrance = fragrance_tokens(product.ingredients)
            if fragrance:
                return Exclusion(FRAGRANCE, (
                    f"It lists {fragrance[0]} (declared fragrance). "
                    "Sensitive skin gets fragrance-free products only."
                ))
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


@dataclass
class _Plan:
    """What planning one routine collects as it goes."""

    profile: object
    products: list[ProductRecord]
    warnings: list[str] = field(default_factory=list)
    left_out: list[_LeftOutEntry] = field(default_factory=list)  # in the order they happened
    _index: dict[tuple, _LeftOutEntry] = field(default_factory=dict)

    def leave_out(self, product: ProductRecord, session: str, excluded_by: Exclusion | str) -> None:
        """Record a product the rules would have used, with why (merged per product+reason)."""
        if isinstance(excluded_by, str):
            key, reason, pending = (product.id, excluded_by), excluded_by, None
        elif excluded_by.code == SESSION:
            key, reason, pending = (product.id, SESSION, excluded_by.cls, excluded_by.token), "", excluded_by
        else:
            key, reason, pending = (product.id, excluded_by.reason), excluded_by.reason, None
        entry = self._index.get(key)
        if entry is None:
            entry = self._index[key] = _LeftOutEntry(product, [], reason, pending)
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
            if key in out:
                merged = tuple(dict.fromkeys(out[key].sessions + tuple(entry.sessions)))
                out[key] = LeftOut(entry.product.id, entry.product.name, merged, reason)
            else:
                out[key] = LeftOut(entry.product.id, entry.product.name, tuple(entry.sessions), reason)
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


def find_product(
    plan: _Plan, req: Requirement, session: str, chosen_ids: set[int]
) -> tuple[ProductRecord | None, str | None, bool]:
    """The first eligible product for the requirement, its keyword, and whether any
    product was skipped for a hard rule. Skipped products are recorded in plan.left_out."""
    excluded = False
    for product, keyword in candidates(plan.products, req):
        if product.id in chosen_ids:  # already in this session's routine
            continue
        excluded_by = exclusion(plan.profile, product, session)
        if excluded_by is not None:
            plan.leave_out(product, session, excluded_by)
            excluded = True
            continue
        return product, keyword, excluded
    return None, None, excluded


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

    steps: list[Step] = []
    chosen_ids: set[int] = set()

    for chain in core_choice.values():
        for i, req in enumerate(chain):
            product, keyword, excluded = find_product(plan, req, session, chosen_ids)
            if product:
                steps.append(Step(req, product, keyword))
                chosen_ids.add(product.id)
                break
            plan.warnings.append(_not_found(req, excluded, fallback=i < len(chain) - 1))

    for req in optional:
        product, keyword, excluded = find_product(plan, req, session, chosen_ids)
        if product:
            steps.append(Step(req, product, keyword))
            chosen_ids.add(product.id)
        else:
            plan.warnings.append(_not_found(req, excluded, fallback=False))
    return steps


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
    return min(found, key=lambda c: cfg.SEVERITY_ORDER.index(c.severity), default=None)


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
            plan.leave_out(loser.product, session, f"It clashes with {winner.product.name}: {conflict.reason}")


def kept_in_order(steps: list[Step]) -> list[Step]:
    """The steps that stay, in application order (stable: keeps priority within a category)."""
    kept = [s for s in steps if not s.removed]
    kept.sort(key=lambda s: cfg.CATEGORY_ORDER.index(s.req.category))
    return kept


def sensitive_substitutions(plan: _Plan, reqs: list[Requirement]) -> list[Requirement]:
    """Replace or drop steps for sensitive skin (routine_config.SENSITIVE_SUBSTITUTIONS).

    An "always" entry applies to every sensitive profile. An "all_excluded" entry applies
    only when the catalog has products for the step and every one of them is left out by
    a sensitive-skin hard rule. Each applied entry adds its warning, and the step's
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
        exclusions = [exclusion(plan.profile, product, req.sessions[0]) for product, _ in found]
        hard = [e is not None and e.code in SENSITIVE_HARD_RULES for e in exclusions]
        if when == cfg.ALL_EXCLUDED and not (found and all(hard)):
            out.append(req)
            continue
        plan.warnings.append(warning)
        for (product, _), excluded_by, is_hard in zip(found, exclusions, hard):
            if is_hard:
                for session in req.sessions:
                    plan.leave_out(product, session, excluded_by)
        if replacement is not None:
            new = requirement(replacement, req.source)
            if new not in reqs and new not in out:
                out.append(new)
    return out


def build_routine(profile, products: Iterable[ProductRecord], conflicts: ConflictTable) -> Routine:
    plan = _Plan(profile, sorted(products, key=lambda p: p.id))
    reqs = sensitive_substitutions(plan, build_requirements(profile))
    am = plan_session(plan, cfg.AM, reqs)
    pm = plan_session(plan, cfg.PM, reqs)
    resolve_conflicts(plan, am, conflicts, cfg.AM)
    resolve_conflicts(plan, pm, conflicts, cfg.PM)
    kept = {cfg.AM: {s.product.id for s in am if not s.removed},
            cfg.PM: {s.product.id for s in pm if not s.removed}}
    return Routine(
        base_set=base_set(profile),
        am=am,
        pm=pm,
        warnings=list(dict.fromkeys(plan.warnings)),  # de-duplicate, keep order
        left_out=plan.finish_left_out(kept),
    )
