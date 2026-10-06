#!/usr/bin/env python3
"""Bounded cross-library discovery and project-local preview handoff.

Search is recall, not a semantic decision. Only the project owner chooses and
adapts a candidate in the existing motion plan. No metadata is shell code.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
import re
import shutil
import subprocess
import struct
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from urllib.parse import unquote, urlsplit
from mechanism_atlas import enrich_candidate, reference_rows
from expression_contract import validate_segment


PLUGIN = Path(__file__).resolve().parent.parent
# Optional user-supplied workspace. The public package never assumes a
# creator's private project or centrally managed business library is present.
WORKSPACE = Path(os.environ.get("MUZHI_VIDEO_WORKSPACE", str(PLUGIN))).expanduser().resolve()
CENTRAL = WORKSPACE / "optional-libraries/central/index.json"
HISTORICAL = WORKSPACE / "optional-libraries/historical/index.json"
HISTORICAL_SHELF = WORKSPACE / "optional-libraries/historical/reviewed.md"
SHOTCRAFT = PLUGIN / "assets/shotcraft/full-index.json"
SHOTCRAFT_CODE_STUDY = PLUGIN / "assets/shotcraft/pinned-code-study.json"
AGENT = WORKSPACE / "optional-libraries/agent-motion/catalog.json"
SEMANTIC_SCENE = PLUGIN / "assets/semantic-scenes/src/SemanticScene.tsx"
SEMANTIC_RECORD = PLUGIN / "assets/semantic-scenes/asset-record.json"
INTERACTIVE_RECORD = PLUGIN / "assets/interactive-scenes/asset-record.json"
INTERACTIVE_FRAME = PLUGIN / "assets/interactive-scenes/src/frame.tsx"
INTERACTIVE_FRAME_V2_SNAPSHOT = PLUGIN / "assets/interactive-scenes/versions/frame.tsx"
INTERACTIVE_TRIAL_SNAPSHOT = PLUGIN / "assets/interactive-scenes/versions/asset-record-actor-v2.snapshot.json"
FOUR_RECORD = PLUGIN / "assets/four-family-mechanisms/asset-record.json"
FOUR_COMMON = PLUGIN / "assets/four-family-mechanisms/src/common.tsx"
FOUR_CAUSE_BASE = PLUGIN / "assets/four-family-mechanisms/src/CauseActor.tsx"
STUDY_WORLD_RECORD = PLUGIN / "assets/study-world-v2/asset-record.json"
EDITORIAL_PRIMITIVE_RECORD = PLUGIN / "assets/editorial-primitives/asset-record.json"
SEMANTIC_ACTION_RECORD = PLUGIN / "assets/semantic-actions/asset-record.json"
HANZI_TRACE_RECORD = PLUGIN / "assets/hanzi-trace/asset-record.json"
OWNED_VISUAL_RECORD = PLUGIN / "assets/owned-visual-layers/asset-record.json"

# These are entry points, not duplicated library records or claims of readiness.
SOURCES = {
    "shotcraft": (SHOTCRAFT, "Apache-2.0 text mechanisms and authored bounded observations; not a renderer"),
    "shotcraft_pilot": (PLUGIN / "assets/shotcraft/templates/knowledge-pilot/render-sample.mjs", "three generic example components"),
    "semantic_action": (SEMANTIC_ACTION_RECORD, "seven locally authored source units; project adaptation and actual media review required"),
}
ROLES = {
    "visual": "static", "motion-clip": "static", "remotion-template": "adaptable_code",
    "external-reference": "reference", "production-contract": "method",
    "prompt-template": "method", "audio": "static", "caption-template": "adaptable_code",
}
SHA = re.compile(r"[0-9a-fA-F]{64}\Z")
COMPOSITION = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,79}\Z")
MEDIA_EXT = {".mp4", ".mov", ".webm"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
REGISTERED_COMPONENT_SYMBOLS = {
    "semantic_action:EvidenceJourney": "EvidenceJourney",
    "semantic_action:PaperActionTheater": "PaperActionTheater",
    "semantic_action:ObjectReflow": "ObjectReflow",
    "semantic_action:TimeStructure": "TimeStructure",
    "semantic_action:DataMorph": "DataMorph",
    "semantic_action:UnitDuration": "UnitDuration",
    "semantic_action:RowCanvasTransfer": "RowCanvasTransfer",
    "semantic_action:FocusHandoff": "FocusHandoff",
    "semantic_action:PolarContourMorph": "PolarContourMorph",
    "semantic_action:CountParticleFill": "CountParticleFill",
    "hanzi_trace:HanziTrace": "HanziTrace",
    "study_world:StudyWorldVisualV2": "StudyWorld",
    "interactive_scene:BrowserActor": "BrowserActor",
    "interactive_scene:PhoneActorFlexible": "PhoneActorFlexible",
}
TERM_FAMILIES = (
    ("比较", "对比", "对照", "compare", "comparison", "contrast"),
    ("条件", "前提", "限制", "condition", "conditional", "constraint"),
    ("分支", "分流", "branch", "fork", "split"),
    ("流程", "时间", "顺序", "timeline", "process", "sequence", "step"),
    ("手机", "设备", "机身", "phone", "device", "screen"),
    ("聊天", "消息", "输入", "发送", "接收", "chat", "message", "typing"),
    ("网页", "浏览器", "网站", "进站", "文章", "browser", "website", "page"),
    ("滚动", "停位", "滚屏", "scroll", "brake"),
    ("游标", "光标", "指针", "点击", "cursor", "pointer", "click"),
    ("镜头", "相机", "放大", "推进", "景别", "camera", "zoom", "dolly"),
    ("层级", "纵深", "前景", "背景", "视差", "depth", "layer", "parallax"),
    ("变形", "形变", "接触", "碰撞", "反馈", "morph", "impact", "trigger"),
    ("转场", "接力", "共享元素", "穿越", "transition", "shared", "travel"),
)
MODE_LABELS = {"local_remotion": "本地代码动效", "manual_adaptation": "人工改编后制作",
               "static_composite": "静态素材合成", "local_hyperframes": "本地代码场景",
               "external_backend": "外部后端待核", "direct_render": "直接渲染待核"}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def sha_file(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def local_file(root, name):
    if not isinstance(name, str) or not name.strip():
        raise ValueError("project-relative file path required")
    rel = Path(name)
    if rel.is_absolute() or any(part in (".", "..") for part in rel.parts):
        raise ValueError("unsafe project-relative path")
    path = root
    for part in rel.parts:
        path /= part
        if path.is_symlink():
            raise ValueError("symlink path forbidden")
    if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"missing project file: {name}")
    return path


def json_file(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))








def _shotcraft_rows():
    for item in json_file(SHOTCRAFT).get("cards", []):
        rid = item.get("id")
        if not rid:
            continue
        path = PLUGIN / str(item.get("full_card_path", ""))
        yield {"id": "shotcraft:" + rid, "source": "shotcraft", "role": "reference",
               "capability_class": "text_mechanism_not_renderer",
               "title": item.get("summary") or rid,
               "search_text": " ".join(str(item.get(k, "")) for k in ("summary", "use_cases", "category")) + " " + " ".join(item.get("tags", [])),
               "path": str(path), "exists": path.is_file(), "category": item.get("category"),
               "status": "local_text_reference", "availability": "present_text_only" if path.is_file() else "card_missing",
               "rights": "source card and project adaptation review; card/gallery are not rendered project media",
               "indexed_sha256": item.get("local_card_sha256")}




def _project_component_rows(source, base, definitions):
    for name, title, purpose in definitions:
        path = base / (name + ".tsx")
        yield {"id": source + ":" + name, "source": source, "role": "adaptable_code",
               "capability_class": "project_code_requires_adaptation",
               "title": title, "mechanism_name": name,
               "search_text": name + " " + title + " " + purpose,
               "path": str(path), "exists": path.is_file(), "category": "project_example_component",
               "status": "example_source_not_general_template", "availability": "present" if path.is_file() else "source_missing",
               "rights": "bundled locally authored example source under repository MIT; adapt facts, design and timing before use"}


def _shotcraft_pilot_rows():
    base = PLUGIN / "assets/shotcraft/templates/knowledge-pilot/src"
    return _project_component_rows("shotcraft_pilot", base, (
        ("LayeredQuestionCard", "分层提问卡", "问题逐层揭示 阅读停留 question reveal"),
        ("TimelineProgress", "时间轴推进", "顺序 游标 时间线 progression timeline step"),
        ("ConditionComparison", "条件对照点群", "条件 前提 对比 比较 分支 分流 非数据点群 condition comparison branch split"),
    ))














def _semantic_action_rows():
    record = json_file(SEMANTIC_ACTION_RECORD)
    titles = {"EvidenceJourney": "多站真实来源与源像素读窗", "PaperActionTheater": "稳定物件身份、纸面接触与反应",
              "ObjectReflow": "稳定对象按给定分类重排与连线", "TimeStructure": "同域连续、碎片与恢复时间结构",
              "DataMorph": "同源值与坐标轴共同变化", "UnitDuration": "同数课时的分钟到小时与若按假设对照",
              "RowCanvasTransfer": "同一条目从列表行进入画布并留空槽",
              "FocusHandoff": "旧景退焦与新景收焦的可变输入交棒",
              "PolarContourMorph": "闭合星形轮廓的同角径向形变",
              "CountParticleFill": "每粒明确单位的整数数量筑柱",
              "SceneCoordinate": "同一坐标投影的相机、光标与原像素停滚纯函数",
              "ChartGeometry": "堆叠分母与曲线端点读数同源纯函数",
              "PathArc": "贝塞尔时间进度与已走弧长分离纯函数"}
    for entry in record.get("entries", []):
        path = SEMANTIC_ACTION_RECORD.parent / entry["path"]
        is_helper = path.stem in {"SceneCoordinate", "ChartGeometry", "PathArc"}
        yield {"id": entry["id"], "source": "semantic_action", "role": "adaptable_code_helper" if is_helper else "adaptable_code",
               "capability_class": "pure_geometry_helper_not_jsx_scene" if is_helper else "source_only_project_adaptation_required",
               "title": titles[path.stem], "search_text": entry["search_text"],
               "path": str(path), "exists": path.is_file(), "category": record["asset_type"],
               "status": "project_adaptation_required", "availability": "present_adaptable_source" if path.is_file() else "source_missing",
               "rights": record["rights"], "record_sha256": sha_file(SEMANTIC_ACTION_RECORD),
               "indexed_sha256": entry["sha256"], "source_project": record["source_project"],
               "reuse_conditions": record["reuse_conditions"], "dependencies": record["dependencies"],
               "input_contract": entry.get("input_contract"),
               "bad_fit": entry.get("bad_fit"), "execution_boundary": entry.get("execution_boundary"),
               "examples": entry.get("examples", []),
               "public_export_eligible": entry.get("public_export_eligible") is True,
               "use_boundary": "Bind original source SHA, project code/props/source media hashes and actual frame evidence; never claim navigation or contact from index alone"}






ROW_LOADERS = {"shotcraft": _shotcraft_rows,
               "shotcraft_pilot": _shotcraft_pilot_rows,
               "semantic_action": _semantic_action_rows}
ENTRY_ROLES = {}


def _entry_row(source):
    path, boundary = SOURCES[source]
    return {"id": source + ":entry", "source": source, "role": ENTRY_ROLES[source],
            "capability_class": "method_or_backend_entry_not_scene",
            "title": source.replace("_", " "), "search_text": source.replace("_", " ") + " " + boundary,
            "path": str(path), "exists": path.exists(), "status": "entry_only_not_run",
            "rights": boundary, "category": "capability_entry"}


def source_status():
    return [{"source": name, "path": str(path), "exists": path.exists(), "role_and_boundary": boundary,
             "records_are_dynamic": name in ROW_LOADERS} for name, (path, boundary) in SOURCES.items()]


def _present_candidate(row):
    """Current human-facing trial state; selected rows stay frozen for old SHA bindings."""
    item = {key: value for key, value in enrich_candidate(row, PLUGIN, WORKSPACE).items() if key != "search_text"}
    if row["source"] != "interactive_scene":
        return item
    record = json_file(INTERACTIVE_RECORD)
    entry = next((e for e in record.get("entries", []) if e.get("id") == row["id"]), None)
    if not entry:
        return item
    item["current_availability"] = entry.get("availability")
    if row["id"] == "interactive_scene:PhoneActor":
        item["title"] = "手机对话旧版V2｜冻结2/4/6条"
        item["version_note"] = "Existing project SHA and preview remain bound here; prefer PhoneActorFlexible for new scripts."
    elif row["id"] == "interactive_scene:BrowserActor":
        item["title"] = "同源网页查证V2｜固定已试渲源"
        item["version_note"] = "Bounded local silent trial; new sources still require per-project evidence and review."
    else:
        item["title"] = "手机对话新版｜允许2–6条"
        item["version_note"] = "New-script candidate; three/five-message render and visual review pending."
    trial = next((e for e in record.get("trial_evidence", []) if e.get("entry_id") == row["id"]), None)
    if trial and trial.get("source_sha256", "").lower() == row.get("indexed_sha256", "").lower():
        item["bounded_trial"] = {"media": trial["media"], "media_sha256": trial["media_sha256"], "scope": trial["scope"]}
    return item


def _term_present(word, haystack):
    if word.isascii() and word.isalnum():
        return bool(re.search(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])", haystack))
    return word in haystack


def discover(terms=(), role=None, per_source=6, include_missing=True):
    requested = [str(word).casefold() for word in terms if str(word).strip()]
    words = list(requested)
    for word in requested:
        family = next((family for family in TERM_FAMILIES if word in family), None)
        if family:
            words.extend(alias for alias in family if alias not in words)
    if per_source < 0:
        raise ValueError("per_source must be >= 0")
    groups = []
    for source in SOURCES:
        loader = ROW_LOADERS.get(source)
        path = SOURCES[source][0]
        if not path.exists():
            groups.append({"source": source, "error": "index missing", "total_matches": 0, "items": []})
            continue
        rows = []
        seen_duplicates = set()
        for raw in loader() if loader else [_entry_row(source)]:
            item = enrich_candidate(raw, PLUGIN, WORKSPACE)
            if role and item["role"] != role:
                continue
            if not include_missing and not item["exists"]:
                continue
            haystack = " ".join([item["id"], str(item["title"]), item["search_text"]]).casefold()
            score = 3 * sum(_term_present(word, haystack) for word in requested)
            score += sum(_term_present(word, haystack) for word in words if word not in requested)
            if words and not score:
                continue
            if item.get("duplicate_of"):
                continue
            duplicate_group = item.get("duplicate_group")
            if duplicate_group:
                if duplicate_group in seen_duplicates:
                    continue
                seen_duplicates.add(duplicate_group)
            rows.append((score, item))
        rows.sort(key=lambda row: (-row[0], 0 if row[1]["id"] == "interactive_scene:PhoneActorFlexible" else 1, row[1]["id"]))
        groups.append({"source": source, "total_matches": len(rows),
                       "items": [_present_candidate(item) for _, item in (rows if per_source == 0 else rows[:per_source])]})
    return {"groups": groups, "sources": source_status(),
            "requested_terms": requested, "expanded_lexical_terms": words,
            "boundary": "Per-source lexical recall with listed synonyms only; the project owner reads selected sources and decides semantics, rights and adaptation."}


def search_receipt(terms, role=None, per_source=2):
    """Compact reproducible receipt for the existing search, not proof of reading."""
    if (not isinstance(terms, list) or not 1 <= len(terms) <= 6 or
            any(not isinstance(term, str) or not term.strip() or len(term) > 80 for term in terms)):
        raise ValueError("search receipt needs one to six non-empty terms")
    if role is not None and (not isinstance(role, str) or not role.strip()):
        raise ValueError("search receipt role must be non-empty or null")
    if type(per_source) is not int or not 1 <= per_source <= 6:
        raise ValueError("search receipt per_source must be 1..6")
    found = discover(terms, role, per_source, True)
    matched_sources = {group["source"] for group in found["groups"] if group["total_matches"]}
    # Unmatched indexes cannot affect this query unless they gain a match,
    # which changes the result list. Avoid invalidating a plan for an unrelated
    # trial-note update elsewhere in the catalog. Zero matches bind all sources.
    relevant_sources = matched_sources or set(SOURCES)
    indexes = {name: sha_file(path) if path.is_file() else None
               for name, (path, _) in SOURCES.items() if name in relevant_sources}
    results = []
    for group in found["groups"]:
        for item in group["items"]:
            identity = candidate_identity(item["id"])
            results.append({"id": item["id"], "sha256": identity["current_sha256"],
                            "source_state": identity["source_state"]})
    return {"terms": terms, "role": role, "per_source": per_source,
            "index_digest_sha256": digest(indexes), "results": results}


def selected(ids):
    wanted = list(ids)
    if not wanted or len(wanted) > 8:
        raise ValueError("read accepts one to eight candidate IDs")
    found = {}
    for source in {rid.split(":", 1)[0] for rid in wanted}:
        loader = ROW_LOADERS.get(source)
        if source not in SOURCES or not SOURCES[source][0].exists():
            raise ValueError("unknown or missing source: " + source)
        for row in loader() if loader else [_entry_row(source)]:
            if row["id"] in wanted:
                found[row["id"]] = row
    if set(wanted) != set(found):
        raise ValueError("unknown candidate ID: " + ", ".join(set(wanted) - set(found)))
    return [found[rid] for rid in wanted]


def candidate_identity(resource_id):
    """Current indexed identity for one declared candidate, without reading media."""
    row = selected([resource_id])[0]
    path = Path(row["path"]) if row.get("path") else None
    current = sha_file(path) if path and path.is_file() else None
    indexed = row.get("indexed_sha256")
    mechanism = enrich_candidate(row, PLUGIN, WORKSPACE).get("mechanism")
    if isinstance(mechanism, dict) and mechanism.get("source_sha256"):
        indexed = mechanism["source_sha256"]
    return {"resource_id": resource_id, "source": row["source"], "role": row.get("role"),
            "source_state": "missing" if current is None else
                            "drift" if indexed and current != indexed.lower() else "current",
            "current_sha256": current, "indexed_sha256": indexed,
            "source_path": str(path) if path else None}


def read(ids):
    result = []
    code_study = json_file(SHOTCRAFT_CODE_STUDY) if SHOTCRAFT_CODE_STUDY.is_file() else None
    for row in selected(ids):
        item = enrich_candidate(dict(row), PLUGIN, WORKSPACE)
        if row["source"] == "interactive_scene":
            item.update(_present_candidate(row))
        if item.get("examples"):
            checked = []
            for example in item["examples"]:
                media = example.get("media", {}) if isinstance(example, dict) else {}
                try:
                    path = local_file(WORKSPACE.resolve(), media.get("path"))
                    current = sha_file(path)
                except (ValueError, OSError, TypeError):
                    current = None
                checked.append({**example, "media_exists": current is not None,
                                "media_sha_matches": bool(current and current == str(media.get("sha256", "")).lower())})
            item["examples"] = checked
        path = Path(row["path"]) if row.get("path") else None
        if path and path.is_file() and path.suffix.lower() in {".md", ".txt", ".json", ".tsx", ".ts", ".py"}:
            if path.stat().st_size > 128_000:
                item["text_boundary"] = "selected file exceeds 128 KiB; read directly after review"
            else:
                item["text"] = path.read_text(encoding="utf-8-sig", errors="replace")
                item["current_sha256"] = sha_file(path)
                item["indexed_hash_matches"] = not row.get("indexed_sha256") or row["indexed_sha256"].lower() == item["current_sha256"]
                item["reading_receipt"] = {"reading_status": "read", "source_sha256": item["current_sha256"],
                                           "read_scope": "complete_text", "usage_kind": "reference_only"}
        if row["source"] == "shotcraft":
            card_study = code_study.get("cards", {}).get(row["id"]) if isinstance(code_study, dict) else None
            source_table = code_study.get("sources", {}) if isinstance(code_study, dict) else {}
            paths = card_study.get("source_paths") if isinstance(card_study, dict) else None
            if (not isinstance(paths, list) or not paths or
                    card_study.get("original_text_sha256") != item.get("current_sha256") or
                    code_study.get("upstream_commit") != json_file(SHOTCRAFT).get("upstream", {}).get("commit") or
                    any(not isinstance(source_table.get(source_path), dict) for source_path in paths)):
                item["source_code_study"] = {"status": "missing_or_drifted", "boundary": "Do not use stale source notes; verify current card and pinned study."}
            else:
                observations = []
                for observation in card_study.get("bounded_gallery_observations", []):
                    if not isinstance(observation, dict):
                        continue
                    observations.append({**observation,
                                         "record_current_sha_matches": None,
                                         "record_provenance_scope": "authored public metadata; original research files are not distributed"})
                item["source_code_study"] = {
                    "status": "pinned_source_text_fully_reviewed_not_executed",
                    "upstream_commit": code_study["upstream_commit"],
                    "rights_boundary": code_study["rights_boundary"],
                    "execution_boundary": code_study["execution_boundary"],
                    "source_files": [{"path": source_path, **source_table[source_path]} for source_path in paths],
                    "bounded_gallery_observations": observations,
                    "gallery_observation_boundary": code_study["gallery_observation_boundary"],
                    "provenance_boundary": code_study.get("provenance_boundary"),
                    "upstream_source_or_media_bundled": False,
                    "same_version_gallery_media_verified": False,
                }
        elif path and path.is_file() and path.suffix.lower() in IMAGE_EXT:
            item["current_sha256"] = sha_file(path)
            item["indexed_hash_matches"] = not row.get("indexed_sha256") or row["indexed_sha256"].lower() == item["current_sha256"]
            item["reading_receipt"] = {"reading_status": "asset_identity_verified", "source_sha256": item["current_sha256"],
                                       "read_scope": "binary_identity_only; no motion observation", "usage_kind": "reference_only"}
        provenance = item.get("source_provenance")
        if isinstance(provenance, dict) and isinstance(provenance.get("path"), str):
            try:
                rel = Path(provenance["path"])
                origin = (WORKSPACE / rel).resolve()
                item["provenance_identity_verified"] = (not rel.is_absolute() and ".." not in rel.parts and
                    origin.is_relative_to(WORKSPACE.resolve()) and origin.is_file() and
                    sha_file(origin) == str(provenance.get("sha256", "")).lower())
            except (OSError, ValueError):
                item["provenance_identity_verified"] = False
        project_code = item.get("project_code_example")
        if isinstance(project_code, dict):
            checks = {}
            refs = {"code": project_code, "media": project_code.get("media"),
                    "lineage": project_code.get("lineage"), "review": project_code.get("review")}
            for i, ref in enumerate(project_code.get("inputs", [])):
                refs[f"input_{i}"] = ref
            for i, ref in enumerate(project_code.get("render_receipts", [])):
                refs[f"render_receipt_{i}"] = ref
            previous = project_code.get("previous_example")
            if isinstance(previous, dict):
                refs["previous_baseline"] = previous.get("baseline")
                refs["previous_media"] = previous.get("media")
            for label, ref in refs.items():
                try:
                    checks[label] = (isinstance(ref, dict) and isinstance(ref.get("path"), str) and
                        sha_file(local_file(WORKSPACE.resolve(), ref["path"])) == str(ref.get("sha256", "")).lower())
                except (OSError, ValueError, TypeError):
                    checks[label] = False
            item["project_code_example_identity"] = checks
        mechanism = item.get("mechanism") if isinstance(item.get("mechanism"), dict) else {}
        verified_examples = [example for example in item.get("examples", []) if isinstance(example, dict) and
                             example.get("media_exists") is True and example.get("media_sha_matches") is True]
        source = row["source"]
        observed = (item.get("source_code_study", {}).get("bounded_gallery_observations", [])
                    if source == "shotcraft" else [])
        item["learning_evidence"] = {
            "source_level": "current_original_readable" if item.get("indexed_hash_matches") is True else
                            "current_source_unread_or_drifted",
            "historical_research_read_scope": mechanism.get("original_read"),
            "capability_class": item.get("capability_class") or mechanism.get("capability_class") or row.get("role"),
            "execution_level": "adaptable_bundled_code" if row.get("role") == "adaptable_code" else
                               "adaptable_bundled_code_helper" if row.get("role") == "adaptable_code_helper" else
                               "method_or_text_not_renderer" if row.get("role") in {"reference", "method"} else
                               "asset_or_record_requires_project_adapter",
            "bounded_project_media_count": len(verified_examples),
            "upstream_demo_source": "not_bundled_in_this_plugin" if source == "shotcraft" else "not_established_here",
            "upstream_source_media_same_version": "unverified",
            "current_pass_original_demo_media_observed": bool(observed),
            "bounded_live_gallery_style_observations": len(observed),
            "bounded_gallery_observation_record_count": len(observed),
            "bounded_gallery_unique_style_count": len({entry.get("style_id") for entry in observed
                                                       if isinstance(entry, dict) and entry.get("style_id")}),
            "media_observation_scope": "bounded_live_gallery_visual_not_same_version" if observed else
                                       mechanism.get("media_observation_scope") or item.get("media_observation_scope"),
            "boundary": "Source read, demo availability, same-version media, project execution and normal-speed quality are separate; bounded examples do not certify another script."
        }
        result.append(item)
    return result


def core_plan(plan):
    clone = json.loads(json.dumps(plan, ensure_ascii=False))
    for item in clone.get("segments", []):
        if isinstance(item, dict):
            item.pop("preview_binding", None)
    return clone


def _preview_identity_version(plan):
    value = plan.get("preview_identity_version", 1)
    if type(value) is not int or value not in (1, 2):
        raise ValueError("preview_identity_version must be 1 or 2")
    return value


def _shared_preview_context(plan):
    keys = ("source_script", "source_sha256", "design_source", "design_sha256",
            "srt_source", "srt_sha256", "authored_cues", "timebase_kind", "semantic_contract_version",
            "protected_cue_groups", "srt_exclusions", "audio_source", "audio_sha256",
            "audio_sample_rate", "audio_presentation_samples", "style_intent", "project_kind")
    return {key: plan.get(key) for key in keys if key in plan}


def _segment_preview_core(plan, sid):
    segments = [item for item in plan.get("segments", []) if isinstance(item, dict)]
    index = next((i for i, item in enumerate(segments) if item.get("id") == sid), None)
    if index is None:
        raise ValueError("segment ID missing")
    segment = dict(segments[index])
    segment.pop("preview_binding", None)
    previous = segments[index - 1] if index > 0 else None
    following = segments[index + 1] if index + 1 < len(segments) else None
    adjacency = {
        "previous": {"id": previous.get("id"), "exit": (previous.get("continuity") or {}).get("exit"),
                     "next_segment_id": (previous.get("continuity") or {}).get("next_segment_id")} if previous else None,
        "next": {"id": following.get("id"), "entry": (following.get("continuity") or {}).get("entry")} if following else None,
    }
    return {"segment": segment, "adjacent_handoff": adjacency}


def _segment_input_scope_issues(plan, sid, impl):
    if impl.get("input_scope") != "segment":
        return ["preview identity v2 requires a truthful segment input closure"]
    inputs = impl.get("inputs")
    if not isinstance(inputs, list):
        return ["implementation.inputs must be a list"]
    paths = [item.get("path") for item in inputs if isinstance(item, dict)]
    errors = []
    if len(paths) != len(inputs) or len(set(paths)) != len(paths):
        errors.append("segment input paths must be distinct bounded references")
    own_props = impl.get("props")
    if own_props is not None and own_props not in paths:
        errors.append("segment props must be a hashed input")
    for other in plan.get("segments", []):
        if not isinstance(other, dict) or other.get("id") == sid:
            continue
        their_impl = (other.get("chosen_resource") or {}).get("implementation") or {}
        their_props = their_impl.get("props")
        if isinstance(their_props, str) and their_props != own_props and their_props in paths:
            errors.append("segment closure includes another segment's props: " + their_props)
    return errors


def affected_scope(before, after):
    """Predict conservative re-render/review scope without changing either plan."""
    before_segments = {item.get("id"): item for item in before.get("segments", []) if isinstance(item, dict)}
    after_segments = {item.get("id"): item for item in after.get("segments", []) if isinstance(item, dict)}
    ids = [item.get("id") for item in after.get("segments", []) if isinstance(item, dict)]
    shared_changed = digest(_shared_preview_context(before)) != digest(_shared_preview_context(after))
    changed = {sid for sid in set(before_segments) | set(after_segments)
               if sid not in before_segments or sid not in after_segments or
               digest({key: value for key, value in before_segments[sid].items() if key != "preview_binding"}) !=
               digest({key: value for key, value in after_segments[sid].items() if key != "preview_binding"})}
    def render_core(item):
        chosen = item.get("chosen_resource") or {}
        fields = ("spoken_text", "srt_cue_ids", "srt_timecode", "authored_timecode", "visual_route",
                  "visual_action", "reading_plan", "continuity")
        return {**{key: item.get(key) for key in fields},
                "resource_id": chosen.get("resource_id"), "implementation": chosen.get("implementation")}
    render_changed = {sid for sid in changed if sid not in before_segments or sid not in after_segments or
                      digest(render_core(before_segments[sid])) != digest(render_core(after_segments[sid]))}
    if shared_changed:
        rerender = set(ids)
        review = set(ids)
    else:
        rerender = set(render_changed)
        review = set(changed)
        for index, sid in enumerate(ids):
            if sid in changed:
                if index > 0:
                    review.add(ids[index - 1])
                if index + 1 < len(ids):
                    review.add(ids[index + 1])
    return {"shared_context_changed": shared_changed, "rerender_segments": [sid for sid in ids if sid in rerender],
            "review_segments": [sid for sid in ids if sid in review],
            "rebind_current_board": shared_changed or bool(changed),
            "boundary": "Conservative dependency scope; actual visual and voice effects still require director review"}


def _segment(plan, sid):
    matches = [item for item in plan.get("segments", []) if isinstance(item, dict) and item.get("id") == sid]
    if len(matches) != 1:
        raise ValueError("segment ID missing or duplicated")
    return matches[0]


def _chosen(segment):
    chosen = segment.get("chosen_resource")
    if not isinstance(chosen, dict) or not chosen.get("resource_id") or not chosen.get("reason"):
        raise ValueError("chosen_resource requires resource_id and reason")
    options = segment.get("resource_options")
    if not isinstance(options, list) or chosen["resource_id"] not in [item.get("resource_id") for item in options if isinstance(item, dict)]:
        raise ValueError("chosen_resource ID is not in resource_options")
    impl = chosen.get("implementation")
    if not isinstance(impl, dict) or any(not isinstance(impl.get(key), str) or not impl[key].strip() for key in ("mode", "adaptation", "fallback")):
        raise ValueError("chosen_resource.implementation needs mode, adaptation, fallback")
    inputs = impl.get("inputs")
    if not isinstance(inputs, list):
        raise ValueError("implementation.inputs must be a list")
    return chosen, impl


def _candidate_snapshot(resource_id):
    source = resource_id.split(":", 1)[0]
    if ":" not in resource_id or source not in SOURCES:
        return None  # Project-original component; its source belongs in implementation.inputs.
    row = selected([resource_id])[0]
    path = Path(row["path"]) if row.get("path") else None
    current = sha_file(path) if path and path.is_file() else None
    indexed = row.get("indexed_sha256")
    if indexed and current and indexed.lower() != current:
        raise ValueError("selected library source differs from its indexed SHA-256")
    frozen = json_file(INTERACTIVE_TRIAL_SNAPSHOT).get("frozen_candidate_digests", {}) if row["source"] == "interactive_scene" else {}
    if resource_id in frozen:
        record_hash = frozen[resource_id]
    elif row["source"] in {"interactive_scene", "four_family"}:
        relative_source = Path(row["path"]).resolve().relative_to(PLUGIN.resolve()).as_posix()
        record = json_file(INTERACTIVE_RECORD if row["source"] == "interactive_scene" else FOUR_RECORD)
        entry = next(e for e in record["entries"] if e["id"] == resource_id)
        stable_identity = {
            "id": resource_id,
            "relative_source_path": relative_source,
            "source_sha256": indexed.lower() if indexed else None,
            "shared_source_sha256": record["shared_source_sha256"].lower(),
            "input_contract": entry["input_contract"],
            "contract_version": entry.get("contract_version", 1),
        }
        if row["source"] == "four_family" and entry.get("base_source_sha256"):
            stable_identity["base_source_sha256"] = entry["base_source_sha256"].lower()
        record_hash = digest(stable_identity)
    elif row["source"] in {"study_world", "editorial_primitive", "semantic_action", "hanzi_trace"}:
        relative_source = Path(row["path"]).resolve().relative_to(PLUGIN.resolve()).as_posix()
        record_path = {"study_world": STUDY_WORLD_RECORD, "editorial_primitive": EDITORIAL_PRIMITIVE_RECORD,
                       "semantic_action": SEMANTIC_ACTION_RECORD, "hanzi_trace": HANZI_TRACE_RECORD}[row["source"]]
        record = json_file(record_path)
        entry = record["entry"] if row["source"] == "hanzi_trace" else next(e for e in record["entries"] if e["id"] == resource_id)
        if row["source"] == "hanzi_trace":
            for item in [*record["data"], record["license"]]:
                asset = record_path.parent / item["path"]
                if not asset.is_file() or sha_file(asset) != item["sha256"].lower():
                    raise ValueError("selected HanziTrace data/license differs from indexed SHA-256")
        stable_identity = {"id": resource_id, "relative_source_path": relative_source,
                           "source_sha256": indexed.lower(), "input_contract": entry["input_contract"],
                           "contract_version": entry.get("contract_version", 1)}
        if row["source"] == "hanzi_trace":
            stable_identity["licensed_data"] = [{"path": item["path"], "sha256": item["sha256"]}
                                                for item in [*record["data"], record["license"]]]
        record_hash = digest(stable_identity)
    else:
        record_hash = digest(row)
    return {"id": resource_id, "record_sha256": record_hash,
            "source_sha256": current,
            "exists": row["exists"]}


def _source_snapshot_matches(bound, current):
    if bound == current:
        return True
    if not isinstance(bound, dict) or not isinstance(current, dict):
        return False
    legacy = json_file(INTERACTIVE_TRIAL_SNAPSHOT).get("legacy_flexible_first_binding", {})
    return (current["id"] == legacy.get("id") and current["exists"] is True and
            bound == {key: legacy[key] for key in ("id", "record_sha256", "source_sha256")}|{"exists": True} and
            current["source_sha256"] == legacy.get("source_sha256") and
            legacy.get("relative_source_path") == "assets/interactive-scenes/src/PhoneActorFlexible.tsx" and
            legacy.get("contract_version") == 1)


def _bound_file(root, item, extensions=None):
    if not isinstance(item, dict) or not isinstance(item.get("sha256"), str) or not SHA.fullmatch(item["sha256"]):
        raise ValueError("bound file needs path and SHA-256")
    path = local_file(root, item.get("path"))
    if extensions and path.suffix.lower() not in extensions:
        raise ValueError("bound file has wrong media extension")
    if sha_file(path) != item["sha256"].lower():
        raise ValueError("bound file SHA-256 drift: " + item["path"])
    return path


def _new_file_ref(root, name, extensions=None):
    path = local_file(root, name)
    if extensions and path.suffix.lower() not in extensions:
        raise ValueError("file has wrong extension: " + name)
    return {"path": name, "sha256": sha_file(path)}


def _hanzi_glyph_issues(root, impl, chars, sources=None, manifest_name=None):
    """Validate only selected local glyphs; unknown glyphs need the pinned preparation manifest."""
    from prepare_hanzi_glyphs import validate_glyph_bytes

    root = Path(root).resolve()
    refs = {ref.get("path"): ref for ref in impl.get("inputs", []) if isinstance(ref, dict)}
    record = json_file(HANZI_TRACE_RECORD)
    builtins = {item["char"]: item for item in record["data"]}
    errors = []
    license_hash = record["license"]["sha256"].lower()
    license_copies = [name for name in refs if isinstance(name, str) and Path(name).name == "ARPHICPL.TXT"]
    if len(license_copies) != 1 or refs[license_copies[0]].get("sha256", "").lower() != license_hash:
        errors.append("HanziTrace needs one hashed unaltered Arphic license copy")
    else:
        try:
            _bound_file(root, refs[license_copies[0]])
        except ValueError as exc:
            errors.append(str(exc))
    manifest = None
    if manifest_name is not None:
        if not isinstance(manifest_name, str) or manifest_name not in refs or Path(manifest_name).suffix.lower() != ".json":
            errors.append("HanziTrace glyph manifest must be a hashed project JSON input")
        else:
            try:
                manifest = json_file(_bound_file(root, refs[manifest_name]))
                license_meta = manifest.get("license") if isinstance(manifest, dict) else None
                if (not isinstance(manifest, dict) or manifest.get("schema_version") != 1 or
                        manifest.get("package") != "hanzi-writer-data" or manifest.get("version") != "2.0.1" or
                        manifest.get("channel") != "https://cdn.jsdelivr.net/npm/hanzi-writer-data@2.0.1/" or
                        not isinstance(manifest.get("glyphs"), dict) or
                        not isinstance(license_meta, dict) or
                        str(license_meta.get("sha256", "")).lower() != license_hash or
                        license_meta.get("path") != license_copies[0]):
                    errors.append("HanziTrace manifest package/version/channel/license drift")
                    manifest = None
            except (ValueError, OSError, json.JSONDecodeError) as exc:
                errors.append(str(exc))
    if not isinstance(chars, list) or not 1 <= len(chars) <= 4 or any(not isinstance(c, str) or len(c) != 1 for c in chars):
        return errors + ["HanziTrace needs 1-4 explicit characters"]
    if sources is None:
        sources = {}
        for char in chars:
            entry = builtins.get(char)
            copies = [name for name in refs if isinstance(name, str) and Path(name).name == f"{char}.json"]
            if entry and len(copies) == 1:
                sources[char] = {"path": copies[0], "sha256": entry["sha256"]}
    if not isinstance(sources, dict):
        return errors + ["HanziTrace glyphSources must be a map"]
    for char in dict.fromkeys(chars):
        builtin = builtins.get(char)
        entry = builtin or (manifest or {}).get("glyphs", {}).get(char)
        binding = sources.get(char)
        expected_url = f"https://cdn.jsdelivr.net/npm/hanzi-writer-data@2.0.1/{quote(char)}.json"
        if not isinstance(entry, dict) or (not builtin and entry.get("url") != expected_url):
            errors.append("HanziTrace glyph lacks pinned 2.0.1 provenance: " + char)
            continue
        if not builtin and (not isinstance(entry.get("strokes"), int) or entry["strokes"] < 1 or
                            not isinstance(entry.get("median_points"), int) or entry["median_points"] < 2):
            errors.append("HanziTrace glyph manifest shape missing: " + char)
            continue
        if not isinstance(binding, dict) or not isinstance(binding.get("path"), str) or \
                str(binding.get("sha256", "")).lower() != str(entry.get("sha256", "")).lower() or \
                (not builtin and binding.get("path") != entry.get("path")):
            errors.append("HanziTrace character source not bound: " + char)
            continue
        ref = refs.get(binding["path"])
        if not ref or str(ref.get("sha256", "")).lower() != str(entry["sha256"]).lower():
            errors.append("HanziTrace glyph missing from hashed inputs: " + char)
            continue
        try:
            path = _bound_file(root, ref)
            details = validate_glyph_bytes(path.read_bytes(), char)
            if entry.get("strokes") and details["strokes"] != entry["strokes"]:
                errors.append("HanziTrace glyph stroke count differs from pinned manifest: " + char)
            if not builtin and details["median_points"] != entry["median_points"]:
                errors.append("HanziTrace glyph median point count differs from pinned manifest: " + char)
        except (ValueError, OSError) as exc:
            errors.append(str(exc))
    return errors


def _auxiliary_source_issues(root, impl):
    """Bind optional secondary sources without treating reference as execution."""
    items = impl.get("auxiliary_sources")
    if items is None:
        return []
    if not isinstance(items, list) or len(items) > 6:
        return ["auxiliary_sources must be a bounded list"]
    declared = {ref.get("path") for ref in impl.get("inputs", []) if isinstance(ref, dict)}
    errors, seen = [], set()
    for item in items:
        if not isinstance(item, dict):
            errors.append("auxiliary source must be an object")
            continue
        rid = item.get("resource_id")
        usage = item.get("usage")
        if not isinstance(rid, str) or not rid or rid in seen:
            errors.append("auxiliary resource_id missing or duplicated")
            continue
        seen.add(rid)
        if usage not in {"reference_only", "adapted_private_code", "local_visual_asset"}:
            errors.append("auxiliary source usage must distinguish reference from implemented input: " + rid)
            continue
        expected = item.get("source_sha256")
        if not isinstance(expected, str) or not SHA.fullmatch(expected):
            errors.append("auxiliary source needs exact source SHA-256: " + rid)
            continue
        try:
            if rid.startswith("project_source:"):
                value = item.get("source_path")
                rel = Path(value) if isinstance(value, str) else None
                if rel is None or rel.is_absolute() or not rel.parts or ".." in rel.parts:
                    raise ValueError("project_source needs a workspace-relative file path")
                project_root = Path(root).resolve()
                source = (project_root / rel).resolve()
                if not source.is_relative_to(project_root) or not source.is_file():
                    raise ValueError("project_source file missing or escapes project")
                source_role = "adaptable_code"
            else:
                row = selected([rid])[0]
                source = Path(row["path"]) if row.get("path") else None
                if not source or not source.is_file():
                    raise ValueError("indexed auxiliary source is missing or not a file")
                source_role = row.get("role")
                if rid.startswith("owned_visual:"):
                    provenance = row.get("source_provenance")
                    _bound_file(WORKSPACE.resolve(), provenance, {".json"})
                if rid.startswith("agent_motion:") and usage != "reference_only":
                    raise ValueError("restricted Agent Motion analysis is reference only without new permission")
            if sha_file(source) != expected.lower():
                raise ValueError("auxiliary source SHA-256 drift")
        except (ValueError, OSError, KeyError) as exc:
            errors.append(rid + ": " + str(exc))
            continue
        if not isinstance(item.get("mechanism"), str) or not item["mechanism"].strip():
            errors.append("auxiliary mechanism required: " + rid)
        if not isinstance(item.get("rights_basis"), str) or not item["rights_basis"].strip():
            errors.append("auxiliary rights_basis required: " + rid)
        if usage == "reference_only":
            if item.get("project_input"):
                errors.append("reference_only auxiliary cannot claim an implemented project input: " + rid)
            continue
        if item.get("cost_boundary") != "existing_local_no_new_fee":
            errors.append("implemented auxiliary must have no new fee in this scope: " + rid)
        if item.get("rights_status") not in {"private_project_reuse", "cleared_for_this_local_scope"}:
            errors.append("implemented auxiliary lacks current local reuse status: " + rid)
        if not isinstance(item.get("visible_action"), str) or not item["visible_action"].strip():
            errors.append("implemented auxiliary needs a concrete visible_action: " + rid)
        project_input = item.get("project_input")
        if not isinstance(project_input, str) or project_input not in declared:
            errors.append("implemented auxiliary needs a hashed project_input: " + rid)
        elif usage == "local_visual_asset":
            try:
                if sha_file(local_file(Path(root).resolve(), project_input)) != expected.lower():
                    errors.append("local_visual_asset project copy differs from selected source: " + rid)
            except ValueError as exc:
                errors.append(str(exc))
        elif source_role not in {"adaptable_code", "adaptable_code_helper", "reference"}:
            errors.append("adapted_private_code needs source code or a documented mechanism reference: " + rid)
        if rid == "hanzi_trace:HanziTrace" and usage == "adapted_private_code":
            record = json_file(HANZI_TRACE_RECORD)
            chars = item.get("glyph_text") or [entry["char"] for entry in record["data"]]
            if isinstance(chars, str):
                chars = list(chars)
            errors.extend(_hanzi_glyph_issues(root, impl, chars, item.get("glyph_sources"), item.get("glyph_manifest")))
    return errors


def _source_read_task_issues(root, segment, impl):
    """Validate a caller-measured source-pixel reading unit, not OCR truth."""
    issues = []
    task = impl.get("read_task")
    if not isinstance(task, dict) or task.get("target_read_unit") not in {"keyword", "sentence", "header_value"}:
        return ["SourcePixelViewport final reading needs read_task target_read_unit keyword/sentence/header_value"]
    requirements = segment.get("expression_requirements")
    req = next((item for item in (requirements if isinstance(requirements, list) else []) if isinstance(item, dict) and
                item.get("id") == task.get("requirement_id")), None)
    attention = req.get("attention") if isinstance(req, dict) else None
    if not isinstance(attention, dict) or type(attention.get("min_read_seconds")) not in (int, float) or attention["min_read_seconds"] <= 0:
        issues.append("SourcePixelViewport read_task must cite a requirement with an actual reading budget")
    refs = {ref.get("path"): ref for ref in impl.get("inputs", []) if isinstance(ref, dict)}
    name = task.get("source_image_path")
    ref = refs.get(name) if isinstance(name, str) else None
    if (not isinstance(ref, dict) or str(ref.get("sha256", "")).lower() != str(task.get("source_sha256", "")).lower() or
            Path(name).suffix.lower() != ".png"):
        issues.append("SourcePixelViewport read_task needs one hashed original PNG input path/SHA")
        return issues
    try:
        path = _bound_file(Path(root).resolve(), ref, {".png"})
        with path.open("rb") as stream:
            header = stream.read(24)
        if header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
            raise ValueError("source PNG dimensions unavailable")
        width, height = struct.unpack(">II", header[16:24])
        if task.get("source_width") != width or task.get("source_height") != height:
            issues.append("SourcePixelViewport read_task source dimensions differ from actual PNG")
    except (ValueError, OSError, TypeError) as exc:
        issues.append("SourcePixelViewport read_task source: " + str(exc))
        return issues
    def rect(value):
        if not isinstance(value, dict):
            return None
        x, y, w, h = (value.get(key) for key in ("x", "y", "width", "height"))
        if any(type(n) not in (int, float) or not math.isfinite(n) for n in (x, y, w, h)):
            return None
        return (float(x), float(y), float(w), float(h)) if x >= 0 and y >= 0 and w > 0 and h > 0 and x + w <= width and y + h <= height else None
    window, target = rect(task.get("source_window")), rect(task.get("target_rect"))
    if window is None or target is None:
        issues.append("SourcePixelViewport read_task needs source-window and complete target rectangles inside original pixels")
        return issues
    wx, wy, ww, wh = window
    tx, ty, tw, th = target
    if tx < wx or ty < wy or tx + tw > wx + ww or ty + th > wy + wh:
        issues.append("SourcePixelViewport read_task target unit is clipped by source_window")
    neighbors = task.get("neighbor_rects")
    if not isinstance(neighbors, list):
        issues.append("SourcePixelViewport read_task neighbor_rects must be a measured list")
    else:
        for neighbor in neighbors:
            other = rect(neighbor)
            if other is None:
                issues.append("SourcePixelViewport read_task neighbor rectangle invalid")
                continue
            nx, ny, nw, nh = other
            if max(wx, nx) < min(wx + ww, nx + nw) and max(wy, ny) < min(wy + wh, ny + nh):
                issues.append("SourcePixelViewport read_task source_window leaks a declared neighboring row")
    return issues


def _probe_media(path):
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise ValueError("ffprobe missing; actual media cannot be confirmed")
    run = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height,r_frame_rate", "-of", "json", str(path)], capture_output=True, text=True, timeout=20)
    if run.returncode:
        raise ValueError("ffprobe rejected media: " + run.stderr[:300])
    data = json.loads(run.stdout)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if not video or float(data.get("format", {}).get("duration") or 0) <= 0:
        raise ValueError("actual video stream and positive duration required")
    audio_streams = sum(s.get("codec_type") == "audio" for s in data.get("streams", []))
    return {"duration_seconds": float(data["format"]["duration"]), "width": video.get("width"), "height": video.get("height"), "frame_rate": video.get("r_frame_rate"), "audio_streams": audio_streams}


def _preview_interval(segment, duration):
    start, stop = segment.get("start_seconds"), segment.get("end_seconds")
    if start is None and stop is None:
        return None
    if (isinstance(start, bool) or isinstance(stop, bool) or
            not isinstance(start, (int, float)) or not isinstance(stop, (int, float)) or
            not math.isfinite(start) or not math.isfinite(stop) or
            start < 0 or stop <= start or stop > duration + 0.05):
        raise ValueError("segment start_seconds/end_seconds must be an actual interval inside preview media")
    return float(start), float(stop)


def _future_project_path(root, name):
    base = Path(root).resolve()
    if not isinstance(name, str) or not name.strip():
        raise ValueError("render path must be a project-relative nonempty name")
    relative = Path(name)
    target = (base / relative).resolve()
    if relative.is_absolute() or ".." in relative.parts or not target.is_relative_to(base):
        raise ValueError("render path escapes project")
    return target


def _render_scope(plan, sid):
    if sid != "__main__":
        segment = _segment(plan, sid)
        _, impl = _chosen(segment)
        return digest(_segment_preview_core(plan, sid)), digest(impl), impl.get("inputs", [])
    segments = [item for item in plan.get("segments", []) if isinstance(item, dict)]
    if not segments:
        raise ValueError("whole main render needs nonempty plan segments")
    implementations = [_chosen(item)[1] for item in segments]
    identities = {(item.get("entry"), item.get("composition_id")) for item in implementations}
    if len(identities) != 1 or any(not a or not b for a, b in identities):
        raise ValueError("whole main render needs one shared entry and Composition ID")
    refs = {}
    for impl in implementations:
        for ref in impl.get("inputs", []):
            if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
                raise ValueError("whole main render has invalid implementation input")
            old = refs.get(ref["path"])
            if old is not None and old.get("sha256") != ref.get("sha256"):
                raise ValueError("whole main render has conflicting input SHA for " + ref["path"])
            refs[ref["path"]] = ref
    return digest(core_plan(plan)), digest(implementations), [refs[name] for name in sorted(refs)]


def render_receipt_start(root, plan, sid, output, receipt, command, parent_receipt=None):
    """Record exact inputs before a new output exists; never backfill history."""
    root = Path(root).resolve()
    from project_policy import requires_visual_decision
    preflight_ids = []
    if requires_visual_decision(root, plan):
        from motion_plan import validate as validate_plan
        plan_check = validate_plan(plan, root, "pre-director")
        if not plan_check["passed"]:
            raise ValueError("pre-render plan preflight failed: " + "; ".join(plan_check["errors"]))
        segments = [item for item in plan.get("segments", []) if isinstance(item, dict)]
        preflight_ids = [item.get("id") for item in segments] if sid == "__main__" else [sid]
        issues = []
        for segment_id in preflight_ids:
            try:
                report = resolve(root, plan, segment_id)
                issues.extend(f"{segment_id}: {issue}" for issue in report["issues"])
            except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
                issues.append(f"{segment_id}: {exc}")
        if issues:
            raise ValueError("pre-render resource preflight failed: " + "; ".join(issues))
    segment_hash, implementation_hash, declared_inputs = _render_scope(plan, sid)
    target = _future_project_path(root, output)
    receipt_path = _future_project_path(root, receipt)
    if target.exists() or receipt_path.exists():
        raise ValueError("render-start needs a new output path and a new receipt path; old media cannot be rebound")
    if target.suffix.lower() not in MEDIA_EXT or receipt_path.suffix.lower() != ".json":
        raise ValueError("render-start needs a video output and JSON receipt")
    if not isinstance(command, str) or not command.strip():
        raise ValueError("render-start needs the exact intended local command")
    snapshots = []
    for ref in declared_inputs:
        _bound_file(root, ref)
        snapshots.append({"path": ref["path"], "sha256": ref["sha256"].lower()})
    parent = None
    if parent_receipt:
        parent_path = local_file(root, parent_receipt)
        prior = json_file(parent_path)
        if prior.get("status") != "complete" or not isinstance(prior.get("output"), dict):
            raise ValueError("derivative needs a completed parent render receipt")
        if prior.get("source_plan_sha256") != digest(core_plan(plan)) or prior.get("shared_context_sha256") != digest(_shared_preview_context(plan)):
            raise ValueError("derivative parent was rendered from another plan or shared input version")
        for ref in prior.get("inputs", []):
            _bound_file(root, ref)
        _bound_file(root, prior["output"], MEDIA_EXT)
        parent = {"receipt_path": parent_receipt, "receipt_sha256": sha_file(parent_path),
                  "media_path": prior["output"]["path"], "media_sha256": prior["output"]["sha256"]}
    value = {"render_receipt_version": 1, "status": "prepared", "project": str(root),
             "segment_id": sid, "source_plan_sha256": digest(core_plan(plan)),
             "segment_core_sha256": segment_hash,
             "shared_context_sha256": digest(_shared_preview_context(plan)),
             "implementation_sha256": implementation_hash, "inputs": snapshots,
             "resource_preflight": {"checked_segment_ids": preflight_ids,
                                    "boundary": "Selected resources/props/source bytes checked before output; no semantic or visual proof."},
             "scope": "whole_main_composition" if sid == "__main__" else "segment_or_derivative",
             "output_path": output, "command": command.strip(), "parent": parent,
             "started_at_utc": datetime.now(timezone.utc).isoformat(),
             "execution_evidence": "external_command_declared_before_output; actual invocation to be captured at finish"}
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"path": receipt, "sha256": sha_file(receipt_path), "status": "prepared", "output_preexisted": False,
            "boundary": "Pre-render byte snapshot; no render has been observed yet."}


def render_receipt_finish(root, plan, sid, receipt, exit_code, command_log=None, executed_by_tool=False):
    """Bind one newly created output to unchanged pre/post inputs and parent."""
    root = Path(root).resolve()
    receipt_path = local_file(root, receipt)
    value = json_file(receipt_path)
    if value.get("render_receipt_version") != 1 or value.get("status") != "prepared" or value.get("project") != str(root) or value.get("segment_id") != sid:
        raise ValueError("render-finish needs this project's prepared receipt")
    if type(exit_code) is not int or exit_code != 0:
        raise ValueError("render-finish requires the actual successful command exit code")
    segment_hash, implementation_hash, declared_inputs = _render_scope(plan, sid)
    if (value.get("source_plan_sha256") != digest(core_plan(plan)) or
            value.get("segment_core_sha256") != segment_hash or
            value.get("shared_context_sha256") != digest(_shared_preview_context(plan)) or
            value.get("implementation_sha256") != implementation_hash):
        raise ValueError("plan or implementation changed after render-start")
    current = []
    for ref in declared_inputs:
        _bound_file(root, ref)
        current.append({"path": ref["path"], "sha256": ref["sha256"].lower()})
    if current != value.get("inputs"):
        raise ValueError("render inputs changed after render-start")
    parent = value.get("parent")
    if isinstance(parent, dict):
        parent_path = local_file(root, parent.get("receipt_path"))
        if sha_file(parent_path) != parent.get("receipt_sha256"):
            raise ValueError("parent render receipt changed")
        _bound_file(root, {"path": parent.get("media_path"), "sha256": parent.get("media_sha256")}, MEDIA_EXT)
    output = local_file(root, value.get("output_path"))
    if output.suffix.lower() not in MEDIA_EXT:
        raise ValueError("render output is not a video")
    media = {"path": value["output_path"], "sha256": sha_file(output), **_probe_media(output)}
    log = None
    if command_log:
        log_path = local_file(root, command_log)
        log = {"path": command_log, "sha256": sha_file(log_path)}
    value.update(status="complete", output=media, command_exit_code=exit_code, command_log=log,
                 completed_at_utc=datetime.now(timezone.utc).isoformat(),
                 execution_evidence="tool_executed_safe_local_command" if executed_by_tool else
                                    "operator_attested_external_command_with_log" if log else
                                    "operator_attested_external_command_without_log")
    receipt_path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"path": receipt, "sha256": sha_file(receipt_path), "status": "complete", "output": media,
            "parent": parent, "execution_evidence": value["execution_evidence"],
            "boundary": "Inputs and output are byte-bound; an external invocation is operator-attested, not independently replayed or watched."}


def _render_receipt_issues(root, plan, sid, media, reference):
    issues = []
    try:
        receipt_path = _bound_file(root, reference, {".json"})
        value = json_file(receipt_path)
        segment = _segment(plan, sid)
        _, impl = _chosen(segment)
        if value.get("render_receipt_version") != 1 or value.get("status") != "complete" or value.get("project") != str(Path(root).resolve()) or value.get("segment_id") != sid:
            issues.append("render receipt is not a completed record for this project segment")
        if (value.get("source_plan_sha256") != digest(core_plan(plan)) or
                value.get("segment_core_sha256") != digest(_segment_preview_core(plan, sid)) or
                value.get("shared_context_sha256") != digest(_shared_preview_context(plan)) or
                value.get("implementation_sha256") != digest(impl)):
            issues.append("render receipt belongs to different plan or implementation bytes")
        expected_inputs = [{"path": ref["path"], "sha256": ref["sha256"].lower()} for ref in impl.get("inputs", [])]
        if value.get("inputs") != expected_inputs:
            issues.append("render receipt input snapshot differs from current implementation")
        output = value.get("output")
        if not isinstance(media, dict) or not isinstance(output, dict) or output.get("path") != media.get("path") or output.get("sha256") != media.get("sha256"):
            issues.append("render receipt output differs from bound preview media")
        else:
            _bound_file(root, value["output"], MEDIA_EXT)
        parent = value.get("parent")
        if isinstance(parent, dict):
            path = local_file(root, parent.get("receipt_path"))
            if sha_file(path) != parent.get("receipt_sha256"):
                issues.append("render receipt parent record drift")
            prior = json_file(path)
            if (prior.get("status") != "complete" or prior.get("source_plan_sha256") != digest(core_plan(plan)) or
                    prior.get("shared_context_sha256") != digest(_shared_preview_context(plan))):
                issues.append("render receipt parent belongs to different plan/source timing")
            for ref in prior.get("inputs", []):
                _bound_file(root, ref)
            _bound_file(root, {"path": parent.get("media_path"), "sha256": parent.get("media_sha256")}, MEDIA_EXT)
        if value.get("command_exit_code") != 0 or not isinstance(value.get("command"), str) or not value["command"].strip():
            issues.append("render receipt lacks successful declared command")
        log = value.get("command_log")
        if isinstance(log, dict):
            _bound_file(root, log)
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        issues.append("render receipt: " + str(exc))
    return issues


def bind_preview(root, plan, sid, frames, media, render_receipt=None):
    root = Path(root).resolve()
    segment = _segment(plan, sid)
    chosen, impl = _chosen(segment)
    if plan.get("semantic_contract_version") == 2:
        expression_errors = []
        validate_segment(segment, root, expression_errors, sid)
        if expression_errors:
            raise ValueError("expression closure rejected: " + "; ".join(expression_errors))
    identity_version = _preview_identity_version(plan)
    if identity_version == 2:
        scope_errors = _segment_input_scope_issues(plan, sid, impl)
        if scope_errors:
            raise ValueError("segment input closure rejected: " + "; ".join(scope_errors))
    if chosen["resource_id"].startswith(("interactive_scene:", "four_family:", "study_world:", "editorial_primitive:", "semantic_action:", "hanzi_trace:")):
        report = resolve(root, plan, sid)
        if not report["ready_for_handoff"]:
            raise ValueError("interactive actor input rejected: " + "; ".join(report["issues"]))
    static_binding = media is None
    if static_binding:
        requirements = segment.get("expression_requirements")
        if (plan.get("semantic_contract_version") != 2 or identity_version != 2 or
                segment.get("visual_route") not in {"official_evidence", "sourced_chart", "real_media"} or
                not isinstance(requirements, list) or not requirements or
                any(not isinstance(item, dict) or item.get("proof_kind") != "static_reading" for item in requirements)):
            raise ValueError("static preview is limited to v2 exact-source reading obligations")
    if not isinstance(frames, list) or len(frames) < (1 if static_binding else 2):
        raise ValueError("actual keyframes required for static reading; two required for continuous media")
    input_refs = impl["inputs"]
    for ref in input_refs:
        _bound_file(root, ref)
    frame_refs = [_new_file_ref(root, name, IMAGE_EXT) for name in frames]
    media_ref = None
    if not static_binding:
        media_ref = _new_file_ref(root, media, MEDIA_EXT)
        media_ref.update(_probe_media(root / media))
        _preview_interval(segment, media_ref["duration_seconds"])
        if plan.get("timebase_kind") == "authored_screen_timing" and media_ref["audio_streams"]:
            raise ValueError("silent authored-screen preview contains an audio stream")
    from project_policy import requires_visual_decision
    receipt_ref = None
    if not static_binding and requires_visual_decision(root, plan):
        if not render_receipt:
            raise ValueError("new studio dynamic preview needs a pre/post input render receipt")
        receipt_ref = _new_file_ref(root, render_receipt, {".json"})
        issues = _render_receipt_issues(root, plan, sid, media_ref, receipt_ref)
        if issues:
            raise ValueError("render receipt rejected: " + "; ".join(issues))
    design = _new_file_ref(root, "design.md")
    if plan.get("design_sha256") != design["sha256"]:
        raise ValueError("plan design hash drift")
    source_snapshot = _candidate_snapshot(chosen["resource_id"])
    if source_snapshot is not None and not source_snapshot["exists"]:
        raise ValueError("chosen indexed source missing; adapt from a verified source first")
    if static_binding:
        return {"version": 2, "static_reading": True, "segment_id": sid,
                "segment_core_sha256": digest(_segment_preview_core(plan, sid)),
                "shared_context_sha256": digest(_shared_preview_context(plan)),
                "design_sha256": design["sha256"], "chosen_resource_id": chosen["resource_id"],
                "implementation_sha256": digest(impl), "source_snapshot": source_snapshot,
                "inputs": input_refs, "keyframes": frame_refs}
    if identity_version == 2:
        return {"version": 2, "segment_id": sid,
                "segment_core_sha256": digest(_segment_preview_core(plan, sid)),
                "shared_context_sha256": digest(_shared_preview_context(plan)),
                "design_sha256": design["sha256"], "chosen_resource_id": chosen["resource_id"],
                "implementation_sha256": digest(impl), "source_snapshot": source_snapshot,
                "inputs": input_refs, "keyframes": frame_refs, "preview_media": media_ref,
                **({"render_receipt": receipt_ref} if receipt_ref else {})}
    return {"version": 1, "segment_id": sid, "plan_core_sha256": digest(core_plan(plan)),
            "design_sha256": design["sha256"], "chosen_resource_id": chosen["resource_id"],
            "implementation_sha256": digest(impl), "source_snapshot": source_snapshot,
            "inputs": input_refs,
            "keyframes": frame_refs, "preview_media": media_ref}


def verify_preview(root, plan, sid):
    root = Path(root).resolve()
    errors = []
    try:
        segment = _segment(plan, sid)
        chosen, impl = _chosen(segment)
        if plan.get("semantic_contract_version") == 2:
            validate_segment(segment, root, errors, sid)
        if chosen["resource_id"].startswith(("interactive_scene:", "four_family:", "study_world:", "editorial_primitive:", "semantic_action:", "hanzi_trace:")):
            report = resolve(root, plan, sid)
            errors.extend(report["issues"])
        binding = segment.get("preview_binding")
        identity_version = _preview_identity_version(plan)
        if not isinstance(binding, dict) or binding.get("version") != identity_version:
            raise ValueError("preview binding version differs from current plan")
        expected = {"segment_id": sid,
                    "design_sha256": sha_file(local_file(root, "design.md")),
                    "chosen_resource_id": chosen["resource_id"], "implementation_sha256": digest(impl)}
        if identity_version == 2:
            errors.extend(_segment_input_scope_issues(plan, sid, impl))
            expected["segment_core_sha256"] = digest(_segment_preview_core(plan, sid))
            expected["shared_context_sha256"] = digest(_shared_preview_context(plan))
        else:
            expected["plan_core_sha256"] = digest(core_plan(plan))
        for key, value in expected.items():
            if binding.get(key) != value:
                errors.append(key + " drift")
        if not _source_snapshot_matches(binding.get("source_snapshot"), _candidate_snapshot(chosen["resource_id"])):
            errors.append("chosen source record or bytes drift")
        if plan.get("design_sha256") != expected["design_sha256"]:
            errors.append("plan design_sha256 drift")
        if binding.get("inputs") != impl["inputs"]:
            errors.append("implementation inputs drift")
        for ref in impl["inputs"]:
            _bound_file(root, ref)
        frames = binding.get("keyframes")
        static_binding = binding.get("static_reading") is True
        static_requirements = segment.get("expression_requirements")
        if static_binding and (plan.get("semantic_contract_version") != 2 or identity_version != 2 or
                segment.get("visual_route") not in {"official_evidence", "sourced_chart", "real_media"} or
                not isinstance(static_requirements, list) or not static_requirements or
                any(not isinstance(item, dict) or item.get("proof_kind") != "static_reading"
                    for item in static_requirements)):
            errors.append("static preview cannot satisfy continuous obligations")
        if not isinstance(frames, list) or len(frames) < (1 if static_binding else 2):
            errors.append("actual preview keyframes missing")
        else:
            for frame in frames:
                path = _bound_file(root, frame, IMAGE_EXT)
                from director_review_gate import _image
                _image(path, "preview keyframe", errors)
        from project_policy import requires_visual_decision
        consumer_paths = []
        if requires_visual_decision(root, plan):
            decision = segment.get("visual_decision")
            roles = decision.get("media_roles", []) if isinstance(decision, dict) else []
            roles = roles if isinstance(roles, list) else []
            if any(isinstance(role, dict) and role.get("input_state") == "needed" for role in roles):
                errors.append("real preview cannot claim completion while a declared media role is still needed")
            consumer_paths = _consumer_probe_issues(root, segment, impl, binding, frames, errors)
        if static_binding:
            if binding.get("preview_media") is not None:
                errors.append("static reading binding must not claim video media")
            return {"passed": not errors, "segment_id": sid, "errors": errors,
                    "consumer_call_paths": consumer_paths,
                    "boundary": "static source frame and cue-window identity only; no continuous motion or aesthetic proof"}
        media = binding.get("preview_media")
        path = _bound_file(root, media, MEDIA_EXT)
        probe = _probe_media(path)
        # Early v1 bindings lacked audio_streams; the actual stream check below
        # still rejects a silent trial with an AAC track.
        if any(media.get(k) != probe.get(k) for k in probe if k != "audio_streams" or k in media):
            errors.append("preview media probe drift")
        if plan.get("timebase_kind") == "authored_screen_timing" and probe["audio_streams"]:
            errors.append("silent authored-screen preview contains an audio stream")
        if plan.get("timebase_kind") == "real_voice_srt" and not probe["audio_streams"]:
            errors.append("real-voice preview needs an actual audio stream; waveform alignment remains separate")
        _preview_interval(segment, probe["duration_seconds"])
        from project_policy import requires_visual_decision
        if requires_visual_decision(root, plan):
            reference = binding.get("render_receipt")
            if not isinstance(reference, dict):
                errors.append("new studio dynamic preview needs its bound render receipt")
            else:
                errors.extend(_render_receipt_issues(root, plan, sid, media, reference))
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        errors.append(str(exc))
    return {"passed": not errors, "segment_id": sid, "errors": errors,
            "consumer_call_paths": consumer_paths if 'consumer_paths' in locals() else [],
            "boundary": "byte and structure check only; not semantic, aesthetic, voice, or user approval"}


def _consumer_probe_issues(root, segment, impl, binding, frames, errors):
    """Recompute main-Composition JSX call paths against an actual bound still.

    No author-supplied ``used: true`` flag or mere import statement counts as
    execution. Static reachability plus the bound frame is bounded technical
    evidence, not proof the target is visible at that frame or looks good.
    """
    probe = impl.get("consumer_probe")
    if not isinstance(probe, dict):
        errors.append("new v2 preview needs an internal main-Composition consumer_probe")
        return []
    entry, cid = impl.get("entry"), impl.get("composition_id")
    frame_number, frame_path = probe.get("frame_number"), probe.get("frame_path")
    symbols = probe.get("component_symbols")
    if not isinstance(entry, str) or not isinstance(cid, str) or not isinstance(frame_path, str) or type(frame_number) is not int:
        errors.append("consumer_probe needs implementation entry/composition and bound frame_number/frame_path")
        return []
    if frame_path not in [item.get("path") for item in frames if isinstance(item, dict)]:
        errors.append("consumer_probe frame_path must be a hashed actual preview keyframe")
        return []
    if not isinstance(symbols, dict):
        errors.append("consumer_probe component_symbols must name exact JSX exports, not just imported files")
        return []
    clock = segment.get("srt_timecode") or segment.get("authored_timecode")
    match = re.fullmatch(r"(\d\d):(\d\d):(\d\d),(\d\d\d) --> (\d\d):(\d\d):(\d\d),(\d\d\d)", str(clock))
    if not match:
        errors.append("consumer_probe needs a bound segment timecode")
        return []
    nums = [int(value) for value in match.groups()]
    start = nums[0] * 3600 + nums[1] * 60 + nums[2] + nums[3] / 1000
    end = nums[4] * 3600 + nums[5] * 60 + nums[6] + nums[7] / 1000
    declared = {item.get("path") for item in impl.get("inputs", []) if isinstance(item, dict)}
    if entry not in declared:
        errors.append("consumer_probe entry must be a hashed implementation input")
        return []
    candidate_paths = {}
    required_components = set()
    for mapping in impl.get("expression_map", []) if isinstance(impl.get("expression_map"), list) else []:
        if not isinstance(mapping, dict):
            continue
        for name in mapping.get("project_input_paths", []) if isinstance(mapping.get("project_input_paths"), list) else []:
            if isinstance(name, str) and Path(name).suffix.lower() in {".tsx", ".jsx", ".ts", ".js"} and name != entry:
                candidate_paths[name] = mapping.get("resource_id")
                registered = mapping.get("resource_id")
                if (registered in REGISTERED_COMPONENT_SYMBOLS and
                        Path(name).stem == ("StudyWorldVisualV2" if registered == "study_world:StudyWorldVisualV2" else registered.rsplit(":", 1)[-1])):
                    required_components.add(name)
    for source in impl.get("auxiliary_sources", []) if isinstance(impl.get("auxiliary_sources"), list) else []:
        if isinstance(source, dict) and source.get("usage") == "adapted_private_code":
            name = source.get("project_input")
            if isinstance(name, str) and Path(name).suffix.lower() in {".tsx", ".jsx", ".ts", ".js"}:
                candidate_paths[name] = source.get("resource_id")
                if source.get("resource_id") in REGISTERED_COMPONENT_SYMBOLS:
                    required_components.add(name)
    targets = set(symbols)
    if not targets or not targets.issubset(candidate_paths):
        errors.append("consumer_probe component_symbols must target implemented project code from expression_map/auxiliary_sources")
        return []
    if required_components - targets:
        errors.append("consumer_probe must trace each declared registered component, not only its wrapper: " +
                      ", ".join(sorted(required_components - targets)))
        return []
    node = shutil.which("node")
    runtime = Path(os.environ.get("MUZHI_TYPESCRIPT_RUNTIME", str(PLUGIN))).expanduser().resolve()
    tracer = PLUGIN / "scripts/consumer_call_trace.cjs"
    if not node or not (runtime / "node_modules/typescript").is_dir() or not tracer.is_file():
        errors.append("consumer_probe needs Node and TypeScript in this plugin or MUZHI_TYPESCRIPT_RUNTIME; no dependency is downloaded automatically")
        return []
    call_paths = []
    for name in sorted(targets):
        if name not in declared:
            errors.append("consumer_probe target is not a hashed implementation input: " + name)
            continue
        symbol = symbols.get(name)
        if not isinstance(symbol, str) or not re.fullmatch(r"[A-Za-z_$][\w$]*", symbol):
            errors.append("consumer_probe needs an exact component symbol for " + name)
            continue
        registered = candidate_paths[name]
        expected_symbol = REGISTERED_COMPONENT_SYMBOLS.get(registered)
        if expected_symbol and symbol != expected_symbol and Path(name).stem == ("StudyWorldVisualV2" if registered == "study_world:StudyWorldVisualV2" else registered.rsplit(":", 1)[-1]):
            errors.append("consumer_probe symbol differs from registered component export: " + name)
            continue
        try:
            target = local_file(root, name)
            code = subprocess.run([node, str(tracer), "--project", str(root), "--runtime", str(runtime),
                                   "--entry", entry, "--composition", cid, "--target", name, "--symbol", symbol],
                                  cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace",
                                  timeout=20, check=False)
            result = json.loads(code.stdout)
            if code.returncode or result.get("passed") is not True:
                errors.append("consumer_probe main Composition does not call " + name + ": " + str(result.get("reason")))
            else:
                fps = result.get("fps")
                if type(fps) not in (int, float) or not math.isfinite(fps) or fps <= 0:
                    errors.append("consumer_probe main Composition needs a literal positive fps for frame binding")
                elif frame_number < int(start * fps) - 1 or frame_number > math.ceil(end * fps) + 1:
                    errors.append("consumer_probe frame_number must fall in this main Composition segment")
                media = binding.get("preview_media") if isinstance(binding, dict) else None
                rate = media.get("frame_rate") if isinstance(media, dict) else None
                if rate and type(fps) in (int, float):
                    try:
                        top, bottom = str(rate).split("/", 1)
                        if abs(float(top) / float(bottom) - fps) > .01:
                            errors.append("consumer_probe Composition fps differs from actual preview media")
                    except (ValueError, ZeroDivisionError):
                        errors.append("consumer_probe actual preview frame rate invalid")
                call_paths.append({"target": name, "sha256": sha_file(target), "component_symbol": symbol,
                                   "call_path": result["call_path"], "frame_number": frame_number,
                                   "frame_path": frame_path, "fps": fps,
                                   "evidence_level": result["evidence_level"],
                                   "conditional_visibility_unverified": True})
        except (ValueError, OSError, subprocess.TimeoutExpired, json.JSONDecodeError, KeyError) as exc:
            errors.append("consumer_probe failed for " + name + ": " + str(exc))
    return call_paths


def resolve(root, plan, sid):
    segment = _segment(plan, sid)
    chosen, impl = _chosen(segment)
    rid = chosen["resource_id"]
    row = selected([rid])[0] if ":" in rid and rid.split(":", 1)[0] in SOURCES else None
    checks = []
    if plan.get("semantic_contract_version") == 2 and _preview_identity_version(plan) == 2:
        from project_policy import requires_visual_decision
        if requires_visual_decision(root, plan):
            checks.extend(_segment_input_scope_issues(plan, sid, impl))
            try:
                design = _new_file_ref(Path(root).resolve(), "design.md")
                if plan.get("design_sha256") != design["sha256"]:
                    checks.append("plan design_sha256 drift")
            except (ValueError, OSError) as exc:
                checks.append("design source: " + str(exc))
            try:
                snapshot = _candidate_snapshot(rid)
                if snapshot is not None and not snapshot["exists"]:
                    checks.append("chosen indexed source missing; adapt from a verified source first")
            except (ValueError, OSError, KeyError, TypeError) as exc:
                checks.append("chosen source identity: " + str(exc))
            probe = impl.get("consumer_probe")
            if not isinstance(probe, dict):
                checks.append("new v2 render needs a declared main-Composition consumer_probe")
            else:
                # Existing call-path check can run against the planned future
                # keyframe path; actual frame bytes/media remain a post-render gate.
                _consumer_probe_issues(root, segment, impl, None,
                                       [{"path": probe.get("frame_path")}], checks)
    if plan.get("semantic_contract_version") == 2:
        validate_segment(segment, root, checks, sid)
    if row and not row["exists"]:
        checks.append("indexed source file missing or unresolved")
    if row and row.get("indexed_sha256") and row.get("path") and row["exists"]:
        if sha_file(Path(row["path"])) != row["indexed_sha256"].lower():
            checks.append("selected source differs from indexed SHA-256")
    if row and row["role"] in {"reference", "method", "static", "adaptable_code"} and impl["mode"] == "direct_render":
        checks.append("reference/method/static/adaptable code item has no direct renderer")
    if row and row["source"] == "shotcraft" and impl["mode"] == "local_remotion":
        usage = impl.get("reference_usage")
        card_hash = sha_file(Path(row["path"])) if row["exists"] else None
        if (not isinstance(usage, dict) or usage.get("source_sha256") != card_hash or
                not isinstance(usage.get("mechanism"), str) or not usage["mechanism"].strip() or
                not isinstance(usage.get("visible_action"), str) or not usage["visible_action"].strip()):
            checks.append("selected Shotcraft text requires current card SHA-256, mechanism and visible_action in implementation.reference_usage")
        if not any(isinstance(ref, dict) and Path(str(ref.get("path", ""))).suffix.lower() in {".ts", ".tsx", ".js", ".jsx"}
                   for ref in impl["inputs"]):
            checks.append("selected Shotcraft text requires a hashed project-local code implementation")
    if rid.startswith("owned_visual:"):
        try:
            _bound_file(WORKSPACE.resolve(), row.get("source_provenance"), {".json"})
            matches = [ref for ref in impl["inputs"] if isinstance(ref, dict) and
                       Path(str(ref.get("path", ""))).suffix.lower() in IMAGE_EXT and
                       str(ref.get("sha256", "")).lower() == row["indexed_sha256"].lower()]
            if len(matches) != 1:
                checks.append("selected owned still needs one exact hashed project PNG copy and a scene wrapper")
            if not any(isinstance(ref, dict) and Path(str(ref.get("path", ""))).suffix.lower() in {".tsx", ".jsx", ".ts", ".js"}
                       for ref in impl["inputs"]):
                checks.append("selected owned still needs project code; image alone is not a motion scene")
        except (ValueError, OSError, KeyError, TypeError) as exc:
            checks.append("owned still provenance: " + str(exc))
    for ref in impl["inputs"]:
        try:
            _bound_file(Path(root).resolve(), ref)
        except ValueError as exc:
            checks.append(str(exc))
    checks.extend(_auxiliary_source_issues(root, impl))
    from project_policy import requires_visual_decision
    auxiliary_sources = impl.get("auxiliary_sources")
    if requires_visual_decision(root, plan) and (rid == "editorial_primitive:SourcePixelViewport" or
            any(isinstance(item, dict) and item.get("resource_id") == "editorial_primitive:SourcePixelViewport" and
                item.get("usage") == "adapted_private_code" for item in
                (auxiliary_sources if isinstance(auxiliary_sources, list) else []))):
        checks.extend(_source_read_task_issues(root, segment, impl))
    if rid.startswith(("editorial_primitive:", "semantic_action:")):
        declared = [ref.get("path") for ref in impl["inputs"] if isinstance(ref, dict)]
        original = Path(row["path"])
        copies = [name for name in declared if isinstance(name, str) and Path(name).name == original.name]
        wrappers = [name for name in declared if isinstance(name, str) and name not in copies and
                    Path(name).suffix.lower() in {".tsx", ".jsx", ".ts", ".js"}]
        if len(copies) != 1 or not wrappers:
            checks.append("source-only component needs one exact project source copy and a hashed project scene wrapper")
        else:
            try:
                if sha_file(local_file(Path(root).resolve(), copies[0])) != sha_file(original):
                    checks.append("project editorial primitive source differs from selected reusable source")
            except ValueError as exc:
                checks.append(str(exc))
        if rid == "semantic_action:PaperActionTheater":
            declared_refs = {ref.get("path"): ref for ref in impl["inputs"] if isinstance(ref, dict)}
            props_name = impl.get("props")
            if not isinstance(props_name, str) or props_name not in declared_refs or Path(props_name).suffix.lower() != ".json":
                checks.append("PaperActionTheater needs hashed JSON props with explicit visual assets")
            else:
                try:
                    payload = json_file(local_file(Path(root).resolve(), props_name))
                    scene = payload.get("scene", payload) if isinstance(payload, dict) else {}
                    objects = scene.get("objects", []) if isinstance(scene, dict) else []
                    objects = objects if isinstance(objects, list) else []
                    objects_by_id = {obj.get("id"): obj for obj in objects if isinstance(obj, dict) and isinstance(obj.get("id"), str)}
                    for obj in objects:
                        if not isinstance(obj, dict):
                            checks.append("PaperActionTheater object must be an object")
                            continue
                        asset = obj.get("visualAsset")
                        if obj.get("kind") in {"hand", "person", "horse"} and not isinstance(asset, dict):
                            checks.append("PaperActionTheater figure needs a bound project visualAsset: " + str(obj.get("id")))
                        if isinstance(asset, dict):
                            name = asset.get("path")
                            ref = declared_refs.get(name)
                            if not isinstance(name, str) or not name.startswith("public/") or not ref or \
                                    ref.get("sha256", "").lower() != str(asset.get("sha256", "")).lower():
                                checks.append("PaperActionTheater visualAsset path/SHA must match hashed implementation input: " + str(obj.get("id")))
                            else:
                                try:
                                    _bound_file(Path(root).resolve(), ref)
                                except ValueError as exc:
                                    checks.append(str(exc))
                    beats = scene.get("beats", []) if isinstance(scene, dict) else []
                    for beat in (beats if isinstance(beats, list) else []):
                        if not isinstance(beat, dict) or beat.get("action") not in {"open", "close", "fold"}:
                            continue
                        object_id = beat.get("objectId")
                        target = objects_by_id.get(object_id) if isinstance(object_id, str) else None
                        if target and (isinstance(target.get("visualAsset"), dict) or target.get("visual")):
                            checks.append("PaperActionTheater custom visual bypasses built-in open/close/fold: " + object_id)
                except (ValueError, OSError, json.JSONDecodeError) as exc:
                    checks.append(str(exc))
    if rid == "hanzi_trace:HanziTrace":
        declared_refs = {ref.get("path"): ref for ref in impl["inputs"] if isinstance(ref, dict)}
        source = Path(row["path"])
        record = json_file(HANZI_TRACE_RECORD)
        for asset in [{"path": record["entry"]["path"], "sha256": record["entry"]["sha256"]}]:
            original = HANZI_TRACE_RECORD.parent / asset["path"]
            copies = [name for name in declared_refs if isinstance(name, str) and Path(name).name == original.name]
            if len(copies) != 1:
                checks.append("HanziTrace needs one hashed project copy of " + asset["path"])
            else:
                try:
                    if sha_file(local_file(Path(root).resolve(), copies[0])) != asset["sha256"].lower():
                        checks.append("HanziTrace project copy differs from indexed source: " + asset["path"])
                except ValueError as exc:
                    checks.append(str(exc))
        wrappers = [name for name in declared_refs if isinstance(name, str) and
                    Path(name).suffix.lower() in {".tsx", ".jsx", ".ts", ".js"} and Path(name).name != source.name]
        props_name = impl.get("props")
        if not wrappers or not isinstance(props_name, str) or props_name not in declared_refs or Path(props_name).suffix.lower() != ".json":
            checks.append("HanziTrace needs hashed wrapper and JSON props")
        else:
            try:
                payload = json_file(local_file(Path(root).resolve(), props_name))
                scene = payload.get("scene", payload) if isinstance(payload, dict) else {}
                text = scene.get("text", [])
                sources = scene.get("glyphSources", {})
                if not isinstance(text, list) or not text or len(text) > 4 or not isinstance(sources, dict):
                    checks.append("HanziTrace props need explicit text and glyphSources")
                else:
                    manifest_name = impl.get("glyph_manifest") or scene.get("glyphManifestPath")
                    checks.extend(_hanzi_glyph_issues(root, impl, text, sources, manifest_name))
            except (ValueError, OSError, json.JSONDecodeError) as exc:
                checks.append(str(exc))
    if rid in {"semantic_action:TimeStructure", "semantic_action:DataMorph"}:
        declared_refs = {ref.get("path"): ref for ref in impl["inputs"] if isinstance(ref, dict)}
        props_name = impl.get("props")
        if not isinstance(props_name, str) or props_name not in declared_refs or Path(props_name).suffix.lower() != ".json":
            checks.append("numeric semantic action needs hashed JSON props and source status")
        else:
            try:
                payload = json_file(local_file(Path(root).resolve(), props_name))
                scene = payload.get("scene", payload) if isinstance(payload, dict) else {}
                measured = (scene.get("domain", {}).get("kind") == "measured" if rid.endswith("TimeStructure")
                            else scene.get("dataStatus") == "measured")
                source = scene.get("domain", {}) if rid.endswith("TimeStructure") else scene
                if measured:
                    name = source.get("sourcePath")
                    ref = declared_refs.get(name)
                    if not isinstance(name, str) or not ref or \
                            ref.get("sha256", "").lower() != str(source.get("sourceSha256", "")).lower():
                        checks.append("measured semantic action source path/SHA must match implementation input")
                    else:
                        try:
                            _bound_file(Path(root).resolve(), ref)
                        except ValueError as exc:
                            checks.append(str(exc))
            except (ValueError, OSError, json.JSONDecodeError) as exc:
                checks.append(str(exc))
    if rid == "semantic_action:UnitDuration":
        declared_refs = {ref.get("path"): ref for ref in impl["inputs"] if isinstance(ref, dict)}
        props_name = impl.get("props")
        if not isinstance(props_name, str) or props_name not in declared_refs or Path(props_name).suffix.lower() != ".json":
            checks.append("UnitDuration needs hashed JSON props with one count and counterfactual minute bases")
        else:
            try:
                payload = json_file(local_file(Path(root).resolve(), props_name))
                scene = payload.get("scene", payload) if isinstance(payload, dict) else {}
                if not isinstance(scene, dict):
                    scene = {}
                count = scene.get("count") if isinstance(scene, dict) else None
                current = scene.get("currentMinutesPerUnit") if isinstance(scene, dict) else None
                comparison = scene.get("comparisonMinutesPerUnit") if isinstance(scene, dict) else None
                events = scene.get("events") if isinstance(scene, dict) else None
                if type(count) is not int or count <= 0 or count > 9007199254740991:
                    checks.append("UnitDuration count must be a positive safe integer")
                if any(type(n) not in (int, float) or not math.isfinite(n) or n <= 0 for n in (current, comparison)):
                    checks.append("UnitDuration minutes-per-unit values must be positive finite numbers")
                elif type(count) is int and count > 0 and not all(math.isfinite(count * n) for n in (current, comparison)):
                    checks.append("UnitDuration count times minutes-per-unit overflows numeric range")
                unit_label = scene.get("unitLabel")
                if scene.get("comparisonMode") != "counterfactual" or scene.get("displayUnit") != "小时" or not isinstance(unit_label, str) or not unit_label.strip() or len(unit_label) > 12:
                    checks.append("UnitDuration must visibly keep 若按 counterfactual, unit label and hour display")
                if not isinstance(events, dict) or any(type(events.get(k)) is not int for k in
                    ("unitReveal", "totalReveal", "compareReveal", "readUntil")) or not (
                        0 <= events["unitReveal"] < events["totalReveal"] < events["compareReveal"] and
                        events["readUntil"] >= events["compareReveal"] + 24):
                    checks.append("UnitDuration event order or settled reading window invalid")
                elif "focusComparison" in events and (type(events["focusComparison"]) is not int or not (
                        events["compareReveal"] < events["focusComparison"] < events["readUntil"])):
                    checks.append("UnitDuration focusComparison must follow compareReveal and precede readUntil")
            except (ValueError, OSError, TypeError, json.JSONDecodeError) as exc:
                checks.append(str(exc))
    if rid == "semantic_scene:SemanticScene":
        from semantic_scene_contract import validate_scene
        checks.extend(validate_scene(segment, Path(root).resolve()))
        source_copies = [ref for ref in impl["inputs"] if isinstance(ref, dict)
                         and Path(str(ref.get("path", ""))).name == "SemanticScene.tsx"]
        if len(source_copies) != 1:
            checks.append("implementation.inputs must hash exactly one project-local SemanticScene.tsx source copy")
        else:
            try:
                if sha_file(local_file(Path(root).resolve(), source_copies[0]["path"])) != sha_file(SEMANTIC_SCENE):
                    checks.append("project SemanticScene.tsx differs from selected reusable source")
            except ValueError as exc:
                checks.append(str(exc))
        props = impl.get("props")
        if not isinstance(props, str) or props not in [ref.get("path") for ref in impl["inputs"] if isinstance(ref, dict)]:
            checks.append("semantic scene render props must be a project-local hashed implementation input")
    if rid.startswith("interactive_scene:"):
        root = Path(root).resolve()
        shared_source = Path(row.get("shared_source_path", str(INTERACTIVE_FRAME)))
        if row.get("shared_indexed_sha256") and sha_file(shared_source) != row["shared_indexed_sha256"].lower():
            checks.append("interactive shared frame source differs from asset record SHA-256")
        declared = {ref.get("path") for ref in impl["inputs"] if isinstance(ref, dict)}
        for original in (Path(row["path"]), shared_source):
            copies = [name for name in declared if isinstance(name, str) and Path(name).name == original.name]
            if len(copies) != 1:
                checks.append("interactive actor needs exactly one hashed project copy of " + original.name)
                continue
            try:
                if sha_file(local_file(root, copies[0])) != sha_file(original):
                    checks.append("project interactive actor source differs from " + original.name)
            except ValueError as exc:
                checks.append(str(exc))
        props_name = impl.get("props")
        if not isinstance(props_name, str) or props_name not in declared:
            checks.append("interactive actor props must be a hashed project-local JSON input")
        else:
            try:
                from interactive_scene_contract import validate_actor
                props_path = local_file(root, props_name)
                if props_path.suffix.lower() != ".json":
                    checks.append("interactive actor props must be JSON")
                else:
                    checks.extend(validate_actor(rid, json_file(props_path), root, declared))
            except (ValueError, OSError, json.JSONDecodeError) as exc:
                checks.append(str(exc))
    if rid.startswith("four_family:"):
        root = Path(root).resolve()
        if row.get("shared_indexed_sha256") and sha_file(FOUR_COMMON) != row["shared_indexed_sha256"].lower():
            checks.append("four-family common source differs from asset record SHA-256")
        if row.get("base_indexed_sha256") and sha_file(FOUR_CAUSE_BASE) != row["base_indexed_sha256"].lower():
            checks.append("evidence actor base CauseActor source differs from asset record SHA-256")
        declared = {ref.get("path") for ref in impl["inputs"] if isinstance(ref, dict)}
        originals = (Path(row["path"]), FOUR_COMMON) + ((FOUR_CAUSE_BASE,) if rid == "four_family:CauseEvidenceActor" else ())
        for original in originals:
            copies = [name for name in declared if isinstance(name, str) and Path(name).name == original.name]
            if len(copies) != 1:
                checks.append("four-family actor needs exactly one hashed project copy of " + original.name)
                continue
            try:
                if sha_file(local_file(root, copies[0])) != sha_file(original):
                    checks.append("project four-family actor source differs from " + original.name)
            except ValueError as exc:
                checks.append(str(exc))
        props_name = impl.get("props")
        if not isinstance(props_name, str) or props_name not in declared:
            checks.append("four-family actor props must be a hashed project-local JSON input")
        else:
            try:
                from four_family_contract import validate_actor
                props_path = local_file(root, props_name)
                if props_path.suffix.lower() != ".json":
                    checks.append("four-family actor props must be JSON")
                else:
                    payload = json_file(props_path)
                    checks.extend(validate_actor(rid, payload))
                    scene = payload.get("scene", payload) if isinstance(payload, dict) else {}
                    external_ids = [obj.get("id") for obj in scene.get("objects", []) if isinstance(obj, dict) and obj.get("externalContent") is True] if isinstance(scene, dict) else []
                    external = impl.get("external_content")
                    for obj_id in external_ids:
                        name = external.get(obj_id) if isinstance(external, dict) else None
                        if (not isinstance(name, str) or name not in declared or
                                Path(name).suffix.lower() not in {".tsx", ".jsx", ".ts", ".js"} or
                                Path(name).name in {Path(row["path"]).name, "common.tsx"}):
                            checks.append("externalContent object needs a hashed project code path in implementation.external_content: " + str(obj_id))
            except (ValueError, OSError, json.JSONDecodeError) as exc:
                checks.append(str(exc))
    if rid in {"study_world:StudyWorld", "study_world:StudyWorldVisualV2"}:
        root = Path(root).resolve()
        declared = {ref.get("path") for ref in impl["inputs"] if isinstance(ref, dict)}
        if impl.get("input_scope") != "segment":
            checks.append("StudyWorld needs a truthful segment input closure")
        source_name = Path(row["path"]).name
        copies = [name for name in declared if isinstance(name, str) and Path(name).name == source_name]
        if len(copies) != 1:
            checks.append("StudyWorld needs exactly one hashed project source copy")
        else:
            try:
                if sha_file(local_file(root, copies[0])) != sha_file(Path(row["path"])):
                    checks.append("project StudyWorld source differs from selected reusable source")
            except ValueError as exc:
                checks.append(str(exc))
        names = {field: impl.get(field) for field in ("props", "world_contract", "style_params", "style")}
        if any(not isinstance(name, str) or name not in declared for name in names.values()):
            checks.append("StudyWorld props/world_contract/style_params/style must be hashed implementation inputs")
        else:
            try:
                from study_world_contract import continuity, validate_scene as validate_study_scene, validate_style
                data = {}
                for field, name in names.items():
                    path = local_file(root, name)
                    if path.suffix.lower() != ".json":
                        checks.append("StudyWorld " + field + " must be JSON")
                    else:
                        data[field] = json_file(path)
                if len(data) == len(names):
                    scene = data["props"].get("scene", data["props"])
                    if rid == "study_world:StudyWorld" and (
                        any(action.get("kind") == "exit" for action in scene.get("actions", []) if isinstance(action, dict)) or
                        "hidden" in (scene.get("initialStates") or {}).values()
                    ):
                        checks.append("legacy StudyWorld source cannot render exit/hidden; select StudyWorldVisualV2")
                    checks.extend(validate_style(root, data["style"], data["style_params"], plan.get("design_sha256")))
                    checks.extend(validate_study_scene(data["world_contract"], scene, data["style"], plan, segment, declared, root))
                    parts = [part for part in plan.get("segments", []) if isinstance(part, dict)]
                    index = next((i for i, part in enumerate(parts) if part.get("id") == sid), None)
                    if index is not None:
                        for prev, following in ((parts[index], parts[index + 1]) if index + 1 < len(parts) else (None, None),
                                                (parts[index - 1], parts[index]) if index > 0 else (None, None)):
                            if not prev or not following:
                                continue
                            earlier = prev.get("chosen_resource") or {}
                            later = following.get("chosen_resource") or {}
                            if earlier.get("resource_id") != rid or later.get("resource_id") != rid:
                                continue
                            a = earlier.get("implementation") or {}
                            b = later.get("implementation") or {}
                            if not all(isinstance(v, str) for v in (a.get("world_contract"), a.get("props"), b.get("world_contract"), b.get("props"))):
                                checks.append("adjacent StudyWorld shots need bound world and scene inputs")
                                continue
                            if a["world_contract"] != b["world_contract"]:
                                checks.append("adjacent StudyWorld shots need one shared world contract path")
                                continue
                            a_world = json_file(local_file(root, a["world_contract"]))
                            b_world = json_file(local_file(root, b["world_contract"]))
                            a_scene_payload = json_file(local_file(root, a["props"]))
                            b_scene_payload = json_file(local_file(root, b["props"]))
                            checks.extend(continuity(a_world, a_scene_payload.get("scene", a_scene_payload),
                                                     b_world, b_scene_payload.get("scene", b_scene_payload)))
            except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
                checks.append(str(exc))
    return {"segment_id": sid, "candidate": row, "chosen_resource": chosen,
            "implementation": impl, "ready_for_handoff": not checks,
            "issues": checks, "execution_responsibility": "the project owner adapts/executes the selected scene; another reviewer verifies bytes and meaning; formal gates remain separate"}


def local_command(root, plan, sid, output):
    root = Path(root).resolve()
    report = resolve(root, plan, sid)
    impl = report["implementation"]
    if not report["ready_for_handoff"]:
        raise ValueError("selected implementation cannot run: " + "; ".join(report["issues"]))
    if impl["mode"] != "local_remotion":
        raise ValueError("only a local_remotion implementation can be prepared")
    entry = local_file(root, impl.get("entry"))
    declared = {item.get("path") for item in impl["inputs"] if isinstance(item, dict)}
    if impl["entry"] not in declared:
        raise ValueError("render entry must be hashed in implementation.inputs")
    cid = impl.get("composition_id")
    if not isinstance(cid, str) or not COMPOSITION.fullmatch(cid):
        raise ValueError("invalid composition ID")
    relative = Path(output)
    if relative.is_absolute() or ".." in relative.parts or relative.suffix.lower() not in MEDIA_EXT:
        raise ValueError("output must be a project-relative media path")
    target = root / relative
    if not target.parent.is_dir() or target.is_symlink() or not target.resolve().is_relative_to(root):
        raise ValueError("output directory must already exist in project")
    if target.exists():
        raise ValueError("output already exists; choose a new versioned path")
    runtime_value = os.environ.get("MUZHI_REMOTION_RUNTIME")
    browser_value = os.environ.get("MUZHI_BROWSER_EXECUTABLE")
    if not runtime_value or not browser_value:
        raise ValueError("set MUZHI_REMOTION_RUNTIME and MUZHI_BROWSER_EXECUTABLE explicitly before local rendering; no browser download is allowed")
    runtime = Path(runtime_value).expanduser().resolve()
    cli = runtime / "node_modules/@remotion/cli/remotion-cli.js"
    node = shutil.which("node")
    browser = Path(browser_value).expanduser().resolve()
    if not node or not cli.is_file() or not browser.is_file():
        raise ValueError("existing Node, Remotion CLI or explicit browser missing; no download is allowed")
    command = [node, str(cli), "render", str(entry), cid, str(target),
               "--concurrency=1", "--browser-executable=" + str(browser)]
    if plan.get("timebase_kind") == "authored_screen_timing":
        command.append("--muted")  # Installed Remotion CLI omits the audio track with this flag.
    if impl.get("props"):
        props = local_file(root, impl["props"])
        if impl["props"] not in declared:
            raise ValueError("render props must be hashed in implementation.inputs")
        command.append("--props=" + str(props))
    return {"command": command, "cwd": str(runtime), "output": relative.as_posix(),
            "boundary": "explicit local executable and project paths; no shell or external metadata execution; project owner controls the render slot"}


def preproduction_check(root, plan_name="motion-plan.json", contract_name="artifacts/director-storyboard.json", require_board=True):
    root = Path(root).resolve()
    errors = []
    plan = None
    try:
        plan_path = local_file(root, plan_name)
        contract_path = local_file(root, contract_name)
        plan = json_file(plan_path)
        contract = json_file(contract_path)
        if contract.get("preproduction_contract_version") != 1:
            errors.append("preproduction contract v1 required")
        if contract.get("motion_plan_source") != plan_name or contract.get("motion_plan_sha256") != sha_file(plan_path):
            errors.append("director contract motion plan hash drift")
        if contract.get("design_source") != "design.md" or contract.get("design_sha256") != sha_file(local_file(root, "design.md")):
            errors.append("director contract design hash drift")
        from motion_plan import validate as validate_plan
        result = validate_plan(plan, root, "storyboard")
        errors.extend("motion plan: " + e for e in result["errors"])
        ids = [s.get("id") for s in plan.get("segments", []) if isinstance(s, dict)]
        shots = contract.get("shots")
        if not isinstance(shots, list) or [s.get("segment_id") for s in shots if isinstance(s, dict)] != ids:
            errors.append("director shots must cover plan segments once in order")
        for sid in ids:
            result = verify_preview(root, plan, sid)
            errors.extend(sid + ": " + e for e in result["errors"])
        if plan.get("semantic_contract_version") == 2 and isinstance(shots, list):
            from expression_contract import cue_window, validate_evidence
            from project_policy import requires_visual_decision

            strict_decision = requires_visual_decision(root, plan)

            for segment, shot in zip(plan.get("segments", []), shots):
                if not isinstance(segment, dict) or not isinstance(shot, dict):
                    continue
                sid = segment.get("id")
                requirements = segment.get("expression_requirements", [])
                binding = segment.get("preview_binding") or {}
                static_binding = binding.get("static_reading") is True
                if static_binding and (segment.get("visual_route") not in {"official_evidence", "sourced_chart", "real_media"} or
                                       not isinstance(shot.get("static_reading_reason"), str) or not shot["static_reading_reason"].strip()):
                    errors.append(str(sid) + ": static reading needs a permitted route and shot reason")
                windows = {}
                local_windows = {}
                segment_start = None
                if strict_decision:
                    try:
                        segment_start = cue_window(root, plan, segment.get("srt_cue_ids"))[0]
                    except (ValueError, OSError, UnicodeError) as exc:
                        errors.append(str(sid) + ": " + str(exc))
                for requirement in requirements if isinstance(requirements, list) else []:
                    if isinstance(requirement, dict) and isinstance(requirement.get("id"), str) and (requirement.get("proof_kind") == "static_reading" or strict_decision):
                        try:
                            window = cue_window(root, plan, requirement.get("cue_ids"))
                            if requirement.get("proof_kind") == "static_reading":
                                windows[requirement["id"]] = window
                            if segment_start is not None:
                                local_windows[requirement["id"]] = (window[0] - segment_start, window[1] - segment_start)
                        except (ValueError, OSError, UnicodeError) as exc:
                            errors.append(str(sid) + ": " + str(exc))
                validate_evidence(requirements, shot.get("visual_action_check"), shot.get("keyframes", []),
                                  binding.get("preview_media"), errors, str(sid), cue_windows=windows,
                                  expected_domain="preview_local", local_cue_windows=local_windows,
                                  strict_continuous=strict_decision,
                                  static_time_domain="authored_global" if plan.get("timebase_kind") == "authored_screen_timing" else "srt_global")
        if require_board:
            board = {"path": contract.get("board_path"), "sha256": contract.get("board_sha256")}
            _bound_file(root, board, {".html"})
            regenerated = board_html(root, plan, contract, board["path"])
            if hashlib.sha256(regenerated.encode("utf-8")).hexdigest() != board["sha256"].lower():
                errors.append("director board drifts from current plan or shot contract")
    except (ValueError, OSError, TypeError, KeyError, json.JSONDecodeError) as exc:
        errors.append(str(exc))
    actual_media_ready = (not errors and isinstance(plan, dict) and
                          isinstance(plan.get("segments"), list) and bool(plan["segments"]) and
                          all(isinstance(segment, dict) and isinstance(segment.get("preview_binding"), dict) and
                              isinstance(segment["preview_binding"].get("preview_media"), dict)
                              for segment in plan["segments"]))
    return {"passed": not errors, "stage": "preview", "errors": errors,
            "actual_media_ready": actual_media_ready,
            "completion_state": "preview_media_bound" if actual_media_ready else "plan_only",
            "seven_step_complete": False, "delivery_ready": False,
            "production_ready": False, "user_approval_recorded": False,
            "boundary": "silent preproduction readback; formal storyboard/batch/master and original voice gates remain in force"}


def _portable_source_label(row):
    """A stable display location, never the checkout/cache machine root."""
    path = row.get("path")
    if not isinstance(path, str) or not path:
        return "资源ID定位；无本地文件"
    candidate = Path(path).resolve()
    for prefix, base in (("plugin", PLUGIN), ("workspace", WORKSPACE)):
        root = base.resolve()
        if candidate.is_relative_to(root):
            return prefix + ":" + candidate.relative_to(root).as_posix()
    return "外部原件按资源ID和当前来源哈希定位"


def _expression_summary(segment, implementation, action):
    """Keep the v2 board readable while retaining trace details on demand."""
    esc = lambda value: html.escape(str(value if value is not None else ""))
    requirements = segment.get("expression_requirements")
    mapping = implementation.get("expression_map")
    evidence = action.get("evidence_by_requirement") if isinstance(action, dict) else None
    requirements = requirements if isinstance(requirements, list) else []
    mapping = mapping if isinstance(mapping, list) else []
    evidence = evidence if isinstance(evidence, list) else []
    roles = {"main": "主画面", "auxiliary": "辅助动效", "original": "本片原创补层"}
    items = []
    for requirement in requirements:
        if not isinstance(requirement, dict):
            continue
        rid = requirement.get("id")
        assigned = [item for item in mapping if isinstance(item, dict) and item.get("requirement_id") == rid]
        actual = next((item for item in evidence if isinstance(item, dict) and item.get("requirement_id") == rid), {})
        responsibility = "、".join(dict.fromkeys(roles.get(item.get("responsible_part"), "待明确") for item in assigned)) or "待明确"
        start, end = actual.get("start_seconds"), actual.get("end_seconds")
        interval = f"{start:g}–{end:g} 秒" if all(type(value) in (int, float) and math.isfinite(value) for value in (start, end)) else "时间未核"
        static = actual.get("evidence_kind") == "static_frame"
        if static:
            location = ("作者屏幕阅读窗口 " if actual.get("time_domain") == "authored_global" else
                        "真实字幕阅读窗口 ") + interval
            frame_note = "源帧已绑定" if actual.get("frame_path") else "源帧未核"
            observation = actual.get("observed_reading")
            technical_frame = esc(actual.get("frame_path"))
            technical_hash = esc(actual.get("frame_sha256"))
        else:
            location = "本段视频 " + interval
            paths = actual.get("keyframe_paths")
            frame_note = "关键帧已绑定" if isinstance(paths, list) and paths else "关键帧未核"
            observation = actual.get("observed_state_change")
            technical_frame = esc(", ".join(paths) if isinstance(paths, list) else "")
            technical_hash = esc(actual.get("media_sha256"))
        outcome = "已记录画面证据，仍需人工核看" if actual.get("status") == "observed" else "尚无完整画面证据"
        technical_assignments = "; ".join(
            f"{esc(item.get('responsible_part'))} · {esc(item.get('resource_id'))} · "
            f"{esc(', '.join(item.get('project_input_paths', [])) if isinstance(item.get('project_input_paths'), list) else '')}"
            for item in assigned)
        items.append(
            f"<li><b>{esc(requirement.get('must_be_seen'))}</b>"
            f"<br>由{esc(responsibility)}负责；{esc(location)}，{esc(frame_note)}。"
            f"<br>目前记录的结果：{esc(observation or '尚未观察')}；{outcome}。"
            f"<details><summary>技术定位</summary>义务 ID：<code>{esc(rid)}</code>；"
            f"实施：<code>{technical_assignments}</code>；证据帧：<code>{technical_frame}</code>；"
            f"证据 SHA：<code>{technical_hash}</code>；时间域：<code>{esc(actual.get('time_domain'))}</code></details></li>")
    return "<p>这一镜不能漏的画面</p><ul>" + "".join(items) + "</ul>"


def board_html(root, plan, contract, output):
    root = Path(root).resolve()
    output = (root / output).resolve()
    if not output.is_relative_to(root) or output.suffix.lower() != ".html":
        raise ValueError("board output must be a project-relative HTML path")
    if contract.get("preproduction_contract_version") != 1:
        raise ValueError("preproduction contract v1 required")
    identity_version = contract.get("board_source_identity_version", 1)
    if type(identity_version) is not int or identity_version not in (1, 2):
        raise ValueError("board_source_identity_version must be 1 or 2")
    plan_source = contract.get("motion_plan_source")
    if not isinstance(plan_source, str) or contract.get("motion_plan_sha256") != sha_file(local_file(root, plan_source)):
        raise ValueError("director contract motion plan hash drift")
    if contract.get("design_source") != "design.md" or contract.get("design_sha256") != sha_file(local_file(root, "design.md")):
        raise ValueError("director contract design hash drift")
    shots = contract.get("shots")
    ids = [s.get("id") for s in plan.get("segments", []) if isinstance(s, dict)]
    if not isinstance(shots, list) or [s.get("segment_id") for s in shots if isinstance(s, dict)] != ids:
        raise ValueError("contract shots must cover plan segments in order")
    for sid in ids:
        result = verify_preview(root, plan, sid)
        if not result["passed"]:
            raise ValueError(sid + ": " + "; ".join(result["errors"]))
    audio_source = plan.get("audio_source") if plan.get("timebase_kind") == "real_voice_srt" else None
    if audio_source and plan.get("audio_sha256") != sha_file(local_file(root, audio_source)):
        raise ValueError("director board final voice hash drift")
    def esc(v):
        return html.escape(str(v if v is not None else ""))
    def href(name):
        relative = os.path.relpath(root / name, output.parent).replace("\\", "/")
        return quote(relative, safe="/.-_")
    sections = []
    for index, (segment, shot) in enumerate(zip(plan["segments"], shots), 1):
        binding = segment["preview_binding"]
        def option_title(option):
            return option.get("display_title") or option.get("title") or ("本片原创镜头" if option.get("source") == "original" else option.get("source") or "候选机制")
        def provenance_label(option):
            receipt = option.get("source_provenance")
            if not isinstance(receipt, dict):
                return ""
            status = {"read": "原件已读", "not_read": "仅索引未读", "missing": "索引在但原件缺失"}.get(receipt.get("reading_status"), "状态待核")
            usage = {"reference_only": "机制借鉴", "planned_adaptation": "计划改编", "planned_backend": "计划调用后端"}.get(receipt.get("usage_kind"), "使用边界待核")
            return f" · {status} · {usage}"
        def provenance_detail(option):
            receipt = option.get("source_provenance")
            if not isinstance(receipt, dict):
                return ""
            return f" · 原件SHA：{esc(receipt.get('source_sha256'))} · 阅读范围：{esc(receipt.get('read_scope'))}"
        options = "".join(f"<li><b>{esc(option_title(o))}</b> · {esc(o.get('reason'))}"
                          f"{esc(provenance_label(o))}"
                          f"{(' · ' + esc(o.get('adaptation'))) if o.get('adaptation') else ''}"
                          f"{(' · 覆盖：' + esc(', '.join(o.get('covers_requirement_ids', [])))) if isinstance(o.get('covers_requirement_ids'), list) else ''}"
                          f"{(' · 缺口：' + esc('; '.join(o.get('gaps', [])))) if isinstance(o.get('gaps'), list) and o.get('gaps') else ''}"
                          f"<details><summary>资源定位</summary><code>{esc(o.get('resource_id'))}</code> · {esc(o.get('source'))}"
                          f"{provenance_detail(o)}</details></li>"
                          for o in segment.get("resource_options", []))
        frames = "".join(f"<figure><img src='{href(f['path'])}' alt='{esc(segment['id'])}实际帧'><figcaption>{esc(f['path'])}</figcaption></figure>" for f in binding["keyframes"])
        chosen = segment["chosen_resource"]
        chosen_option = next(o for o in segment["resource_options"] if o.get("resource_id") == chosen["resource_id"])
        impl = chosen["implementation"]
        auxiliary = "".join(
            f"<li>{esc(item.get('resource_id'))} · {esc(item.get('usage'))} · {esc(item.get('mechanism'))}"
            f" · {'实际动作：' + esc(item.get('visible_action')) if item.get('usage') != 'reference_only' else '仅供机制参考'}"
            f" · 权利依据：{esc(item.get('rights_basis'))} · 成本：{esc(item.get('cost_boundary') or '待核')}</li>"
            for item in impl.get("auxiliary_sources", []) if isinstance(item, dict)
        ) if identity_version == 2 and isinstance(impl.get("auxiliary_sources"), list) else ""
        actions = shot.get("visual_action_check") or {}
        expression = _expression_summary(segment, impl, actions) if plan.get("semantic_contract_version") == 2 else ""
        continuity = segment.get("continuity") or {}
        evidence = "".join(f"<li>{esc(e.get('ref'))} · {'已核' if e.get('verified') else '待核'} · {esc(e.get('note') or e.get('source'))}</li>"
                           for e in segment.get("evidence", []) if isinstance(e, dict))
        source_snapshot = binding.get("source_snapshot")
        if isinstance(source_snapshot, dict):
            row = selected([source_snapshot["id"]])[0]
            source_text = (f"{esc(row.get('title'))} [{esc(row.get('role'))}] · {esc(row.get('status'))}"
                           f"<br>权利/边界：{esc(row.get('rights'))}")
            if identity_version == 2:
                source_technical = (f"<p>稳定资源ID：{esc(source_snapshot.get('id'))}</p>"
                                    f"<p>相对来源位置：{esc(_portable_source_label(row))}</p>"
                                    f"<p>源文件 SHA-256：{esc(source_snapshot.get('source_sha256'))}</p>")
            else:
                source_technical = (f"<p>路径：{esc(row.get('path'))}</p><p>源记录 SHA-256：{esc(source_snapshot.get('record_sha256'))}</p>"
                                    f"<p>源文件 SHA-256：{esc(source_snapshot.get('source_sha256'))}</p>")
        else:
            source_text = "本片原创；源代码列于实施输入"
            source_technical = ""
        review = shot.get("review")
        review_text = "; ".join(f"{esc(k)}: {esc(v.get('status') if isinstance(v, dict) else v)}" for k, v in review.items()) if isinstance(review, dict) else "待审核"
        changes = shot.get("modification_points") or segment.get("modification_points") or []
        change_text = "; ".join(esc(v) for v in changes) if isinstance(changes, list) else esc(changes)
        static_binding = binding.get("static_reading") is True
        interval = None if static_binding else _preview_interval(segment, binding["preview_media"]["duration_seconds"])
        interval_text = ("真实cue阅读窗口（静态原件帧）" if static_binding else
                         f"{interval[0]:g}–{interval[1]:g} 秒" if interval else "整段媒体（未给独立镜头秒域）")
        video_attrs = f" data-start='{interval[0]:g}' data-end='{interval[1]:g}'" if interval else ""
        video_html = "" if static_binding else f"<video controls playsinline preload='metadata'{video_attrs} src='{href(binding['preview_media']['path'])}'></video>"
        audio_html = ""
        if audio_source:
            from expression_contract import cue_window
            voice_start, voice_end = cue_window(root, plan, segment.get("srt_cue_ids"))
            audio_html = (f"<p>本镜原声试听（{voice_start:g}–{voice_end:g} 秒）</p>"
                          f"<audio controls preload='metadata' data-start='{voice_start:g}' data-end='{voice_end:g}' "
                          f"src='{href(audio_source)}'></audio>")
        sections.append(f"<section><h2>镜头 {index} · {esc(segment.get('semantic_role') or segment.get('audience_takeaway'))}</h2>"
                        f"<p class='quote'>{esc(segment.get('spoken_text'))}</p><p>原意/易误解：{esc(segment.get('original_intent'))}</p>"
                        f"<p>本镜要做：{esc(segment.get('shot_purpose'))} · 观众应看懂：{esc(segment.get('audience_takeaway'))}</p>"
                        f"<p>时间：{esc(segment.get('srt_timecode') or segment.get('screen_timing') or '无声预制时序')}；本镜播放 {interval_text}</p>"
                        f"<p>候选比较</p><ul>{options}</ul><p>选定：{esc(option_title(chosen_option))} · {esc(chosen['reason'])}</p>"
                        f"{('<p>辅来源及各自职责</p><ul>' + auxiliary + '</ul>') if auxiliary else ''}"
                        f"<p>实施：{esc(MODE_LABELS.get(impl['mode'], impl['mode']))} · {esc(impl['adaptation'])}</p><p>退路：{esc(impl['fallback'])}</p>"
                        f"{expression}"
                        f"<p>来源：{source_text}</p><p>事实/证据</p><ul>{evidence or '<li>本段无外部精确信息</li>'}</ul>"
                        f"<p>起：{esc(actions.get('entry'))} → 变：{esc(actions.get('interaction'))} → 终：{esc(actions.get('result'))}</p>"
                        f"<p>阅读停留：{esc(actions.get('reading_hold') or segment.get('reading_plan'))} · 退出：{esc(actions.get('exit'))}</p>"
                        f"<p>接棒：{esc(continuity.get('exit') or segment.get('handoff'))} → {esc(continuity.get('next_segment_id'))}</p>"
                        f"<div class='frames'>{frames}</div>{video_html}{audio_html}"
                        f"<p>当前审核：{review_text}</p><p>可改点：{change_text or '待观众反馈'}</p>"
                        f"<details class='small'><summary>技术定位与同版校验</summary><p>段 ID：<code>{esc(segment['id'])}</code></p>"
                        f"<p>选定资源 ID：<code>{esc(chosen['resource_id'])}</code></p>{source_technical}"
                        f"<p>实际媒体 SHA-256：{esc(binding.get('preview_media', {}).get('sha256') if not static_binding else '静态源帧，无连续媒体')}</p></details></section>")
    title = esc(contract.get("title") or "同版镜头预览")
    script = "<script>document.querySelectorAll('video[data-start],audio[data-start]').forEach(v=>{const a=Number(v.dataset.start),b=Number(v.dataset.end);v.addEventListener('loadedmetadata',()=>{v.currentTime=a});v.addEventListener('play',()=>{if(v.currentTime<a||v.currentTime>=b)v.currentTime=a});v.addEventListener('timeupdate',()=>{if(v.currentTime>=b){v.pause();v.currentTime=b}})});</script>"
    has_voiced_preview = bool(audio_source) or plan.get("timebase_kind") == "real_voice_srt" and any(
        (segment.get("preview_binding") or {}).get("preview_media", {}).get("audio_streams", 0) > 0
        for segment in plan["segments"])
    from project_policy import requires_visual_decision
    if requires_visual_decision(root, plan):
        all_video_bound = all(isinstance((segment.get("preview_binding") or {}).get("preview_media"), dict)
                              for segment in plan["segments"])
        media_label = "同版连续媒体和关键帧已绑定" if all_video_bound else "静读关键帧已绑定；连续媒体不适用或仍待核"
        review_label = ("独立审查记录已附，结论仍以审者回执为准" if isinstance(contract.get("independent_review"), dict)
                        else "待独立原意复述和正常速度审看")
        preface = f"{'有声' if has_voiced_preview else '无声'}片前试件：计划已形成；{media_label}；{review_label}。非正式成片，用户批准另行记录。"
    else:
        preface = ("有声片前预制，非正式成片；动静范围按逐镜记录。请审镜头关系、准确字、阅读与实际运动；正式用户批准另行记录。"
                   if has_voiced_preview else
                   "无声预制 · 原计划与真实媒体同版。请审镜头关系、准确字、阅读与实际运动；正式用户批准和原声制作另行记录。")
    return "<!doctype html><html lang='zh-CN'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>"+title+"</title><style>body{font:18px/1.65 system-ui,'Microsoft YaHei',sans-serif;background:#eee9df;color:#27231e;max-width:1050px;margin:auto;padding:22px}section{background:#fffaf1;padding:24px;margin:24px 0;border:1px solid #c7baaa;border-radius:16px}h1,h2{line-height:1.25}.quote{font-size:1.2em;font-weight:650}.frames{display:flex;gap:12px;overflow:auto}figure{margin:0;min-width:180px;max-width:260px}img{width:100%;border-radius:8px}figcaption,.small{font-size:.75em;overflow-wrap:anywhere}video{display:block;width:min(100%,400px);margin:18px auto;background:#111}audio{display:block;width:min(100%,400px);margin:12px auto}li{margin:.3em 0}details{font-size:.8em;color:#584b3d}code{overflow-wrap:anywhere}</style><h1>"+title+"</h1><p>"+preface+"</p>"+"".join(sections)+script+"</html>"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    subs.add_parser("sources")
    search = subs.add_parser("search"); search.add_argument("terms", nargs="*"); search.add_argument("--role"); search.add_argument("--per-source", type=int, default=6); search.add_argument("--available-only", action="store_true")
    receipt = subs.add_parser("search-receipt"); receipt.add_argument("terms", nargs="+"); receipt.add_argument("--role"); receipt.add_argument("--per-source", type=int, default=2)
    reading = subs.add_parser("read"); reading.add_argument("--ids", required=True)
    for command in ("resolve", "prepare", "run-local", "render-start", "render-finish", "bind-preview", "verify-preview"):
        p = subs.add_parser(command); p.add_argument("--project", required=True); p.add_argument("--plan", default="motion-plan.json"); p.add_argument("--segment", required=True)
        if command in ("prepare", "run-local"):
            p.add_argument("--output", required=True)
        if command == "render-start":
            p.add_argument("--output", required=True); p.add_argument("--receipt", required=True)
            p.add_argument("--command-text", required=True); p.add_argument("--parent-receipt")
        if command == "render-finish":
            p.add_argument("--receipt", required=True); p.add_argument("--exit-code", required=True, type=int)
            p.add_argument("--command-log")
        if command == "bind-preview":
            p.add_argument("--frames", required=True, help="comma-separated project-relative actual images"); p.add_argument("--media", required=True)
            p.add_argument("--render-receipt")
    board = subs.add_parser("board"); board.add_argument("--project", required=True); board.add_argument("--plan", default="motion-plan.json"); board.add_argument("--contract", default="artifacts/director-storyboard.json"); board.add_argument("--output", required=True)
    check = subs.add_parser("check-preview"); check.add_argument("--project", required=True); check.add_argument("--plan", default="motion-plan.json"); check.add_argument("--contract", default="artifacts/director-storyboard.json")
    args = parser.parse_args(argv)
    try:
        if args.command == "sources":
            value = source_status()
        elif args.command == "search":
            value = discover(args.terms, args.role, args.per_source, not args.available_only)
        elif args.command == "search-receipt":
            value = search_receipt(args.terms, args.role, args.per_source)
        elif args.command == "read":
            value = read([x for x in args.ids.split(",") if x])
        elif args.command == "check-preview":
            value = preproduction_check(args.project, args.plan, args.contract)
        else:
            root = Path(args.project).resolve()
            plan = json_file(local_file(root, args.plan))
            if args.command == "resolve":
                value = resolve(root, plan, args.segment)
            elif args.command == "prepare":
                value = local_command(root, plan, args.segment, args.output)
            elif args.command == "render-start":
                value = render_receipt_start(root, plan, args.segment, args.output, args.receipt,
                                             args.command_text, args.parent_receipt)
            elif args.command == "render-finish":
                value = render_receipt_finish(root, plan, args.segment, args.receipt, args.exit_code,
                                              args.command_log)
            elif args.command == "run-local":
                prepared = local_command(root, plan, args.segment, args.output)
                from project_policy import requires_visual_decision
                auto_receipt = args.output + ".render-receipt.json" if requires_visual_decision(root, plan) else None
                if auto_receipt:
                    render_receipt_start(root, plan, args.segment, args.output, auto_receipt,
                                         " ".join(prepared["command"]))
                run = subprocess.run(prepared["command"], cwd=prepared["cwd"], capture_output=True, text=True, timeout=900)
                value = {"passed": run.returncode == 0, "exit_code": run.returncode, "stdout": run.stdout[-2000:], "stderr": run.stderr[-2000:], "prepared": prepared}
                if run.returncode == 0:
                    rendered = local_file(root, args.output)
                    value["media"] = {"path": args.output, "sha256": sha_file(rendered), **_probe_media(rendered)}
                    if auto_receipt:
                        value["render_receipt"] = render_receipt_finish(root, plan, args.segment, auto_receipt, 0,
                                                                         executed_by_tool=True)
                    if plan.get("timebase_kind") == "authored_screen_timing" and value["media"]["audio_streams"]:
                        value["passed"] = False
                        value["error"] = "renderer added an audio stream; use an explicitly versioned video-only remux before binding"
            elif args.command == "bind-preview":
                value = bind_preview(root, plan, args.segment, [x for x in args.frames.split(",") if x], args.media,
                                     args.render_receipt)
            elif args.command == "verify-preview":
                value = verify_preview(root, plan, args.segment)
            else:
                contract = json_file(local_file(root, args.contract))
                markup = board_html(root, plan, contract, args.output)
                target = root / args.output
                if target.exists() and target.is_symlink():
                    raise ValueError("board output symlink forbidden")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(markup, encoding="utf-8")
                value = {"board_path": args.output, "board_sha256": sha_file(target), "bytes": target.stat().st_size,
                         "boundary": "generated from original plan and director contract; approval remains pending"}
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 0 if not isinstance(value, dict) or value.get("passed", True) else 1
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"passed": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
