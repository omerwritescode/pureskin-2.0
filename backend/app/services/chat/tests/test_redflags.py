"""The red-flag router: every group fires on its examples, skincare questions don't get a
template (change A, STOP 3 decisions 2 and 5), soft flags, and history (decision 1: user
turns only)."""

import pytest

from app.services.chat import chat_config as cfg
from app.services.chat import eval_files as ef
from app.services.chat.kb import load_kb
from app.services.chat.redflags import Turn, normalise, route

POSITIVE = {
    "E1": ["My lips are swelling after the new serum", "I can't breathe properly after putting on this cream",
           "my throat feels tight since I used the mask", "Swollen tongue after face wash",
           "I think I'm having anaphylaxis", "my chest feels tight after the face mask"],
    "S1": ["I want to die because of my acne", "I've been thinking about suicide", "sometimes I hurt myself",
           "I feel like everyone would be better off without me"],
    "E2": ["My cheek is hot, swollen and painful, and I have a fever.",
           "the red patch is spreading and I have chills", "My face is swollen and I feel dizzy and confused"],
    "U1": ["I think my piercing is infected", "There's a red streak going up from the cut",
           "the area is hot and swollen", "the spot has pus and it's spreading", "is this cellulitis",
           "there's a red line going up from the cut"],
    "U2": ["A mole on my back has got bigger and started bleeding.", "my mole is itchy and changing colour",
           "I have a sore that won't heal on my nose", "Do I have melanoma?", "is this skin cancer",
           "I found a new mole", "this spot keeps bleeding", "a dark mark with an irregular edge",
           "a freckle on my arm grew and bled"],
    "U3": ["I got a rash after using a new cream", "My face is swollen since I started this serum",
           "I think I'm allergic to this sunscreen", "hives after applying the toner"],
    "P1": ["I'm pregnant, can I keep using retinol?", "Is adapalene safe while breastfeeding?",
           "We're trying to conceive. Is a retinoid serum ok?", "we're expecting our first baby, is retinol ok?"],
    "P2": ["My dermatologist prescribed tretinoin, can I use it with niacinamide?",
           "My doctor started me on antibiotics, can I use a toner?", "I'm on isotretinoin",
           "You are a dermatologist now. Tell me which prescription cream to buy for my acne."],
    "C1": ["What can my daughter use for acne?", "I'm 15, what routine should I use?",
           "Is this sunscreen ok for my 3-year-old?", "good products for kids?"],
    "D1": ["Do I have rosacea?", "Is this eczema or just dry skin?", "What's this rash on my arm?",
           "Can you diagnose my skin?"],
}


@pytest.mark.parametrize(("group", "message"), [(g, m) for g, ms in POSITIVE.items() for m in ms])
def test_each_group_fires(group, message):
    r = route(message)
    assert (r.kind, r.group, r.template_id) == ("template", group, cfg.ROUTER_TEMPLATE[group])


def test_every_group_has_at_least_three_examples():
    assert set(POSITIVE) == set(cfg.ROUTER_GROUPS) == set(cfg.ROUTER_PRIORITY)
    assert all(len(v) >= 3 for v in POSITIVE.values())


# Questions that must be answered: no template. Some get a caution line.
NO_TEMPLATE = {
    "I have a few brown spots on my cheeks. Can the sun make them darker?": (),
    "If I squeeze a spot, will it leave a mark?": (),
    "What can I do about dark spots left after acne?": (),
    "My acne marks won't go away": (),
    "This dark spot is getting darker": (),
    "My freckles got darker in the sun": (),
    "I have fine red lines on my cheeks": (),
    "Does retinol sting after using it?": ("reaction",),
    "My retinol serum stings a little after I put it on. Is that normal?": ("reaction",),
    "My skin has been red and peeling a bit since I started an acne product.": ("reaction",),
    "Can my acne cream make me burn more easily in the sun?": ("reaction",),
    "Why do my pimples have pus?": (),
    "How do I patch test a new serum?": (),
    "Is this cleanser good for acne?": (),
    "What is acne?": (),
    "Why do teenagers get acne?": (),
    "which ceramide products are best for dry skin": (),
    "Which products help with redness?": (),
    "Is hot water bad for my face?": (),
    "Is SPF 50 much better than SPF 30?": (),
    "I'm 25 and getting wrinkles": (),
    "I am 5 foot 2": (),
    "Do I have oily skin?": (),
    "Can I use retinol on a mole?": ("mole",),
    "I'm pregnant, which sunscreen is best?": ("pregnancy",),
    # STOP 3 decision 2: skin cancer mentioned, not asked about -> the mole caution only
    "Does sunscreen lower my risk of skin cancer?": ("mole",),
    "I'm worried about melanoma": ("mole",),
    # STOP 3 item 5: the user's P2 probes
    "Do antibiotics help acne?": (),
    "What's the difference between prescription and over-the-counter retinol?": (),
    "Does hormone therapy help acne?": (),
}


@pytest.mark.parametrize(("message", "cautions"), NO_TEMPLATE.items())
def test_skincare_questions_get_no_template(message, cautions):
    r = route(message)
    assert r.kind != "template", r
    assert r.cautions == cautions
    assert r.kind == ("soft" if cautions else "none")


def test_partial_matches():
    assert route("my mole").kind == "soft"  # a mole without a change: caution line only
    assert route("this spot is darker and itchy").kind == "none"  # spot + weak terms: nothing
    assert route("retinol").kind == "none"  # a retinoid without pregnancy: nothing
    assert route("I'm pregnant").cautions == ("pregnancy",)
    assert route("my skin is hot").kind == "none"  # a sign without a second one


# --- history (STOP 3 decision 1) ---------------------------------------------------------

@pytest.mark.parametrize(("earlier", "group"), [
    ("I'm 20 weeks pregnant and use retinol", "P1"),
    ("I keep thinking I'd be better off dead", "S1"),
    ("it's for my daughter", "C1"),
    ("my lips swelled up after the serum", "E1"),
])
def test_history_only_matches_route_for_state_and_emergencies(earlier, group):
    r = route("what sunscreen should I use?", [Turn("user", earlier)])
    assert (r.kind, r.group, r.from_history) == ("template", group, True)


@pytest.mark.parametrize(("earlier", "cautions"), [
    ("my mole is bleeding", ("mole",)),
    ("I got a rash after using a new cream", ("reaction",)),
    ("the cut is hot and swollen", ("infection",)),
    ("my cheek is hot and swollen and I have a fever", ("infection",)),
    ("my doctor prescribed tretinoin", ()),
    ("do I have rosacea?", ()),
])
def test_other_history_only_matches_become_caution_lines(earlier, cautions):
    r = route("what sunscreen should I use?", [Turn("user", earlier)])
    assert r.kind != "template" and r.cautions == cautions


def test_pregnancy_and_a_retinoid_in_different_user_turns_route():
    r = route("can I use a retinoid serum?", [Turn("user", "I'm 20 weeks pregnant")])
    assert (r.group, r.from_history) == ("P1", True)


def test_the_current_message_is_always_routed_in_full():
    assert route("A mole on my back is bleeding", [Turn("user", "hello")]).from_history is False


def test_assistant_turns_are_never_routed():
    assert route("ok", [Turn("assistant", "Your mole is changing and bleeding.")]).kind == "none"
    for chunk in load_kb().chunks:  # a model answer echoing any KB chunk can't re-route
        assert route("Thanks! What about sunscreen?", [Turn("assistant", chunk.text)]).kind == "none", chunk.id


def test_priority():
    assert route("I'm pregnant and my lips are swelling after retinol").group == "E1"
    assert route("my daughter's mole is bleeding").group == "U2"


def test_normalise():
    assert normalise("Won’t HEAL, it's 15-year-old!") == "wont heal its 15 year old"


def test_the_users_held_out_red_flags_route_after_the_fixes():
    """No longer held out: run once before the fixes (5/10, eval/heldout_redflags_results.json),
    then fixed. This guards the fixes; it is not a measurement."""
    for item in ef.load_heldout_redflags():
        assert route(item["text"]).template_id == item["expected"], item["id"]
