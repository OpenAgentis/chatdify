from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = REPO_ROOT / "examples"


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Keep tests away from ~/.chatdify, a local .env and the developer's CHATDIFY_* variables."""
    import os

    for key in list(os.environ):
        if key.startswith("CHATDIFY_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CHATDIFY_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)

    import chatdify.settings as settings_module

    monkeypatch.setattr(settings_module, "CONFIG_FILE", tmp_path / "home" / "config.toml")
    monkeypatch.setitem(settings_module.Settings.model_config, "toml_file", tmp_path / "home" / "config.toml")
    settings_module.configure(home=tmp_path / "home", log_to_console=False)

    # Dify activation is process-global; a test that activates it must not leak into the next.
    from chatdify import dify_compat
    from chatdify.dify_compat import locator

    monkeypatch.setattr(locator, "_active", None)
    monkeypatch.setattr(dify_compat, "_failed_key", None)
    monkeypatch.setattr(dify_compat, "_unavailable_reason", None)
    yield
    settings_module._settings = None


@pytest.fixture
def dify_available():
    from chatdify import dify_compat

    if not dify_compat.is_available():
        pytest.skip(f"Dify static validation unavailable: {dify_compat.unavailable_reason()}")
