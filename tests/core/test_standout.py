from ptopilot.core.standout import is_standout, standout_tag


def test_standout_needs_every_condition():
    assert is_standout(90, "great", "normal", True, 2)
    for args in [
        (84, "great", "normal", True, 2),
        (90, "good", "normal", True, 2),
        (90, "great", "low", True, 2),
        (90, "great", "normal", False, 2),
        (90, "great", "normal", True, 4),
        (90, "great", "normal", True, None),
    ]:
        assert not is_standout(*args)


def test_tag_text():
    assert standout_tag(2) == "Rare: likely gone within ~2 days"
    assert standout_tag(1) == "Rare: likely gone within ~1 day"
    assert standout_tag(None) is None
