"""Compact, LLM- and human-readable views of a Dify DSL, and the difference between two."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

import yaml

# Node fields that only affect how the node is shown in the Dify editor.
DISPLAY_ONLY_KEYS = frozenset({"desc", "selected"})


def _load(dsl: str) -> Dict[str, Any]:
    try:
        data = yaml.safe_load(dsl) or {}
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _graph(data: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    graph = (data.get("workflow") or {}).get("graph") or {}
    return list(graph.get("nodes") or []), list(graph.get("edges") or [])


def _label(node: Dict[str, Any]) -> str:
    d = node.get("data") or {}
    return f"{d.get('title') or node.get('id')}({d.get('type', '?')})"


def _parent(node: Dict[str, Any]) -> Optional[str]:
    return node.get("parentId") or (node.get("data") or {}).get("iteration_id") or (node.get("data") or {}).get("loop_id")


def describe(dsl: str) -> Dict[str, Any]:
    """App name and mode, start variables, nodes and how they are connected."""
    data = _load(dsl)
    nodes, edges = _graph(data)
    by_id = {n.get("id"): n for n in nodes}
    top = [n for n in nodes if not _parent(n) and (n.get("data") or {}).get("type") not in ("iteration-start", "loop-start")]
    children: Dict[str, List[str]] = {}
    for n in nodes:
        parent = _parent(n)
        if parent and (n.get("data") or {}).get("type") not in ("iteration-start", "loop-start"):
            children.setdefault(parent, []).append(_label(n))

    start = next((n for n in nodes if (n.get("data") or {}).get("type") == "start"), None)
    variables = [
        {"name": v.get("variable"), "type": v.get("type"), "required": bool(v.get("required"))}
        for v in ((start or {}).get("data") or {}).get("variables") or []
    ]

    top_ids = {n.get("id") for n in top}
    links = []
    for e in edges:
        if e.get("source") in top_ids and e.get("target") in top_ids:
            handle = e.get("sourceHandle")
            branch = f" [{handle}]" if handle and handle != "source" else ""
            links.append(f"{_label(by_id[e['source']])}{branch} → {_label(by_id[e['target']])}")

    return {
        "name": (data.get("app") or {}).get("name"),
        "mode": (data.get("app") or {}).get("mode"),
        "start_variables": variables,
        "node_count": len(nodes),
        "nodes": [
            {"id": n.get("id"), "title": (n.get("data") or {}).get("title"), "type": (n.get("data") or {}).get("type"),
             **({"children": children[n.get("id")]} if n.get("id") in children else {})}
            for n in top
        ],
        "flow": _flow(top, edges, by_id) or links,
    }


def _flow(top: List[Dict[str, Any]], edges: List[Dict[str, Any]], by_id: Dict[str, Any]) -> List[str]:
    """One "a → b → c" line for a linear graph; empty when the graph branches."""
    top_ids = {n.get("id") for n in top}
    inner = [e for e in edges if e.get("source") in top_ids and e.get("target") in top_ids]
    outs: Dict[str, List[str]] = {}
    ins: Dict[str, int] = {}
    for e in inner:
        outs.setdefault(e["source"], []).append(e["target"])
        ins[e["target"]] = ins.get(e["target"], 0) + 1
    if any(len(v) > 1 for v in outs.values()) or any(v > 1 for v in ins.values()):
        return []
    heads = [i for i in top_ids if i not in ins]
    if len(heads) != 1:
        return []
    chain, current = [], heads[0]
    while current and len(chain) <= len(top_ids):
        chain.append(_label(by_id[current]))
        current = (outs.get(current) or [None])[0]
    return [" → ".join(chain)] if len(chain) == len(top_ids) else []


def overview(dsl: str) -> str:
    """Multi-line text shown to users and to the chat agent."""
    info = describe(dsl)
    if not info["nodes"]:
        return "(empty or unparsable DSL)"
    lines = [f"{info['name']} [{info['mode']}], {info['node_count']} nodes"]
    if info["start_variables"]:
        lines.append("inputs: " + ", ".join(
            f"{v['name']}:{v['type']}{'' if v['required'] else '?'}" for v in info["start_variables"]))
    lines += info["flow"]
    for n in info["nodes"]:
        if n.get("children"):
            lines.append(f"{n['title']} contains: {', '.join(n['children'])}")
    return "\n".join(lines)


def node_detail(dsl: str, key: str) -> Optional[str]:
    """Full data of the node whose id or title matches ``key``."""
    nodes, _ = _graph(_load(dsl))
    for n in nodes:
        d = n.get("data") or {}
        if key in (n.get("id"), d.get("title")):
            return json.dumps({"id": n.get("id"), **d}, ensure_ascii=False, indent=1)
    return None


def diff(old: str, new: str) -> Dict[str, List[str]]:
    """Nodes added, removed and changed from ``old`` to ``new``, matched by id, then by type and title."""
    old_nodes, _ = _graph(_load(old))
    new_nodes, _ = _graph(_load(new))
    old_by_id = {n.get("id"): n for n in old_nodes}
    unmatched_new = []
    pairs = []
    for n in new_nodes:
        if n.get("id") in old_by_id:
            pairs.append((old_by_id.pop(n.get("id")), n))
        else:
            unmatched_new.append(n)

    def key(n):
        d = n.get("data") or {}
        return d.get("type"), d.get("title")

    old_by_key = {key(n): n for n in old_by_id.values()}
    added = []
    for n in unmatched_new:
        if key(n) in old_by_key:
            pairs.append((old_by_key.pop(key(n)), n))
        else:
            added.append(_label(n))
    changed = []
    for a, b in pairs:
        da, db = a.get("data") or {}, b.get("data") or {}
        fields = sorted(k for k in set(da) | set(db) if k not in DISPLAY_ONLY_KEYS and da.get(k) != db.get(k))
        if fields:
            changed.append(f"{_label(b)} [{', '.join(fields)}]")
    return {"added": added, "removed": [_label(n) for n in old_by_key.values()], "changed": changed}


def diff_text(changes: Dict[str, List[str]]) -> str:
    parts = [f"{name}: {', '.join(items)}" for name, items in changes.items() if items]
    return "; ".join(parts) if parts else "no node changes"
