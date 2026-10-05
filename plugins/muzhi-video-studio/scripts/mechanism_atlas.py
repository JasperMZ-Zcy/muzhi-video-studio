#!/usr/bin/env python3
"""Read-only mechanism references for director candidate recall and inspection."""
from __future__ import annotations

import argparse
import hashlib
import json
from functools import lru_cache
from pathlib import Path


PLUGIN = Path(__file__).resolve().parent.parent
# Optional user workspace; no private research catalog is distributed.
WORKSPACE = PLUGIN
CATALOG_REL = "assets/mechanism-atlas/catalog.json"


@lru_cache(maxsize=8)
def _catalog_cached(path_text, size, modified_ns):
    path = Path(path_text)
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if data.get("schema_version") != 1 or not isinstance(data.get("entries"), list):
        raise ValueError(f"invalid mechanism atlas: {path}")
    return data


def _catalog(plugin_root=PLUGIN):
    path = Path(plugin_root) / CATALOG_REL
    if not path.is_file():
        return {"schema_version": 1, "entries": [],
                "source_counts": {"shotcraft": 0, "agent_motion": 0, "hyperframes": 0}}
    stat = path.stat()
    return _catalog_cached(str(path), stat.st_size, stat.st_mtime_ns)


def _locate(locator, plugin_root=PLUGIN, workspace_root=WORKSPACE):
    if not isinstance(locator, dict) or locator.get("root") not in {"plugin", "workspace"}:
        raise ValueError("invalid mechanism source locator")
    base = Path(plugin_root if locator["root"] == "plugin" else workspace_root).resolve()
    relative = Path(locator.get("path", ""))
    if relative.is_absolute() or not relative.parts or any(p in {".", ".."} for p in relative.parts):
        raise ValueError("unsafe mechanism source path")
    target = (base / relative).resolve()
    if not target.is_relative_to(base):
        raise ValueError("mechanism source escapes its root")
    return target


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@lru_cache(maxsize=8)
def _entry_map_cached(path_text, size, modified_ns):
    entries = _catalog_cached(path_text, size, modified_ns)["entries"]
    ids = [e.get("id") for e in entries]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate mechanism ID in atlas")
    return {e["id"]: e for e in entries}


def _entry_map(plugin_root=PLUGIN):
    path = Path(plugin_root) / CATALOG_REL
    if not path.is_file():
        return {}
    stat = path.stat()
    return _entry_map_cached(str(path), stat.st_size, stat.st_mtime_ns)


def _detail(entry, plugin_root, workspace_root):
    source = _locate(entry["source_locator"], plugin_root, workspace_root)
    research = _locate(entry["research_locator"], plugin_root, workspace_root)
    keys = ("id", "source", "source_id", "group", "relation", "state_chain", "viewer_understanding",
            "fit", "bad_fit", "required_inputs", "adaptation", "execution_boundary", "source_version",
            "rights", "public_export_eligible", "media_observed", "media_observation_scope",
            "original_read", "capability_class",
            "research_entry_index")
    source_expected = entry["source_locator"].get("sha256")
    research_expected = entry["research_locator"].get("sha256")
    source_current = _sha(source) if source.is_file() else None
    research_current = _sha(research) if research.is_file() else None
    source_match = bool(source_expected and source_current == source_expected)
    research_match = bool(research_expected and research_current == research_expected)
    return {**{key: entry.get(key) for key in keys},
            "source_locator": entry["source_locator"], "research_locator": entry["research_locator"],
            "source_path": str(source), "source_exists": source.is_file(),
            "research_path": str(research), "research_exists": research.is_file(),
            "source_sha256": source_expected, "source_current_sha256": source_current,
            "source_sha_matches": source_match,
            "research_sha256": research_expected, "research_current_sha256": research_current,
            "research_sha_matches": research_match,
            "provenance_status": "current" if source_match and research_match else "drift_or_missing_review_required"}


def enrich_candidate(row, plugin_root=PLUGIN, workspace_root=WORKSPACE) -> dict:
    """Return a display copy; old selected/source-snapshot rows remain unchanged."""
    result = dict(row)
    entry = _entry_map(plugin_root).get(row.get("id"))
    if entry:
        result["mechanism"] = _detail(entry, plugin_root, workspace_root)
        research_terms = [entry.get(key) for key in
                          ("relation", "viewer_understanding", "fit", "required_inputs", "adaptation")]
        result["search_text"] = " ".join([str(row.get("search_text") or ""),
                                            *[str(value or "") for value in research_terms]]).strip()
    return result


def reference_rows(source, plugin_root=PLUGIN, workspace_root=WORKSPACE) -> list[dict]:
    """Register only new HF IDs; existing Shotcraft/Agent rows are enriched in place."""
    if source != "hyperframes":
        return []
    rows = []
    for entry in _catalog(plugin_root)["entries"]:
        if entry["source"] != source:
            continue
        detail = _detail(entry, plugin_root, workspace_root)
        rows.append({"id": entry["id"], "source": source, "role": "reference",
                     "capability_class": entry["capability_class"], "title": entry["title"],
                     "search_text": " ".join(str(entry.get(key) or "") for key in
                                         ("title", "relation", "viewer_understanding", "fit", "bad_fit")),
                     "path": detail["source_path"], "exists": detail["source_exists"],
                     "category": entry.get("group"), "status": "research_text_reference_only",
                     "availability": "present_text_only" if detail["source_exists"] else "source_missing",
                     "rights": entry["rights"], "public_export_eligible": False,
                     "indexed_sha256": detail["source_sha256"],
                     "mechanism": detail})
    return rows


RELATION_MAP = [
    ("查证路径与引述", "进入来源、找文、定位、原句停读；只引用原句时不虚构进站过程"),
    ("先后与依赖", "先发生和必须先满足是不同关系；并排入场可能误写依赖"),
    ("条件与分支", "条件尚未核实时保留待定；动效不得提前显示确定结果"),
    ("比较与同口径", "对照前核主体、年份、单位和口径；不同口径不能画等长柱"),
    ("数量、占比与换算", "真值驱动数字和几何；未知分钟数不能把课时画成小时"),
    ("因果与反馈", "触发、接触、响应需在画面发生；装饰性变色不证明因果"),
    ("整体与部分", "局部如何组成整体要可追踪；入场聚合不替代事实归属"),
    ("分类与归属", "标签、材料、人物各归其位；位置靠近不自动表示因果"),
    ("过程与状态转移", "起点、操作、结果需连贯；终点截图不冒充操作过程"),
    ("场景与人物反应", "预期、动作、反应支撑笑点；情绪词卡不等于人物行动"),
    ("尺度与视角", "推进/缩放为辨认对象服务；只放大不显示关系时仍是阅读"),
    ("节奏与收束", "标题、停顿、转场可简短静止；修辞包装不冒充知识解释"),
]


def outline():
    return {"purpose": "导演初筛的可选关系地图；不是刚性分类、固定镜数或语义判定器",
            "relations": [{"name": name, "distinction": note} for name, note in RELATION_MAP],
            "selection": "读完整稿和观众认识变化，再比较候选原件、反例与输入；允许原创及无库候选。"}


def read(identifier, plugin_root=PLUGIN, workspace_root=WORKSPACE):
    entry = _entry_map(plugin_root).get(identifier)
    if not entry:
        raise ValueError(f"unknown mechanism ID: {identifier}")
    return {"title": entry["title"], **_detail(entry, plugin_root, workspace_root)}


def search(query, plugin_root=PLUGIN, workspace_root=WORKSPACE, limit=20):
    terms = [t.casefold() for t in query.split() if t]
    if not terms:
        raise ValueError("search requires a query; use outline for the relation map")
    scored = []
    for entry in _catalog(plugin_root)["entries"]:
        fields = ("title", "relation", "viewer_understanding", "fit", "bad_fit", "required_inputs")
        haystack = " ".join(str(entry.get(k) or "") for k in fields).casefold()
        score = sum(haystack.count(term) for term in terms)
        if score:
            scored.append((score, entry))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["id"]))
    return {"query": query, "matches": [{"id": e["id"], "title": e["title"],
                                            "relation": e["relation"], "fit": e["fit"], "bad_fit": e["bad_fit"],
                                            "source": e["source"], "role": "reference", "recall_score": score}
                                           for score, e in scored[:limit]],
            "boundary": "Literal recall only. Zero matches do not prove no suitable mechanism; inspect source coverage, revise the query, or design an original expression."}


def validate(plugin_root=PLUGIN, workspace_root=WORKSPACE):
    catalog = _catalog(plugin_root)
    entries = catalog["entries"]
    ids = [e.get("id") for e in entries]
    errors = []
    if len(ids) != len(set(ids)):
        errors.append("duplicate IDs")
    counts = {source: sum(e.get("source") == source for e in entries) for source in ("shotcraft", "agent_motion", "hyperframes")}
    if counts != catalog.get("source_counts") or sum(counts.values()) != len(entries):
        errors.append(f"source coverage changed: {counts}")
    for entry in entries:
        if entry.get("public_export_eligible") is not False or entry.get("role") != "reference":
            errors.append(f"unsafe classification: {entry.get('id')}")
        for key in ("source_locator", "research_locator"):
            loc = entry.get(key)
            try:
                path = _locate(loc, plugin_root, workspace_root)
                if not path.is_file():
                    errors.append(f"missing {key}: {entry['id']}")
                elif loc.get("sha256") != _sha(path):
                    errors.append(f"SHA drift {key}: {entry['id']}")
            except (ValueError, OSError) as exc:
                errors.append(f"bad {key}: {entry.get('id')}: {exc}")
    return {"passed": not errors, "counts": counts, "entries": len(entries), "errors": errors,
            "boundary": "Only file integrity, coverage and rights flags; no semantic, visual or media acceptance."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("outline")
    p = sub.add_parser("search"); p.add_argument("query"); p.add_argument("--limit", type=int, default=20)
    p = sub.add_parser("read"); p.add_argument("id")
    sub.add_parser("validate")
    args = parser.parse_args(argv)
    try:
        result = (outline() if args.command == "outline" else
                  search(args.query, limit=max(1, min(args.limit, len(_catalog()["entries"])))) if args.command == "search" else
                  read(args.id) if args.command == "read" else validate())
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("passed", True) else 1
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"passed": False, "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
