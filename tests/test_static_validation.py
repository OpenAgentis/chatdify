"""Static validation against Dify's node entities. Skipped when Dify or chatdify[dify] is missing."""
import pytest

from chatdify import api
from conftest import EXAMPLES

pytestmark = pytest.mark.dify


@pytest.mark.parametrize("path", sorted((EXAMPLES / "dsl").glob("*.yml")), ids=lambda p: p.stem)
def test_examples_are_valid(dify_available, path):
    report = api.validate(path.read_text(encoding="utf-8"))
    assert report.static_checked
    assert report.valid, report.summary()


def test_broken_example_reports_code_node(dify_available):
    report = api.validate((EXAMPLES / "broken" / "text_summarization.yml").read_text(encoding="utf-8"))
    assert not report.valid
    assert any(issue.node_type == "code" for issue in report.issues)
    assert "error" in report.summary()


def test_parse_error_is_reported():
    report = api.validate("app: [unclosed")
    assert not report.valid
    assert report.parse_error
