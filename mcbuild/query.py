"""查询器。"""

from __future__ import annotations

from typing import Callable, Dict, List, Union

from .block import AIR, Block, make
from .vec import V, Box, box

Pred = Union[None, str, Block, Callable[[Block], bool]]


def _as_pred(pred: Pred) -> Callable[[Block], bool]:
    if pred is None:
        return lambda b: not b.is_air
    if isinstance(pred, Block):
        return lambda b: b == pred
    if isinstance(pred, str):
        key = pred.lower()

        def f(b: Block) -> bool:
            return key in b.id.lower() or key in b.name.lower()
        return f
    if callable(pred):
        return pred
    raise TypeError(f"无法解释的谓词: {pred!r}")


class Query:
    def __init__(self, world) -> None:
        self.w = world

    def at(self, pos) -> Block:
        return self.w.get(pos)

    def empty(self, pos) -> bool:
        return self.w.get(pos).is_air

    def count(self, block: Pred = None) -> Union[int, Dict[str, int]]:
        """不传参返回占用总数；传谓词返回该谓词命中数；传 list 返回分类型统计。"""
        if block is None:
            return len(self.w.cells)
        pred = _as_pred(block)
        return sum(1 for b in self.w.cells.values() if pred(b))

    def histogram(self, top: int = 8) -> List[tuple]:
        d: Dict[str, int] = {}
        for b in self.w.cells.values():
            d[b.key()] = d.get(b.key(), 0) + 1
        return sorted(d.items(), key=lambda kv: -kv[1])[:top]

    def bounds(self):
        return self.w.bounds()

    def where(self, pred: Pred) -> List[V]:
        f = _as_pred(pred)
        return sorted(p for p, b in self.w.cells.items() if f(b))

    def nearest(self, origin, pred: Pred = None):
        """离 origin 最近的匹配格。origin 可传锚点名。"""
        if isinstance(origin, str):
            origin = self.w.marks.anchor(origin)
        o = V(int(origin[0]), int(origin[1]), int(origin[2]))
        f = _as_pred(pred)
        best, bd = None, None
        for p, b in self.w.cells.items():
            if not f(b):
                continue
            d = (p.x - o.x) ** 2 + (p.y - o.y) ** 2 + (p.z - o.z) ** 2
            if bd is None or d < bd:
                best, bd = p, d
        return best

    def neighbors(self, pos) -> Dict[str, Block]:
        p = V(int(pos[0]), int(pos[1]), int(pos[2]))
        return {
            "north": self.w.get(p + V(0, 0, -1)),
            "south": self.w.get(p + V(0, 0, 1)),
            "east": self.w.get(p + V(1, 0, 0)),
            "west": self.w.get(p + V(-1, 0, 0)),
            "up": self.w.get(p + V(0, 1, 0)),
            "down": self.w.get(p + V(0, -1, 0)),
        }

    def raycast(self, origin, direction, max_dist: float = 64.0):
        """射线检测，返回第一个命中 (V, Block, 距离) 或 None。"""
        import math
        o = V(int(origin[0]), int(origin[1]), int(origin[2]))
        d = (float(direction[0]), float(direction[1]), float(direction[2]))
        n = math.sqrt(sum(c * c for c in d))
        if n == 0:
            return None
        ux, uy, uz = d[0] / n, d[1] / n, d[2] / n
        step = 0.2
        t = 0.0
        last = None
        while t <= max_dist:
            p = V(int(round(o.x + ux * t)), int(round(o.y + uy * t)), int(round(o.z + uz * t)))
            if last is None:
                last = p
            elif p != last:
                b = self.w.get(p)
                if not b.is_air:
                    return (p, b, t)
                last = p
            t += step
        return None

    def volume(self) -> int:
        b = self.w.bounds()
        return b.volume() if b else 0

    def density(self) -> float:
        b = self.w.bounds()
        if not b or b.volume() == 0:
            return 0.0
        return len(self.w.cells) / b.volume()

    def support_report(self):
        """会掉落 / 悬空的方块清单，复用 lint 的 W1 规则。"""
        from .lint import lint
        return [(i.pos, i.block, i.msg) for i in lint(self.w) if i.code == "W1"]
