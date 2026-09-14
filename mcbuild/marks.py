"""命名锚点层。

标记独立于体素：不占方块、不参与导出（除非显式要求），
是模型的空间记忆外挂。
"""

from __future__ import annotations

from typing import Dict

from .vec import V, box, Box


class MarkLayer:
    def __init__(self) -> None:
        self.points: Dict[str, V] = {}
        self.boxes: Dict[str, Box] = {}

    def set_point(self, name: str, pos) -> V:
        self.points[name] = V(int(pos[0]), int(pos[1]), int(pos[2]))
        return self.points[name]

    def set_box(self, name: str, bx) -> Box:
        b = box(bx)
        self.boxes[name] = b
        return b

    def get(self, name: str):
        if name in self.points:
            return self.points[name]
        if name in self.boxes:
            return self.boxes[name]
        raise KeyError(f"未定义的锚点: {name!r}")

    def anchor(self, name: str) -> V:
        if name not in self.points:
            raise KeyError(f"未定义的点锚点: {name!r}")
        return self.points[name]

    def remove(self, name: str) -> None:
        self.points.pop(name, None)
        self.boxes.pop(name, None)

    def as_dict(self) -> dict:
        return {
            "points": {k: list(v) for k, v in self.points.items()},
            "boxes": {k: [list(b.lo), list(b.hi)] for k, b in self.boxes.items()},
        }

    def load(self, data: dict) -> None:
        self.points = {k: V(*v) for k, v in data.get("points", {}).items()}
        self.boxes = {k: box(V(*a), V(*b)) for k, (a, b) in data.get("boxes", {}).items()}

    def __repr__(self) -> str:  # noqa: D105
        return f"MarkLayer(points={self.points}, boxes={list(self.boxes)})"
