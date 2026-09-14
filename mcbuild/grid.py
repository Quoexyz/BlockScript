"""轴网：让模型用 bay(3) 而不是 (0, 64, -6) 寻址。

大建筑里绝对坐标是模型最大的负担。轴网把「第 N 个开间 / 第 N 根柱」
变成一等公民，写出来的代码才不会堆成一串魔数。

    w.grid("bays", origin=(0, 64, -24), axis="z", spacing=6, n=8)
    w.grid_at("bays", 3)            # → V(0, 64, -6)   第 4 个开间起点
    w.grid_cell("bays", 3)          # → Box(...)       第 4 个开间占的范围
    w.place("bay", at=w.grid_at("bays", 3))
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from .vec import V, Box, box

_AXIS_VEC = {"x": V(1, 0, 0), "y": V(0, 1, 0), "z": V(0, 0, 1)}

AxisSpec = Tuple[str, int, int]      # (轴名, 间距, 数量)


@dataclass
class Grid:
    """一维或二维轴网。

    axes: ``[("z", 6, 8)]``              一维：沿 z，间距 6，共 8 格
          ``[("x", 6, 5), ("z", 6, 8)]`` 二维柱网
    """

    name: str
    origin: V
    axes: List[AxisSpec]

    def __post_init__(self) -> None:
        if not 1 <= len(self.axes) <= 2:
            raise ValueError("轴网只支持 1 维或 2 维")
        for ax, sp, n in self.axes:
            if ax not in _AXIS_VEC:
                raise ValueError(f"未知轴: {ax!r}（可用 x/y/z）")
            if sp < 1 or n < 1:
                raise ValueError(f"间距与数量必须 >= 1，收到 {ax} spacing={sp} n={n}")

    # ------------------------------------------------------------ 基本信息
    @property
    def ndim(self) -> int:
        return len(self.axes)

    def count(self, k: int = 0) -> int:
        return self.axes[k][2]

    def _check(self, idx) -> List[Tuple[V, int, int]]:
        """把索引序列规整成 [(方向向量, 索引, 间距), ...]。"""
        if len(idx) != self.ndim:
            raise ValueError(
                f"{self.name} 是 {self.ndim} 维轴网，需要 {self.ndim} 个索引，收到 {len(idx)}")
        out = []
        for k, i in enumerate(idx):
            ax, sp, n = self.axes[k]
            if not 0 <= i < n:
                raise IndexError(f"{self.name} 第 {k} 轴索引越界: {i}（0..{n - 1}）")
            out.append((_AXIS_VEC[ax], i, sp))
        return out

    # ------------------------------------------------------------ 取位
    def at(self, *idx: int) -> V:
        """第 i（, j）个格点的世界坐标。"""
        p = self.origin
        for v, i, sp in self._check(idx):
            p = p + v * (i * sp)
        return p

    def cell(self, *idx: int, size: int = 0) -> Box:
        """第 i 格占据的范围。size 默认取该轴间距。"""
        lo = self.origin
        hi = self.origin
        for v, i, sp in self._check(idx):
            ext = (size or sp) - 1
            lo = lo + v * (i * sp)
            hi = hi + v * (i * sp + ext)
        return box(lo, hi)

    def _span_specs(self, idx):
        """把 span/cover 的参数规整成每轴 (i0, i1)。

        一维：``span(2, 5)`` 与 ``span((2, 5))`` 等价；
        二维：``span((0, 2), (3, 5))``，单给 int 表示该轴单格点。
        """
        if len(idx) == 1 and isinstance(idx[0], (tuple, list)):
            idx = tuple(idx[0])
        if self.ndim == 1 and len(idx) == 2 \
                and all(isinstance(i, int) for i in idx):
            return [(idx[0], idx[1])]
        if len(idx) != self.ndim:
            raise ValueError(
                f"{self.name} 是 {self.ndim} 维轴网，span 需要 {self.ndim} 个"
                f"（或一维时写 i0, i1 两个 int），收到 {len(idx)} 个")
        specs = []
        for s in idx:
            specs.append((s, s) if isinstance(s, int) else (int(s[0]), int(s[1])))
        return specs

    def _check_range(self, k: int, i0: int, i1: int) -> None:
        _, sp, n = self.axes[k]
        for i in (i0, i1):
            if not 0 <= i < n:
                raise IndexError(f"{self.name} 第 {k} 轴索引越界: {i}（0..{n - 1}）")
        if i0 > i1:
            raise IndexError(f"{self.name} 第 {k} 轴范围颠倒: {i0} > {i1}")

    def span(self, *idx) -> Box:
        """格点到格点的包围盒。

        一维：``g.span(2, 5)`` 或 ``g.span((2, 5))``
        二维：``g.span((0, 2), (3, 5))``
        """
        lo = hi = self.origin
        for k, (i0, i1) in enumerate(self._span_specs(idx)):
            self._check_range(k, i0, i1)
            v = _AXIS_VEC[self.axes[k][0]]
            lo = lo + v * (i0 * self.axes[k][1])
            hi = hi + v * (i1 * self.axes[k][1])
        return box(lo, hi)

    def cover(self, *idx) -> Box:
        """覆盖第 i0..i1 格的全部范围（末格按整格宽度计入）。"""
        lo = hi = self.origin
        for k, (i0, i1) in enumerate(self._span_specs(idx)):
            self._check_range(k, i0, i1)
            ax, sp, n = self.axes[k]
            v = _AXIS_VEC[ax]
            lo = lo + v * (i0 * sp)
            hi = hi + v * (i1 * sp + sp - 1)
        return box(lo, hi)

    def __repr__(self) -> str:  # noqa: D105
        desc = ", ".join(f"{ax}+{sp}×{n}" for ax, sp, n in self.axes)
        return f"Grid({self.name}, origin={self.origin}, [{desc}])"
