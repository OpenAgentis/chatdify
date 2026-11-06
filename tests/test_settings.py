import pytest

from chatdify import settings as s


def test_defaults_need_no_llm_or_dify():
    cfg = s.get_settings()
    assert cfg.generation_mode == "AutoGen"
    assert cfg.dify_url is None
    assert not cfg.dynamic_validation_enabled
    assert set(cfg.missing_llm_fields()) == {"llm_model", "llm_base_url", "llm_api_key"}


def test_extra_body_from_env_json(monkeypatch):
    monkeypatch.setenv("CHATDIFY_LLM_EXTRA_BODY", '{"thinking": {"type": "enabled"}}')
    assert s.configure().llm_extra_body == {"thinking": {"type": "enabled"}}
    monkeypatch.setenv("CHATDIFY_LLM_EXTRA_BODY", "")
    assert s.configure().llm_extra_body is None


def test_extra_body_from_toml_table():
    s.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    s.CONFIG_FILE.write_text('llm_extra_body = { enable_thinking = false }\n', encoding="utf-8")
    assert s.configure().llm_extra_body == {"enable_thinking": False}


def test_invalid_extra_body_rejected(monkeypatch):
    monkeypatch.setenv("CHATDIFY_LLM_EXTRA_BODY", "not json")
    with pytest.raises(Exception):
        s.configure()


def test_env_overrides_toml(tmp_path, monkeypatch):
    s.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    s.CONFIG_FILE.write_text('llm_model = "from-toml"\nmax_retries = 5\n', encoding="utf-8")
    monkeypatch.setenv("CHATDIFY_LLM_MODEL", "from-env")
    cfg = s.configure()
    assert cfg.llm_model == "from-env"
    assert cfg.max_retries == 5


def test_configure_ignores_none_and_wins_over_env(monkeypatch):
    monkeypatch.setenv("CHATDIFY_GENERATION_MODE", "ZeroShot")
    assert s.configure(generation_mode=None).generation_mode == "ZeroShot"
    assert s.configure(generation_mode="AutoGen").generation_mode == "AutoGen"


def test_paths_follow_home(tmp_path):
    cfg = s.configure(home=tmp_path / "h", embedding_model="BAAI/bge-m3")
    assert cfg.log_dir == tmp_path / "h" / "logs"
    assert cfg.dify_cache_dir == tmp_path / "h" / "dify"
    assert cfg.dsl_embedding_cache_dir.name == "BAAI_bge-m3"


def test_secrets_hidden_from_repr():
    cfg = s.configure(llm_api_key="sk-secret", dify_password="pw")
    assert "sk-secret" not in repr(cfg)
    assert "pw'" not in repr(cfg)
