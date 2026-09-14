"""分步构建：让模型一轮只处理一个阶段。

脚本越长越难维护，而模型的上下文更长不了。把构建拆成命名阶段之后：

    w.stage("podium", build_podium)
    w.stage("nave", build_nave)
    w.stage("towers", build_towers)

    w.rerun("nave")            # 改了中殿做法：重跑中殿及其之后的阶段
    w.revert_to("nave")        # 撤销中殿及其之后
    w.render.view(center=w.stage_box("nave"))     # 只看这一步的范围

配合已有的 save / load，模型可以一轮只做一步：

    # 第 1 轮
    w = World(); w.stage("podium", build_podium); w.save("church.json")
    # 第 2 轮
    w = World.load("church.json"); w.stage("nave", build_nave); w.save("church.json")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .vec import V, Box, box

Patch = List[tuple]


@dataclass
class Stage:
    """一个构建阶段。"""

    name: str
    fn: Optional[Callable]           # 用函数创建时可重跑；上下文管理器方式为 None
    patch: Patch
    box: Optional[Box] = None
    instances: List = field(default_factory=list)   # 本阶段创建的组件实例

    def __repr__(self) -> str:  # noqa: D105
        b = f" box={self.box}" if self.box else ""
        return f"Stage({self.name}, {len(self.patch)} cells{b})"


class _StageCtx:
    """``with w.stage("nave"):`` 的上下文对象。"""

    def __init__(self, world, name: str) -> None:
        self.w = world
        self.name = name
        self.n0 = 0
        self.i0 = 0

    def __enter__(self):
        self.n0 = len(self.w._undo)
        self.i0 = len(self.w.instances)
        return self.w

    def __exit__(self, *exc) -> None:
        patch = [c for sub in self.w._undo[self.n0:] for c in sub]
        cells = {p for p, old, new in patch if not new.is_air}
        self.w.stages.append(Stage(
            name=self.name, fn=None, patch=patch, box=_bbox(cells),
            instances=self.w.instances[self.i0:]))
        return None


class StageMixin:
    def _init_stages(self) -> None:
        self.stages: List[Stage] = []

    # ------------------------------------------------------------ 记录
    def stage(self, name: str, fn: Optional[Callable] = None):
        """记为一个构建阶段。

        两种写法等价::

            w.stage("nave", build_nave)
            with w.stage("nave"):
                build_nave(w)

        传 fn 的版本可 rerun（函数被记住）；with 版本不行。
        """
        if fn is None:
            return _StageCtx(self, name)
        with _StageCtx(self, name):
            fn(self)
        st = self.stages[-1]
        st.fn = fn
        return st

    # ------------------------------------------------------------ 查询
    def _stage_index(self, name: str) -> int:
        for i, s in enumerate(self.stages):
            if s.name == name:
                return i
        raise KeyError(f"没有名为 {name!r} 的阶段（可用: "
                       f"{[s.name for s in self.stages]}）")

    def stage_box(self, name: str) -> Optional[Box]:
        return self.stages[self._stage_index(name)].box

    # ------------------------------------------------------------ 回退 / 重跑
    def revert_to(self, name: str) -> List[str]:
        """撤销该阶段及其之后的所有阶段（逆序精确撤销）。

        连同这些阶段创建的组件实例一起摘掉，否则 rerun 之后
        ``w.instances`` 里会残留已失效的旧实例。
        """
        i = self._stage_index(name)
        removed = []
        for s in reversed(self.stages[i:]):
            self._apply(s.patch, reverse=True)
            removed.append(s.name)
        dead = {id(x) for s in self.stages[i:] for x in s.instances}
        if dead:
            self.instances = [x for x in self.instances if id(x) not in dead]
        self.stages = self.stages[:i]
        return removed

    def rerun(self, name: str) -> List[str]:
        """重跑该阶段及其之后的所有阶段。要求当初是用函数创建的。"""
        i = self._stage_index(name)
        pending = self.stages[i:]
        for s in pending:
            if s.fn is None:
                raise ValueError(
                    f"阶段 {s.name!r} 是用 with 块创建的，没有可重跑的函数；"
                    f"请改用 w.stage_fn(name, fn)")
        self.revert_to(name)
        for s in pending:
            self.stage(s.name, s.fn)
        return [s.name for s in pending]


def _bbox(cells):
    if not cells:
        return None
    xs = [p.x for p in cells]
    ys = [p.y for p in cells]
    zs = [p.z for p in cells]
    return box(V(min(xs), min(ys), min(zs)), V(max(xs), max(ys), max(zs)))
