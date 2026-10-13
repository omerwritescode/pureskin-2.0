"""The output gate: sentence by sentence, citations, product markers, the claim list,
thinking text, [NO_ANSWER] anywhere (F1), doubled names (F3), stray brackets (F4), the system
rules' wording (F5), phone numbers and the length cap."""

import pytest

from app.services.chat import chat_config as cfg
from app.services.chat.gate import Gate

PRODUCTS = {12: "Brand Gentle Cleanser", 5: "Brand Mineral SPF"}


def run(pieces, sent=("kb-sun-uv", "kb-sun-sunscreen-use"), products=PRODUCTS):
    gate = Gate(sent, products)
    for p in pieces:
        gate.feed(p)
    return gate, gate.finish()


def test_released_sentence_by_sentence_across_pieces():
    gate, out = run(["Reapply sun", "screen every two hours [kb-sun-sunscreen-use]. Shade ", "helps too."])
    assert [r.text for r in out] == ["Reapply sunscreen every two hours.", "Shade helps too."]
    assert out[0].cites == ("kb-sun-sunscreen-use",) and not gate.stopped


def test_a_citation_must_be_a_note_that_was_sent():
    gate, out = run(["Fact one [kb-acne-what][kb-sun-uv]. Fact two [profile]."])
    assert out[0].cites == ("kb-sun-uv",) and out[1].cites == ("profile",)
    assert "kb-acne-what" not in out[0].text and gate.counts["invalid_citation"] == 1


def test_product_markers_get_names_and_unknown_ones_stop():
    gate, out = run(["Use [P12] each morning. Then [P5]."])
    assert [r.text for r in out] == ["Use Brand Gentle Cleanser each morning.", "Then Brand Mineral SPF."]
    gate, out = run(["Use [P12] each morning. Also buy [P99] today. More."])
    assert [r.text for r in out] == ["Use Brand Gentle Cleanser each morning."]
    assert gate.stop_reason == "unknown_product"


def test_the_claim_list_holds_the_sentence_back_and_stops():
    for bad in ("This serum cures acne.", "Results are guaranteed.", "It is clinically proven.",
                "You have rosacea.", "That looks like a diagnosis of eczema."):
        gate, out = run([f"A fine first sentence. {bad} Never sent."])
        assert [r.text for r in out] == ["A fine first sentence."], bad
        assert gate.stop_reason == "claim"


def test_thinking_text_never_goes_out():
    gate, out = run(["<think>secret plan", " more secret</think>The answer is here."])
    assert [r.text for r in out] == ["The answer is here."] and gate.counts["thinking"] == 1
    gate, out = run(["Visible. <think>never closed and secret"])
    assert [r.text for r in out] == ["Visible."]
    assert all("secret" not in r.text for r in out)


def test_no_answer():
    gate, out = run(["[NO_", "ANSWER]"])
    assert out == [] and gate.stop_reason == "no_answer"
    gate, out = run(["One fact. [NO_ANSWER] trailing."])
    assert out == [] and gate.stop_reason == "no_answer"  # F1: the whole answer


def test_the_length_cap():
    sentence = "x" * 600 + "."
    gate, out = run([f"{sentence} {sentence} {sentence} {sentence}"])
    assert len(out) == 3 and gate.stop_reason == "length"
    assert sum(len(r.text) for r in out) <= cfg.MAX_ANSWER_CHARS


def test_nothing_after_a_stop():
    gate = Gate(("kb-sun-uv",), {})
    gate.feed("It cures everything. ")
    gate.feed("More text. ")
    assert gate.stopped and gate.finish() == [] and gate.held == []


def test_a_phone_number_holds_the_sentence_back_and_stops():
    for bad in ("Call 911 now.", "In India, call 112.", "Ring 988 for help.", "Call Tele-MANAS on 14416.",
                "Their helpline is 1800-89-14416.", "Call 9152987821 today.", "Dial 1 800 123 4567 first."):
        gate, out = run([f"A fine first sentence. {bad} Never sent."])
        assert [r.text for r in out] == ["A fine first sentence."], bad
        assert gate.stop_reason == "number", bad


def test_ordinary_numbers_pass():
    gate, out = run(["Use SPF 30 or above. Reapply every 2 hours, or 15 to 30 minutes before going out. "
                     "Your acne score is in the 61-100 band. A 10% niacinamide serum. "
                     "Apply [P12] twice a day."], products={12: "Brand 2% BHA 11112 Gel 1-2-3"})
    assert not gate.stopped and len(out) == 5
    assert out[-1].text == "Apply Brand 2% BHA 11112 Gel 1-2-3 twice a day."  # a swapped-in name never trips it


# --- STOP 6 fixes ---------------------------------------------------------------------------
def test_f1_no_answer_anywhere_makes_the_whole_answer_the_fixed_reply():
    for pieces in (["Two fine sentences [kb-sun-uv]. ", "Another one. ", "[NO_ANSWER]"],
                   ["The notes don't say.\n[no_answer]"], ["Fine. [No Answer]"], ["Fine.\n[NO_ANSWER]\nMore."]):
        gate, out = run(pieces)
        assert out == [] and gate.stop_reason == "no_answer", pieces


@pytest.mark.parametrize("marker", ["[NO_ANSWER]", "[no_answer]", "[No Answer]", "[no-answer]", "[NOANSWER]",
                                    "NO_ANSWER", "no_answer", "No answer", "NO-ANSWER", "noanswer",
                                    "There is no answer to that in the notes"])
def test_every_no_answer_variant(marker):
    gate, out = run([f"A first sentence [kb-sun-uv]. {marker}. After."])
    assert out == [] and gate.stop_reason == "no_answer", marker


@pytest.mark.parametrize("text", ["The answer is no.", "No. Answer: reapply every two hours.",
                                  "No answers are guaranteed here", "Know answer"])
def test_not_a_no_answer_marker(text):
    gate, out = run([f"{text}. Fine."])
    assert gate.stop_reason != "no_answer", text


def test_f1_nothing_is_released_before_the_end():
    gate = Gate(("kb-sun-uv",), {})
    gate.feed("A checked sentence [kb-sun-uv]. ")
    assert [r.text for r in gate.held] == ["A checked sentence."] and gate.released_sentences == 0
    assert [r.text for r in gate.finish()] == ["A checked sentence."] and gate.released_sentences == 1


def test_f3_a_name_repeated_around_its_marker_is_collapsed():
    for answer in ("Use [P12] Brand Gentle Cleanser each morning.", "Use Brand Gentle Cleanser [P12] each morning.",
                   "Use [P12] (Brand Gentle Cleanser) each morning.", "Use [P12] brand gentle cleanser each morning.",
                   "Use [P12]: Brand Gentle Cleanser each morning."):
        gate, out = run([answer])
        assert [r.text for r in out] == ["Use Brand Gentle Cleanser each morning."], answer
        assert gate.counts["doubled_name"] == 1
    gate, out = run(["Use [P12] then [P5]."])
    assert [r.text for r in out] == ["Use Brand Gentle Cleanser then Brand Mineral SPF."]
    assert gate.counts["doubled_name"] == 0


def test_f4_any_other_bracket_stops_the_answer():
    for bad in ("[NOTE: The user is not pregnant. The answer is general.]", "See a doctor [Safety Rule 1].",
                "Read [this page](https://example.com).", "Use it twice a day [citation needed].",
                "Two notes [kb-sun-uv, kb-sun-other].", "A stray ] here.", "[Profile] says oily."):
        gate, out = run([f"A fine first sentence [kb-sun-uv]. {bad} Never sent."])
        assert [r.text for r in out] == ["A fine first sentence."], bad
        assert gate.stop_reason == "bracket", bad


def test_f4_citations_markers_and_unsent_citations_are_not_brackets():
    gate, out = run(["Fact [kb-sun-uv][profile]. Use [P12]. Made up [kb-not-sent]."])
    assert not gate.stopped and len(out) == 3 and gate.counts["invalid_citation"] == 1


def test_f5_a_run_of_the_rules_stops_the_answer_even_across_sentences():
    rules = cfg.SYSTEM_PROMPT.split("\n")[2]  # rule 2
    words = rules.split()
    gate, out = run([f"A fine first sentence. My rules: {' '.join(words[1:10])} etc. Never sent."])
    assert [r.text for r in out] == ["A fine first sentence."] and gate.stop_reason == "prompt"
    split = f"Fine. Rules say {' '.join(words[1:5])}. {' '.join(words[5:10])} too."
    gate, out = run([split])
    assert gate.stop_reason == "prompt"


def test_f5_a_paraphrase_or_a_shorter_run_passes():
    gate, out = run(["I only answer from PureSkin's notes and your profile, citing them. "
                     "Please see a doctor or pharmacist about that."])
    assert not gate.stopped and len(out) == 2
    seven = " ".join(cfg.SYSTEM_PROMPT.split("\n")[2].split()[1:8])
    gate, out = run([f"{seven}."])
    assert gate.stop_reason != "prompt"

