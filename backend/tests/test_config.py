from app.core.config import Settings


def test_debug_release_is_parsed_as_false():
    settings = Settings(DEBUG="release")

    assert settings.DEBUG is False


def test_debug_dev_is_parsed_as_true():
    settings = Settings(DEBUG="dev")

    assert settings.DEBUG is True


def test_auto_dispatch_csv_lists_are_parsed_from_env(monkeypatch):
    monkeypatch.setenv("AUTO_DISPATCH_ALLOWED_BUILDINGS", "A, B ,, C")
    monkeypatch.setenv("AUTO_DISPATCH_ALLOWED_PRIORITIES", "high, medium")
    monkeypatch.setenv("AUTO_DISPATCH_ALLOWED_REQUIRED_SKILLS", "hvac, electrician")

    settings = Settings(_env_file=None)

    assert settings.AUTO_DISPATCH_ALLOWED_BUILDINGS == ["A", "B", "C"]
    assert settings.AUTO_DISPATCH_ALLOWED_PRIORITIES == ["high", "medium"]
    assert settings.AUTO_DISPATCH_ALLOWED_REQUIRED_SKILLS == ["hvac", "electrician"]
