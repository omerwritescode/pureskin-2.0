"""The ingredient check: vocabulary names matched as whole words, longest first; an ingredient
no chunk mentions and no routine product contains blocks the question; routine ingredients
never do. (Examples deliberately avoid the ingredients in eval/new_*.json.)"""

from typing import NamedTuple

from app.services.chat.ingredient_check import named_ingredients, unsupported
from app.services.chat.kb import load_kb


class Chunk(NamedTuple):
    title: str
    aliases: tuple
    text: str


class KB(NamedTuple):
    chunks: tuple


FAKE_KB = KB((Chunk("Niacinamide basics", ("nicotinamide",), "Niacinamide and glycerin are common."),
              Chunk("Peroxide", (), "Benzoyl peroxide can bleach fabric.")))


def test_names_are_canonical_whole_words_and_longest_first():
    assert named_ingredients("Is sodium hyaluronate the same as hyaluronic acid?") == ("hyaluronic acid",)
    assert named_ingredients("Is 3-O-Ethyl Ascorbic Acid gentler than ascorbic acid?") == (
        "3-o-ethyl ascorbic acid", "ascorbic acid")
    assert named_ingredients("Nicotinamide or NIACINAMIDE?") == ("niacinamide",)
    assert named_ingredients("Does madecassoside help, or allantoin?") == ("madecassoside", "allantoin")
    assert named_ingredients("panthenols, ureas and glycerine") == ()  # no plurals or misspellings
    assert named_ingredients("How often should I wash my face?") == ()


def test_an_ingredient_in_no_chunk_and_not_in_the_routine_blocks():
    assert unsupported("Does adenosine help wrinkles?", FAKE_KB) == ("adenosine",)
    assert unsupported("Can I mix urea with niacinamide?", FAKE_KB) == ("urea",)


def test_an_ingredient_the_notes_mention_passes():
    assert unsupported("Is niacinamide fine with benzoyl peroxide?", FAKE_KB) == ()
    assert unsupported("What does glycerin do?", FAKE_KB) == ()


def test_an_ingredient_in_the_users_routine_always_passes():
    routine = frozenset({"panthenol", "urea"})
    assert unsupported("What does the panthenol in my moisturiser do?", FAKE_KB, routine) == ()
    assert unsupported("Can I mix urea with niacinamide?", FAKE_KB, routine) == ()
    assert unsupported("Panthenol or adenosine?", FAKE_KB, routine) == ("adenosine",)


def test_no_ingredient_named_never_blocks():
    assert unsupported("Is it worth getting a facial?", FAKE_KB) == ()


def test_the_real_knowledge_base_mentions_the_actives_its_notes_name():
    kb = load_kb()
    for token in ("benzoyl peroxide", "salicylic acid", "retinol", "niacinamide", "ascorbic acid"):
        assert unsupported(f"What does {token} do?", kb) == (), token
