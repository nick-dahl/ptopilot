from ptopilot import config


def test_package_imports_and_thresholds_are_ordered():
    assert config.GREAT_DEAL_Z < config.GOOD_DEAL_Z < 0
    assert abs(sum(config.GO_NOW_WEIGHTS.values()) - 1.0) < 1e-9
