import json
import tomllib

from chatdify import cli
from chatdify import settings as settings_module
from chatdify.models.node_config.config_loader import ConfigLoader
from chatdify.models.node_config.node_config import NodeConfig
from chatdify.settings import DEFAULT_WORKFLOW_MODELS, configure, get_settings

DEFAULT_LLM = DEFAULT_WORKFLOW_MODELS["llm"]


def test_defaults_fill_model_nodes():
    loader = ConfigLoader()
    assert loader.load_node_config("llm", {"vision": {"enabled": True}}) == {"model": DEFAULT_LLM}
    assert loader.load_node_config("question-classifier", {}) == {"model": DEFAULT_LLM}
    kr = loader.load_node_config("knowledge-retrieval", {})["multiple_retrieval_config"]
    assert kr["reranking_model"] == DEFAULT_WORKFLOW_MODELS["rerank"]
    assert kr["weights"]["vector_setting"] == {
        "embedding_model_name": "BAAI/bge-m3",
        "embedding_provider_name": "langgenius/siliconflow/siliconflow",
    }
    assert loader.load_node_config("code", {}) == {}
    assert get_settings().default_workflow_models() == ["llm", "vision_llm", "rerank", "embedding"]


def test_override_replaces_given_keys_only():
    configure(workflow_llm={"provider": "langgenius/openai/openai", "name": "gpt-4o",
                            "completion_params": {"temperature": 0.7}})
    model = get_settings().workflow_model("llm")
    assert model == {"provider": "langgenius/openai/openai", "name": "gpt-4o", "mode": "chat",
                     "completion_params": {"temperature": 0.7}}
    # vision falls back to the configured text model
    assert get_settings().workflow_model("vision_llm") == model
    assert get_settings().default_workflow_models() == ["rerank", "embedding"]


def test_vision_override_on_top_of_llm():
    configure(workflow_llm={"name": "text-model"}, workflow_vision_llm={"name": "vl-model"})
    loader = ConfigLoader()
    assert loader.load_node_config("llm", {"vision": {"enabled": False}})["model"]["name"] == "text-model"
    assert loader.load_node_config("llm", {"vision": {"enabled": True}})["model"]["name"] == "vl-model"
    assert loader.load_node_config("parameter-extractor", {})["model"]["name"] == "text-model"


def test_env_json_and_toml_table(monkeypatch):
    monkeypatch.setenv("CHATDIFY_WORKFLOW_RERANK", '{"provider": "p", "model": "r"}')
    settings_module.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    settings_module.CONFIG_FILE.write_text(
        '[workflow_embedding]\nprovider = "langgenius/ollama/ollama"\nmodel = "bge-m3"\n')
    configure()
    s = get_settings()
    assert s.workflow_model("rerank") == {"provider": "p", "model": "r"}
    assert s.workflow_model("embedding") == {"provider": "langgenius/ollama/ollama", "model": "bge-m3"}


def test_configured_model_overrides_llm_output():
    configure(workflow_llm={"provider": "langgenius/openai/openai", "name": "gpt-4o"})
    generated = {"title": "LLM", "vision": {"enabled": False},
                 "model": {"provider": "whatever", "name": "llm-guess", "completion_params": {"stop": ["x"]}}}
    model = NodeConfig("llm", generated).get_node_config()["model"]
    assert (model["provider"], model["name"]) == ("langgenius/openai/openai", "gpt-4o")
    assert model["completion_params"]["stop"] == ["x"]
    assert model["completion_params"]["temperature"] == DEFAULT_LLM["completion_params"]["temperature"]


def run(capsys, *argv):
    code = cli.main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


def test_status_marks_defaults_and_reminds(capsys):
    code, out, err = run(capsys, "dify", "status", "--dify-src", "/nonexistent")
    assert code == cli.EXIT_OK
    assert "deepseek-v4-flash (langgenius/deepseek/deepseek)  [default]" in out
    assert "workflow_llm" in err and "your Dify" in err

    code, out, _ = run(capsys, "dify", "status", "--json", "--dify-src", "/nonexistent")
    assert json.loads(out)["workflow_models"]["rerank"]["source"] == "default"


def test_init_writes_workflow_llm_and_silences_reminder(capsys):
    code, _, _ = run(capsys, "init", "--model", "m", "--workflow-llm-provider", "langgenius/openai/openai",
                     "--workflow-llm-name", "gpt-4o")
    assert code == cli.EXIT_OK
    data = tomllib.loads(settings_module.CONFIG_FILE.read_text())
    assert data["workflow_llm"] == {"provider": "langgenius/openai/openai", "name": "gpt-4o"}

    code, out, err = run(capsys, "dify", "status", "--dify-src", "/nonexistent")
    assert "gpt-4o (langgenius/openai/openai)\n" in out
    assert "workflow_llm," not in err and "workflow_rerank" in err
