import pytest

from chatdify.dify_compat import locator


def _fake_dify(root, version="1.11.2"):
    (root / "api" / "core" / "workflow").mkdir(parents=True)
    (root / "api" / "pyproject.toml").write_text(f'[project]\nname = "dify-api"\nversion = "{version}"\n')
    return root


def test_locate_explicit_root_and_api_dir(tmp_path):
    root = _fake_dify(tmp_path / "dify")
    for path in (root, root / "api"):
        info = locator.locate_dify(path, tmp_path / "cache", "1.11.2").info
        assert info.root == root.resolve()
        assert info.version == "1.11.2"
        assert info.version_matches


def test_explicit_path_does_not_fall_back(tmp_path):
    _fake_dify(tmp_path / "cache" / "1.11.2")
    result = locator.locate_dify(tmp_path / "missing", tmp_path / "cache")
    assert result.info is None
    assert [source for source, _ in result.tried] == ["dify_src setting"]


def test_cache_lookup_falls_back_to_other_version(tmp_path, monkeypatch):
    monkeypatch.setattr(locator, "PROJECT_ROOT", tmp_path / "no-repo")
    _fake_dify(tmp_path / "cache" / "9.9.9", version="9.9.9")
    info = locator.locate_dify(None, tmp_path / "cache", "1.11.2").info
    assert info.version == "9.9.9"
    assert not info.version_matches


def test_configured_version_wins_over_submodule(tmp_path, monkeypatch):
    monkeypatch.setattr(locator, "PROJECT_ROOT", tmp_path / "repo")
    _fake_dify(tmp_path / "repo" / "dify", version="1.11.2")
    _fake_dify(tmp_path / "cache" / "1.12.0", version="1.12.0")
    info = locator.locate_dify(None, tmp_path / "cache", "1.12.0").info
    assert (info.version, info.source) == ("1.12.0", "cache (1.12.0)")
    info = locator.locate_dify(None, tmp_path / "cache", "1.11.2").info
    assert (info.version, info.source) == ("1.11.2", "repository submodule")


def test_dify_version_from_env(monkeypatch):
    from chatdify.settings import DEFAULT_DIFY_VERSION, configure

    assert configure().dify_version == DEFAULT_DIFY_VERSION
    monkeypatch.setenv("CHATDIFY_DIFY_VERSION", "1.12.0")
    assert configure().dify_version == "1.12.0"


def test_activate_reports_missing_source(tmp_path, monkeypatch):
    monkeypatch.setattr(locator, "_active", None)
    with pytest.raises(locator.DifyUnavailableError, match="dify fetch"):
        locator.activate(tmp_path / "missing", tmp_path / "cache")


def test_layout_supported(tmp_path):
    root = _fake_dify(tmp_path / "dify")
    assert not locator.layout_supported(root)
    (root / "api" / "core" / "workflow" / "nodes").mkdir()
    (root / "api" / "core" / "workflow" / "nodes" / "node_mapping.py").write_text("")
    assert locator.layout_supported(root)


@pytest.fixture
def fresh_import(monkeypatch):
    import sys

    if locator._PROBE_MODULE in sys.modules:
        pytest.skip("a real Dify is already imported in this process")
    monkeypatch.setattr(locator, "_active", None)
    for name in [n for n in sys.modules if n == "core" or n.startswith("core.")]:
        monkeypatch.delitem(sys.modules, name)


def test_activate_reports_unsupported_layout(tmp_path, fresh_import):
    import sys

    root = _fake_dify(tmp_path / "dify", version="1.19.0")
    with pytest.raises(locator.DifyUnavailableError, match="layout is not supported"):
        locator.activate(root, tmp_path / "cache")
    assert str(root.resolve() / "api") not in sys.path


def test_activate_reports_missing_dependency(tmp_path, fresh_import):
    root = _fake_dify(tmp_path / "dify")
    (root / "api" / "core" / "workflow" / "nodes").mkdir()
    (root / "api" / "core" / "workflow" / "nodes" / "node_mapping.py").write_text("import chatdify_missing_dep\n")
    with pytest.raises(locator.DifyUnavailableError, match="dependency 'chatdify_missing_dep'.*pip install"):
        locator.activate(root, tmp_path / "cache")


def test_is_available_respects_switch():
    from chatdify import dify_compat
    from chatdify.settings import configure

    configure(dify_static_validation=False)
    assert dify_compat.is_available() is False
    assert "disabled" in dify_compat.unavailable_reason()
