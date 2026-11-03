from bot.utils.text_match import MATCH_SUBSTRING, find_banned, normalize


def test_whole_word_does_not_match_inside_other_word():
    assert not find_banned("This is a class", ["ass"])
    assert not find_banned("Еду в Херсон", ["хер"])


def test_whole_word_matches_standalone_word():
    assert find_banned("you ass!", ["ass"])
    assert find_banned("Ну и хер с ним", ["хер"])


def test_case_and_yo_are_ignored():
    assert find_banned("ЁЛКА растёт", ["елка"])


def test_homoglyphs_and_digits_are_normalized():
    assert find_banned("смотри р0рн тут", ["рорн"])
    assert find_banned("pоpн", ["рорн"])  # латиница вперемешку с кириллицей


def test_repeated_letters_are_collapsed():
    assert find_banned("хееееер", ["хер"])


def test_invisible_characters_are_removed():
    assert find_banned("х\u200bер", ["хер"])


def test_substring_mode_matches_inside_words():
    assert find_banned("This is a class", ["ass"], MATCH_SUBSTRING)


def test_empty_inputs():
    assert not find_banned("", ["хер"])
    assert not find_banned("текст", [])
    assert not find_banned("текст", ["  "])


def test_normalize_is_idempotent():
    s = normalize("Р0РН xxx Ёж")
    assert normalize(s) == s
