"""The output gate: sentence by sentence, citations, product markers, the claim list,
thinking text, [NO_ANSWER], and the length cap."""

from app.services.chat import chat_config as cfg
from app.services.chat.gate import Gate

PRODUCTS = {12: "Brand Gentle Cleanser", 5: "Brand Mineral SPF"}


def run(pieces, sent=("kb-sun-uv", "kb-sun-sunscreen-use"), products=PRODUCTS):
    gate = Gate(sent, products)
    out = [r for p in pieces for r in gate.feed(p)]
    out += gate.finish()
    return gate, out


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
    assert [r.text for r in out] == ["One fact."] and gate.stop_reason == "no_answer"


def test_the_length_cap():
    sentence = "x" * 600 + "."
    gate, out = run([f"{sentence} {sentence} {sentence} {sentence}"])
    assert len(out) == 3 and gate.stop_reason == "length"
    assert sum(len(r.text) for r in out) <= cfg.MAX_ANSWER_CHARS


def test_nothing_after_a_stop():
    gate = Gate(("kb-sun-uv",), {})
    gate.feed("It cures everything. ")
    assert gate.stopped and gate.feed("More text. ") == [] and gate.finish() == []
