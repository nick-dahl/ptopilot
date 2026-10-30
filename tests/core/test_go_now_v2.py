from ptopilot.core.scoring import conservative_z, deal_component, go_now


def test_capped_deal_part_is_at_most_half():
    assert deal_component(-2.5, capped=True) == 0.5 and deal_component(-2.5) == 1.0


def test_a_weak_deal_is_not_lifted_by_the_cap():
    assert deal_component(-0.5, capped=True) == deal_component(-0.5) < 0.5
    assert deal_component(None, capped=True) == 0.0


def test_conservative_z_keeps_the_less_extreme():
    assert conservative_z(-2.0, -0.8) == -0.8 and conservative_z(-2.0, None) == -2.0
    assert conservative_z(None, -0.8) == -0.8 and conservative_z(None, None) is None
    assert conservative_z(-0.8, -2.0) == -0.8


def test_go_now_passes_the_cap_through():
    full = go_now(-3.0, "good", 2.0, 60, True)
    assert full - go_now(-3.0, "good", 2.0, 60, True, deal_capped=True) in (24, 25)
