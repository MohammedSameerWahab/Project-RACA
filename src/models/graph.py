from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CodeNode:
    """A node in the repository knowledge graph."""

    id: str
    repository: str
    kind: str
    name: str
    file_path: str
    start_line: int
    end_line: int


@dataclass
class CodeRelation:
    """A relationship between two repository graph nodes."""

    id: str
    relation: str