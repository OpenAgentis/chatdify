"""README commands must parse and only reference files that ship with the repository."""
import re
import shlex

import pytest

from chatdify import cli
from conftest import REPO_ROOT

DOCS = ["README.md", "README_zh.md", "examples/README.md"]


def _commands(doc: str):
    text = (REPO_ROOT / doc).read_text(encoding="utf-8")
    for block in re.findall(r"```bash\n(.*?)```", text, re.S):
        for line in block.replace("\\\n", " ").splitlines():
            line = line.split("   #")[0].strip()
            if line.startswith("chatdify "):
                yield line


CASES = [(doc, cmd) for doc in DOCS for cmd in _commands(doc)]


def test_readmes_have_examples():
    assert {doc for doc, _ in CASES} == set(DOCS)


@pytest.mark.parametrize("doc,command", CASES, ids=[f"{d}:{c[:60]}" for d, c in CASES])
def test_readme_command(doc, command):
    argv = shlex.split(command.split(">")[0])[1:]
    cli.build_parser().parse_args(argv)
    for arg in argv:
        if arg.startswith(("examples/", "test_cases/")):
            assert (REPO_ROOT / arg).exists(), f"{doc}: {arg} does not exist"
