from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


REQUIRED_SECTIONS = [
    "一句话设计目标",
    "唯一视觉基准",
    "必须保持的视觉DNA",
    "我们保留什么，只改什么",
    "正确的资产生成链路",
    "供应商的边界",
    "核心语义文字的正确嵌套",
    "当前生产闸门",
    "一票否决",
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def resolve(project_root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else project_root / path


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate editorial design.md and its locked style references.")
    parser.add_argument("--lock", required=True, help="Path to artifacts/design-lock.json")
    parser.add_argument("--require-approved", action="store_true")
    args = parser.parse_args()

    lock_path = Path(args.lock).resolve()
    errors: list[str] = []
    if not lock_path.exists():
        print(json.dumps({"ok": False, "errors": [f"lock missing: {lock_path}"]}, ensure_ascii=False, indent=2))
        return 1

    try:
        data = json.loads(lock_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(json.dumps({"ok": False, "errors": [f"invalid json: {exc}"]}, ensure_ascii=False, indent=2))
        return 1

    project_root = lock_path.parent.parent
    if str(data.get("schema_version", "")) != "1.0":
        errors.append("schema_version must be 1.0")

    design_path = resolve(project_root, data.get("design_path", "design.md"))
    if not design_path.exists():
        errors.append(f"design missing: {design_path}")
        design_text = ""
    else:
        actual_design_hash = sha256(design_path)
        if actual_design_hash != str(data.get("design_sha256", "")).upper():
            errors.append("design sha256 mismatch")
        design_text = design_path.read_text(encoding="utf-8")
        for section in REQUIRED_SECTIONS:
            if section not in design_text:
                errors.append(f"design section missing: {section}")

    refs = data.get("style_references", [])
    if len(refs) < 2:
        errors.append("at least two style references are required")
    ref_results = []
    for idx, ref in enumerate(refs):
        path = resolve(project_root, ref.get("path", ""))
        if not path.exists():
            errors.append(f"style reference missing[{idx}]: {path}")
            ref_results.append({"path": str(path), "ok": False})
            continue
        actual = sha256(path)
        expected = str(ref.get("sha256", "")).upper()
        if actual != expected:
            errors.append(f"style reference sha256 mismatch[{idx}]: {path}")
        ref_results.append({"path": str(path), "sha256": actual, "ok": actual == expected})

    policy = data.get("supplier_policy", {})
    required_policy = {
        "image_generation_reads_design_md": True,
        "image_to_video_requires_approved_frames": True,
        "image_to_video_may_redefine_style": False,
        "generated_readable_chinese_allowed": False,
    }
    for key, expected in required_policy.items():
        if policy.get(key) is not expected:
            errors.append(f"supplier policy invalid: {key} must be {expected}")

    if args.require_approved:
        if data.get("status") != "approved":
            errors.append("design lock is not approved")
        approval = data.get("approval", {})
        for key in ("approved_by", "approval_quote", "approved_at"):
            if not str(approval.get(key, "")).strip():
                errors.append(f"approval field missing: {key}")

    result = {
        "ok": not errors,
        "project_root": str(project_root),
        "design_path": str(design_path),
        "design_sha256": sha256(design_path) if design_path.exists() else "",
        "style_reference_count": len(refs),
        "style_references": ref_results,
        "status": data.get("status"),
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
