import json

import pytest

from chatdify import cli
from conftest import EXAMPLES


def run(capsys, *argv):
    code = cli.main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert "chatdify" in capsys.readouterr().out


def test_no_command_prints_help(capsys):
    code, out, _ = run(capsys)
    assert code == cli.EXIT_ERROR
    assert "generate" in out


def test_generate_without_llm_is_config_error(capsys):
    code, _, err = run(capsys, "generate", "hello")
    assert code == cli.EXIT_ERROR
    assert "chatdify init" in err


def test_retrieval_mode_requires_embedding(capsys, monkeypatch):
    monkeypatch.setenv("CHATDIFY_LLM_API_KEY", "k")
    code, _, err = run(capsys, "generate", "hello", "--base-url", "https://example.com/v1",
                       "--model", "m", "--mode", "AutoRec")
    assert code == cli.EXIT_ERROR
    assert "embedding" in err


@pytest.fixture
def fake_generate(monkeypatch):
    from chatdify import api

    calls = []

    def generate(request, **kwargs):
        calls.append(kwargs)
        return api.RunResult(success=True, dsl="app: {}\n", attempts=1, duration=0.0,
                             static_checked=False, dynamic_checked=False)

    monkeypatch.setenv("CHATDIFY_LLM_API_KEY", "k")
    monkeypatch.setenv("CHATDIFY_LLM_MODEL", "m")
    monkeypatch.setenv("CHATDIFY_LLM_BASE_URL", "https://example.com/v1")
    monkeypatch.setattr(api, "generate", generate)
    return calls


@pytest.mark.parametrize(
    "extra,expected",
    [(["-o", "{tmp}/translate.yml"], "translate"),
     (["-o", "{tmp}/x.yml", "--name", "翻译助手"], "翻译助手"),
     ([], None)],
)
def test_generate_app_name(capsys, tmp_path, fake_generate, extra, expected):
    argv = [a.format(tmp=tmp_path) for a in extra]
    code, _, _ = run(capsys, "generate", "hello", "-q", *argv)
    assert code == cli.EXIT_OK
    assert fake_generate[0]["name"] == expected


def test_eval_names_app_after_case(capsys, tmp_path, fake_generate):
    cases = tmp_path / "cases.yaml"
    cases.write_text("demo_cases:\n  ppt_outline:\n    prompt: make a ppt outline\n", encoding="utf-8")
    code, _, _ = run(capsys, "eval", "generation", str(cases), "-q", "-o", str(tmp_path / "out"))
    assert code == cli.EXIT_OK
    assert fake_generate[0]["name"] == "ppt_outline"


def test_validate_without_dify_explains_how_to_enable(capsys):
    code, _, err = run(capsys, "validate", str(EXAMPLES / "dsl"), "--no-static")
    assert code == cli.EXIT_ERROR
    assert "dify status" in err


def test_validate_missing_path(capsys):
    code, _, err = run(capsys, "validate", "does-not-exist.yml")
    assert code == cli.EXIT_ERROR


def test_dify_status_json(capsys):
    code, out, _ = run(capsys, "dify", "status", "--json", "--dify-src", "/nonexistent")
    assert code == cli.EXIT_OK
    data = json.loads(out)
    assert data["found"] is None
    assert data["static_validation"] is False
    assert data["searched"][0]["source"] == "dify_src setting"


def test_init_non_interactive_writes_private_config(capsys):
    from chatdify import settings

    code, _, _ = run(capsys, "init", "--model", "m", "--api-key", "sk-x")
    assert code == cli.EXIT_OK
    path = settings.CONFIG_FILE
    assert path.stat().st_mode & 0o777 == 0o600
    assert 'llm_model = "m"' in path.read_text()


def test_init_keeps_extra_body_table(capsys):
    import tomllib

    from chatdify import settings

    settings.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    settings.CONFIG_FILE.write_text('llm_extra_body = { thinking = { type = "enabled" } }\n')
    code, _, _ = run(capsys, "init", "--model", "m", "--force")
    assert code == cli.EXIT_OK
    data = tomllib.loads(settings.CONFIG_FILE.read_text())
    assert data["llm_extra_body"] == {"thinking": {"type": "enabled"}}


def test_config_masks_secrets(capsys, monkeypatch):
    monkeypatch.setenv("CHATDIFY_LLM_API_KEY", "sk-very-secret")
    code, out, _ = run(capsys, "config", "--json")
    assert code == cli.EXIT_OK
    assert "sk-very-secret" not in out
    assert json.loads(out)["llm_api_key"].endswith("***")


@pytest.mark.dify
def test_validate_examples(capsys, dify_available):
    code, out, _ = run(capsys, "validate", str(EXAMPLES / "dsl"))
    assert code == cli.EXIT_OK
    code, out, _ = run(capsys, "validate", str(EXAMPLES / "broken"), "--json")
    assert code == cli.EXIT_FAILED
    assert json.loads(out)[0]["valid"] is False
