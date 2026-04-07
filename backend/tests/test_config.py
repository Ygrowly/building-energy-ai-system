from app.core.config import Settings


def test_debug_release_is_parsed_as_false():
    settings = Settings(DEBUG="release")

    assert settings.DEBUG is False


def test_debug_dev_is_parsed_as_true():
    settings = Settings(DEBUG="dev")

    assert settings.DEBUG is True
