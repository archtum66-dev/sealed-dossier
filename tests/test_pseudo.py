import json

import pytest

from sealed.pseudo import Pseudonymizer, load_entities


@pytest.fixture
def entities():
    return {
        "person": [["Hans Muster", "Hans", "Muster"], "Anna Beispiel"],
        "org": ["Beispiel AG"],
        "place": ["Zürich"],
        "case": [],
        "other": [],
    }


def test_alias_same_placeholder(entities):
    p = Pseudonymizer(entities)
    t1 = p.apply("Hans Muster owes rent.")
    t2 = p.apply("Contact Hans.")
    assert "[PERSON_1]" in t1
    assert "[PERSON_1]" in t2
    assert p.leaks(t1 + t2) == []


def test_longest_alias_wins(entities):
    p = Pseudonymizer(entities)
    out = p.apply("Hans Muster signed.")
    assert "Hans" not in out
    assert "[PERSON_1]" in out


def test_genitive_s(entities):
    p = Pseudonymizer(entities)
    out = p.apply("Hans Musters contract")
    assert out.startswith("[PERSON_1]")


def test_word_boundary_mustermann(entities):
    p = Pseudonymizer(entities)
    out = p.apply("Mustermann is unrelated.")
    assert "[PERSON_" not in out
    assert "Mustermann" in out


def test_newline_in_name(entities):
    p = Pseudonymizer(entities)
    out = p.apply("Hans\nMuster lives here.")
    assert "[PERSON_1]" in out


def test_case_insensitive(entities):
    p = Pseudonymizer(entities)
    out = p.apply("hans MUSTER")
    assert "[PERSON_1]" in out


def test_builtin_ahv():
    p = Pseudonymizer({k: [] for k in ("person", "org", "place", "case", "other")})
    out = p.apply("AHV 756.1234.5678.97")
    assert "[AHV_1]" in out
    assert p.leaks(out) == []


def test_builtin_iban():
    p = Pseudonymizer({k: [] for k in ("person", "org", "place", "case", "other")})
    out = p.apply("IBAN CH93 0076 2011 6238 5295 7 end")
    assert "[IBAN_1]" in out


def test_builtin_email():
    p = Pseudonymizer({k: [] for k in ("person", "org", "place", "case", "other")})
    out = p.apply("mail user.name@example.com now")
    assert "[EMAIL_1]" in out


def test_builtin_phone():
    p = Pseudonymizer({k: [] for k in ("person", "org", "place", "case", "other")})
    out = p.apply("call +41 44 123 45 67 today")
    assert "[PHONE_1]" in out
    bad = p.apply("id 44123456789012")
    assert "[PHONE_" not in bad


def test_builtin_case_number():
    p = Pseudonymizer({k: [] for k in ("person", "org", "place", "case", "other")})
    out = p.apply("File MI.2026.14 open")
    assert "[CASE_1]" in out


def test_restore_round_trip(entities):
    p = Pseudonymizer(entities)
    original = "Hans Musters MI.2026.14 in Zürich"
    applied = p.apply(original)
    restored = p.restore(applied)
    assert restored != original
    assert restored.lower().startswith("hans muster")


def test_leaks_detects_raw_name(entities):
    p = Pseudonymizer(entities)
    assert "person" in p.leaks("Hans Muster still here")


def test_load_entities_validates(tmp_path):
    path = tmp_path / "entities.json"
    path.write_text('{"person": "bad"}', encoding="utf-8")
    with pytest.raises(ValueError):
        load_entities(path)


def test_mapping_and_counts(entities):
    p = Pseudonymizer(entities)
    p.apply("Beispiel AG and Hans Muster")
    assert p.counts["person"] == 1
    assert p.counts["org"] == 1
    assert p.mapping()["[PERSON_1]"] == "Hans Muster"


def test_email_containing_a_listed_name_is_replaced_as_a_whole():
    p = Pseudonymizer({"person": [["Corinne Wyss", "Wyss"]]})
    out = p.apply("Write to corinne.wyss@firma-beispiel.example or call Wyss.")
    assert "corinne" not in out.lower()
    assert "firma" not in out
    assert "[EMAIL_1]" in out
    assert "[PERSON_1]" in out
    assert p.leaks(out) == []


def test_same_builtin_value_gets_the_same_placeholder():
    p = Pseudonymizer({})
    out = p.apply("IBAN CH93 0076 2011 6238 5295 7 and again CH9300762011623852957")
    assert out.count("[IBAN_1]") == 2
    assert "[IBAN_2]" not in out
    assert p.counts == {"iban": 1}


def test_placeholders_are_numbered_by_first_appearance():
    p = Pseudonymizer({"person": ["Anna Beispiel", "Bruno Beispiel"]})
    out = p.apply("Bruno Beispiel schreibt an Anna Beispiel. Bruno Beispiel wartet.")
    assert out == "[PERSON_1] schreibt an [PERSON_2]. [PERSON_1] wartet."
