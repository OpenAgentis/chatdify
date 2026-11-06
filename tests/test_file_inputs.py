"""Mapping input files onto the start node's file variables."""
import yaml

from chatdify.core.testcase_generator import TestCaseGenerator


class FakeClient:
    def upload_file(self, file_path):
        return {"upload_file": {"path": file_path}}


def _dsl(*variables):
    start = {"data": {"type": "start", "variables": [
        {"variable": name, "type": "file", "required": required} for name, required in variables
    ]}}
    return yaml.safe_dump({"workflow": {"graph": {"nodes": [start]}}})


def _extract(dsl, files):
    generator = TestCaseGenerator.__new__(TestCaseGenerator)
    generator._client = FakeClient()
    return generator._extract_file_inputs(dsl, files, "test")


def test_optional_file_variable_is_skipped_when_files_run_out():
    dsl = _dsl(("audio", False), ("notes", True))
    assert _extract(dsl, ["a.md"]) == ({"notes": {"path": "a.md"}}, None)


def test_enough_files_keep_declaration_order():
    dsl = _dsl(("audio", False), ("notes", True))
    assert _extract(dsl, ["a.mp3", "b.md"]) == (
        {"audio": {"path": "a.mp3"}, "notes": {"path": "b.md"}}, None)


def test_missing_required_file_is_an_error():
    inputs, error = _extract(_dsl(("notes", True), ("slides", True)), ["a.md"])
    assert inputs == {} and "必填" in error
