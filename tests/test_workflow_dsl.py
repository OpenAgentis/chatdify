import pytest
import yaml

from chatdify.models.workflow import Workflow, WorkflowErrors, ValidationResult
from conftest import EXAMPLES

EXAMPLE_DSLS = sorted((EXAMPLES / "dsl").glob("*.yml"))


@pytest.mark.parametrize("path", EXAMPLE_DSLS, ids=lambda p: p.stem)
def test_dsl_round_trip_keeps_graph(path):
    source = yaml.safe_load(path.read_text(encoding="utf-8"))
    workflow = Workflow()
    workflow.from_dsl(path.read_text(encoding="utf-8"))
    out = yaml.safe_load(workflow.to_dsl())

    src_graph, out_graph = source["workflow"]["graph"], out["workflow"]["graph"]
    assert {n["id"] for n in out_graph["nodes"]} == {n["id"] for n in src_graph["nodes"]}
    assert {(e["source"], e["target"]) for e in out_graph["edges"]} == {
        (e["source"], e["target"]) for e in src_graph["edges"]
    }
    assert out["app"]["mode"] == source["app"]["mode"]


def test_invalid_dsl_raises():
    with pytest.raises(Exception):
        Workflow().from_dsl("app: [unclosed")


def test_static_is_valid():
    assert WorkflowErrors().static_is_valid()
    errors = WorkflowErrors(static_errors=[ValidationResult(is_valid=True, error_type="edge", error_message="x")])
    assert errors.static_is_valid()
    errors.static_errors.append(ValidationResult(is_valid=False, error_type="node", error_message="bad"))
    assert not errors.static_is_valid()
