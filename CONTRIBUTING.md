# Contributing

Thanks for helping improve ChatDify. Issues and pull requests are welcome in English or Chinese.

## Development setup

```bash
git clone --recurse-submodules --shallow-submodules https://github.com/OpenAgentis/chatdify.git
cd chatdify
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dify,dev]"
pre-commit install
```

## Checks

```bash
ruff check chatdify tests
pytest -q                         # offline; Dify tests are skipped if Dify is unavailable
chatdify validate examples/dsl    # static validation of the examples
```

Tests must not call real LLMs or a Dify instance. Stub the LLM-backed parts instead (see `tests/test_engine_offline.py`).

## Where things live

- **Node validation rules**: `chatdify/core/node_validator/<node_type>.py`. Each validator builds Dify's own node entity first, then applies extra checks. Add a regression DSL under `examples/` or a unit test when you fix a rule.
- **Knowledge base**: `chatdify/kg/node_reference_v4/<node_type>/` (usage notes, samples, common errors) and `chatdify/kg/dsl_template_v3/` (templates). Never commit real API keys, webhook URLs or internal hostnames in templates; use `YOUR_API_KEY`.
- **Prompts**: `chatdify/prompts/`.

## Supporting a new Dify version

1. Check out the new tag in the `dify` submodule (or use `chatdify dify fetch --version X`).
2. Run `pytest` and `chatdify validate examples/dsl`. Import errors usually point to moved modules in `chatdify/dify_compat/entities.py`, which is the only file that imports Dify symbols.
3. Compare `dify/api/pyproject.toml` pins with the `dify` extra in `pyproject.toml`.
4. Add the version to `SUPPORTED_DIFY_VERSIONS` in `chatdify/dify_compat/locator.py` and to the version table under "Upgrading Dify" in `README.md` and `README_zh.md`.

## Pull requests

- Keep PRs focused, describe the user-visible change, and update the README when behaviour or flags change.
- Make sure CI passes: lint, tests with and without Dify, packaging, and the gitleaks secret scan.
