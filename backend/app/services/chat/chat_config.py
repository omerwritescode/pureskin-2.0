"""Conversational AI rules (roadmap step 7d): the knowledge base's rules, the claim list
and retrieval.

Hand-set, like every config here. Any change that can change a result (which chunks load,
what retrieval returns, what the claim list blocks) must bump CHAT_CONFIG_VERSION
(app/tests/test_config_versions.py checks). The knowledge base itself, kb/kb.json, is
versioned separately (kb-X.Y.Z, fingerprint in tests/test_kb.py).
"""

CHAT_CONFIG_VERSION = "chat-1.0.0"

# ======================================================================================
# Knowledge base (kb/kb.json): what a chunk must hold to load
# ======================================================================================
KB_VERSION_PATTERN = r"^kb-\d+\.\d+\.\d+$"
KB_ID_PATTERN = r"^kb-[a-z0-9]+(?:-[a-z0-9]+)*$"
KB_TOPICS = ("sun", "acne", "marks", "redness", "dry_ageing", "reactions", "safety", "app")
KB_TITLE_MAX_CHARS = 60
KB_TEXT_WORDS = (40, 120)  # inclusive bounds
KB_ALIASES_MAX = 10
DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"

# Licence classes (STOP 1). all_rights_reserved sources (AAD, DermNet, MedlinePlus's
# A.D.A.M. encyclopedia and drug monographs) are not a class: they can't be cited at all.
LICENCE_CLASSES = ("public_domain", "ogl", "app_doc")
SOURCE_ROLES = ("support", "further_reading")
# Every chunk needs at least one "support" source of these classes. The NHS (ogl) is
# unattributed further reading only: its terms forbid citing it as the source of adapted
# content, so it can never be the support for a sentence.
SUPPORT_CLASSES = ("public_domain", "app_doc")
FURTHER_READING_ONLY_CLASSES = ("ogl",)
# The hosts each web licence class may come from (the host itself or a subdomain).
SOURCE_HOSTS = {
    # MedlinePlus: only the "Summary" block of a health-topic page is public domain.
    "public_domain": ("medlineplus.gov", "niams.nih.gov", "nia.nih.gov"),
    "ogl": ("nhs.uk",),
}
BLOCKED_HOSTS = ("aad.org", "dermnetnz.org")  # excluded by the user (STOP 1 answer 7)
APP_DOC_PREFIX = "repo:"  # app_doc sources are repo paths, e.g. repo:backend/seed.py
# The load report flags (never rejects) a page whose own date is older than this.
PAGE_AGE_FLAG_YEARS = 3

# Chunk text names no publisher (attribution lives in a chunk's sources), links nowhere
# and carries no phone number (numbers live only in the router's templates, each from an
# official page). Whole words, case-sensitive.
PUBLISHER_NAMES = (
    "NHS", "MedlinePlus", "National Library of Medicine", "NLM", "NIH",
    "National Institutes of Health", "NIAMS", "NIA", "National Institute", "FDA",
    "Food and Drug Administration", "CDC", "AAD", "American Academy of Dermatology", "DermNet",
)
URL_PATTERN = r"https?://|www\.|\b[a-z0-9-]+\.(?:com|org|gov|net|in|uk)\b"
# A run of 5+ digits, three digit groups ("1800-89-14416") or a known emergency or
# helpline number. Score bands ("61-100") are two groups and pass.
PHONE_PATTERNS = (
    r"\b\d{5,}\b",
    r"\b\d{2,5}[\s-]\d{2,5}[\s-]\d{2,5}\b",
    r"\b(?:112|108|111|911|988|999|14416)\b",
)

# ======================================================================================
# The claim list (STOP 1 change D): one narrow list for the KB, the templates and the
# model's output. Case-insensitive; curly apostrophes are straightened first.
# ======================================================================================
# Condition terms for "you have <condition>" (a diagnosis in the second person).
CONDITION_TERMS = (
    "acne", "rosacea", "eczema", "dermatitis", "psoriasis", "melasma", "melanoma", "cancer",
    "carcinoma", "cellulitis", "infection", "impetigo", "vitiligo", "hives", "urticaria",
    "folliculitis", "fungal", "ringworm", "scabies", "shingles", "keratosis", "lupus",
    "anaphylaxis", "allergy",
)
CLAIM_PATTERNS = (
    ("cure", r"\bcures?\b"),
    ("guaranteed", r"\bguaranteed\b"),
    ("proven", r"\bproven\b"),  # also "clinically proven"
    ("diagnos-", r"\bdiagnos\w*"),
    ("you have + condition",
     r"\byou(?:'ve|\s+have|\s+(?:may|might|could|probably|likely|definitely)\s+have)"
     r"\s+(?:got\s+)?(?:(?:a|an|some|mild|severe|bad)\s+)?(?:{conditions})\b"),
)

# ======================================================================================
# Retrieval: hand-written BM25 (Okapi, with the always-positive idf
# ln(1 + (N - df + 0.5) / (df + 0.5))) over each chunk's title, aliases and text.
# ======================================================================================
BM25_K1 = 1.2  # the usual defaults, not tuned
BM25_B = 0.75
TOP_K = 4
# The "I don't know" line: a question whose best chunk scores below this gets the fixed
# no-answer reply without a model call. Chosen on the dev questions only by
# evaluate.choose_line on kb-1.0.0 (2026-10-08: 7/7 answerable kept, 3/4 no-answer refused;
# the leak is d08, collagen supplements, at 4.82 on the ageing chunk), then frozen
# (eval/freeze.json).
NO_ANSWER_MIN_SCORE = 3.03

TOKEN_PATTERN = r"[a-z0-9]+"
# Plural endings, tried in order; the first that fits wins. A word ending in one of
# KEEP_ENDINGS is left alone, and no stem is shorter than MIN_STEM letters.
PLURAL_RULES = (("ies", "y"), ("sses", "ss"), ("shes", "sh"), ("ches", "ch"), ("xes", "x"), ("s", ""))
KEEP_ENDINGS = ("ss", "us", "is")
MIN_STEM = 3
# British spellings -> one form, applied to chunks and questions alike (after plurals).
SPELLING = {
    "colour": "color", "ageing": "aging", "moisturiser": "moisturizer",
    "moisturise": "moisturize", "moisturising": "moisturizing", "fibre": "fiber",
    "sulphur": "sulfur", "recognise": "recognize", "specialise": "specialize",
    "behaviour": "behavior", "odour": "odor", "centre": "center",
}
# Apostrophes are dropped before tokenising ("don't" -> "dont"), hence "dont", "whats"...
STOPWORDS = tuple(sorted(set("""
a about after again all also am an and any are as at be because been before being both
but by can cant could did do does doesnt doing don dont during each few for from further
had has have having he her here hers him his how i if im in into is isnt it its itself
ive just me more most much many my myself no nor not now of off on once only or other our
ours out over own same she should so some such than that thats the their theirs them then
there these they this those through to too under until up very was we were what whats
when where which while who whom why will with wont would you youre your yours yourself
get got use using used really
help please tell thing know want
""".split())))
# Question idioms removed before tokenising questions (never chunks). Set on the dev split:
# "is that normal?" asks whether something is expected, and matched the "normal" skin type.
QUESTION_IDIOMS = (r"\bis (?:it|that|this) (?:normal|ok|okay|fine)\b",)
