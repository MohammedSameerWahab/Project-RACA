from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from src.analysis.navigation import CodeNavigationService
from src.workspace import WorkspaceError

PYTHON_FRAME = re.compile(
    r'^\s*File "([^"]+)", line (\d+)(?:, in ([^\r\n]+))?',
    re.MULTILINE,
)
NODE_FRAME = re.compile(
    r"^\s*at\s+(?:(.*?)\s+\()?(.+):(\d+):(\d+)\)?\s*$",
    re.MULTILINE,
)


def parse_stack_trace(text: str) -> dict[str, Any]:
    if not text.strip():
        raise ValueError("Paste a stack trace or exception.")
    if len(text) > 40000:
        raise ValueError("Stack trace must be 40,000 characters or fewer.")

    frames: list[dict[str, Any]] = []
    for match in PYTHON_FRAME.finditer(text):
        frames.append({
            "raw_path": match.group(1),
            "line": int(match.group(2)),
            "function": (match.group(3) or "<module>").strip(),
            "format": "python",
        })
    if not frames:
        for match in NODE_FRAME.finditer(text):
            frames.append({
                "raw_path": match.group(2),
                "line": int(match.group(3)),
                "column": int(match.group(4)),
                "function": (match.group(1) or "<anonymous>").strip(),
                "format": "node",
            })

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    exception = next(
        (
            line
            for line in reversed(lines)
            if not line.startswith("Traceback (")
            and not line.startswith("File ")
            and not line.startswith("at ")
        ),
        "",
    )
    exception_type, separator, message = exception.partition(":")
    if not separator:
        exception_type, message = exception, ""
    return {
        "exception_type": exception_type.strip()[:200],
        "message": message.strip()[:1000],
        "frames": frames[:100],
    }


def resolve_stack_frames(
    parsed: dict[str, Any],
    navigation: CodeNavigationService,
) -> list[dict[str, Any]]:
    root = navigation.root.resolve()
    resolved: list[dict[str, Any]] = []
    for frame in parsed["frames"]:
        raw_path = str(frame["raw_path"])
        candidate = Path(raw_path)
        relative_path: str | None = None
        if candidate.is_absolute():
            try:
                relative_path = candidate.resolve().relative_to(root).as_posix()
            except (OSError, ValueError):
                relative_path = None
        else:
            relative = raw_path.replace("\\", "/").removeprefix("./")
            try:
                navigation.workspace.read_file(relative)
            except WorkspaceError:
                relative_path = None
            else:
                relative_path = relative

        result = {
            "file_path": relative_path,
            "line": frame["line"],
            "function": frame["function"],
            "resolved": False,
            "external": relative_path is None,
            "source": None,
        }
        if relative_path is not None:
            try:
                result["source"] = navigation.source_excerpt(
                    relative_path, int(frame["line"])
                )
                result["resolved"] = True
            except (WorkspaceError, ValueError):
                result["file_path"] = None
                result["external"] = True
        resolved.append(result)
    return resolved
