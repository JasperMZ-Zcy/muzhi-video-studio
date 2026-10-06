"""Record one project's chosen music method without producing or licensing audio."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RELATIVE = "artifacts/music-method.json"
METHODS = {"code_local", "ai_verified", "provided", "none"}


def status(project: str | Path) -> dict[str, Any]:
    root = Path(project).resolve()
    if not root.is_dir():
        raise ValueError("project directory missing")
    path = root / RELATIVE
    if path.is_symlink():
        raise ValueError("music method state cannot be a symlink")
    if not path.exists():
        return {"selected": False, "method": None, "selection": None}
    state = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(state, dict) or state.get("schema_version") != 1:
        raise ValueError("invalid music method state")
    selection = state.get("selection")
    if (not isinstance(selection, dict) or selection.get("method") not in METHODS or
            selection.get("scope") != "this_project" or
            not isinstance(selection.get("quote"), str) or len(selection["quote"].strip()) < 4):
        raise ValueError("music method state needs a valid this-project method and actual choice quote")
    return {"selected": True,
            "method": selection["method"], "selection": selection,
            "history": state.get("history", [])}


def select(project: str | Path, method: str, quote: str) -> dict[str, Any]:
    if method not in METHODS or not isinstance(quote, str) or len(quote.strip()) < 4:
        raise ValueError("choose code_local, ai_verified, provided or none with the actual user choice")
    root = Path(project).resolve()
    current = status(root)
    prior = current.get("selection")
    if prior and prior.get("method") == method:
        return {"changed": False, "selection": prior}
    selection = {"method": method, "quote": quote.strip(), "scope": "this_project",
                 "selected_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    history = [*current.get("history", []), selection]
    path = root / RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": 1, "selection": selection, "history": history},
                               ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"changed": True, "selection": selection}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("status", "select"))
    parser.add_argument("--project", required=True)
    parser.add_argument("--method", choices=sorted(METHODS))
    parser.add_argument("--quote")
    args = parser.parse_args()
    try:
        result = status(args.project) if args.command == "status" else select(args.project, args.method, args.quote)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"passed": False, "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
