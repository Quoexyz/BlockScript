"""干跑预览：先看后果，再决定要不要提交。

借鉴 Nucleation 的 ``inspect_transform`` / ``apply_transform`` 三段式：
所有破坏性操作都可以先在**不改动世界**的前提下跑一遍，拿到影响报告，
确认后再原子提交。

    pv = w.preview(w.replace, box((0, 0, 0), (63, 100, 63)), src=None, dst="air")
    print(pv.report())
    # 将改动 12000 格：新增 0 · 移除 12000 · 替换 0
    # 影响范围 (0,0,0)..(63,100,63)
    # 涉及 3 个组件实例：bay#0 bay#1 bay#2
    if pv.removed > 2000:
        print("太大了，换个范围")
    else:
        pv.commit()

为什么值得：模型"改完才看见后果"，出错只能靠 undo 逐层退；而 preview 让
后果**在动作之前**到达，大范围误操作可以直接不发生。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .block import AIR, Block
from .vec import V, Box, box

Patch = List[tuple]


def _label(fn, args) -> str:
    name = getattr(fn, "__name__", repr(fn))
    shown = ", ".join(repr(a)[:40] for a in args[:3])
    return f"{name}({shown})"


@dataclass
class Preview:
    """一次干跑的结果。此时世界仍然未被改动。"""

    world: object
    patch: Patch
    label: str = ""
    _fn: object = None
    _args: tuple = ()
    _kwargs: dict = field(default_factory=dict)
    _done: bool = field(default=False, repr=False)

    # ------------------------------------------------------------ 统计
    @property
    def changed(self) -> int:
        return len(self.patch)

    @property
    def added(self) -> int:
        return sum(1 for _, old, new in self.patch if old.is_air and not new.is_air)

    @property
    def removed(self) -> int:
        return sum(1 for _, old, new in self.patch if not old.is_air and new.is_air)

    @property
    def replaced(self) -> int:
        return sum(1 for _, old, new in self.patch
                   if not old.is_air and not new.is_air)

    @property
    def box(self) -> Optional[Box]:
        if not self.patch:
            return None
        xs = [p.x for p, _, _ in self.patch]
        ys = [p.y for p, _, _ in self.patch]
        zs = [p.z for p, _, _ in self.patch]
        return box(V(min(xs), min(ys), min(zs)), V(max(xs), max(ys), max(zs)))

    @property
    def empty(self) -> bool:
        """空操作：改了等于没改。"""
        return not self.patch or all(old == new for _, old, new in self.patch)

    def instances_hit(self) -> List:
        """哪些组件实例的展开范围与本次改动相交。"""
        b = self.box
        if b is None:
            return []
        out = []
        for inst in getattr(self.world, "instances", []):
            ib = inst.box
            if ib is None:
                continue
            if (ib.lo.x <= b.hi.x and b.lo.x <= ib.hi.x
                    and ib.lo.y <= b.hi.y and b.lo.y <= ib.hi.y
                    and ib.lo.z <= b.hi.z and b.lo.z <= ib.hi.z):
                out.append(inst)
        return out

    # ------------------------------------------------------------ 报告
    def report(self, limit: int = 5) -> str:
        if self.empty:
            return f"preview {self.label}：空操作，无改动"
        lines = [f"preview {self.label}"]
        lines.append(f"  将改动 {self.changed} 格："
                     f"新增 {self.added} · 移除 {self.removed} · 替换 {self.replaced}")
        b = self.box
        lines.append(f"  影响范围 {b.lo}..{b.hi}  尺寸 {b.size}")
        hits = self.instances_hit()
        if hits:
            names = []
            for i in hits:
                n = f"{i.name}#{self.world.instances.index(i)}"
                if n not in names:
                    names.append(n)
                if len(names) >= limit:
                    break
            more = "" if len(hits) <= limit else f" …共 {len(hits)} 个"
            lines.append(f"  涉及组件实例：{' '.join(names)}{more}")
        return "\n".join(lines)

    # ------------------------------------------------------------ 提交 / 丢弃
    def commit(self) -> int:
        """原子提交，返回将改动的格数。

        实现是**重放**那个操作，而不是回灌 patch —— 因为 patch 里没有
        组件实例记录，回灌会让 ``place`` 出来的实例丢失。框架是确定性的，
        重放同一操作得到同一结果（材质混合按位置哈希，也不依赖调用顺序）。
        """
        if self._done:
            raise RuntimeError("这个 preview 已经用过（commit 或 discard 过）")
        self._done = True
        if self._fn is not None:
            self._fn(*self._args, **self._kwargs)
        elif self.patch:                       # 无 fn 时的回退路径
            self.world._apply(self.patch, reverse=False)
            self.world._undo.append(list(self.patch))
            self.world._redo.clear()
        return self.changed

    def discard(self) -> None:
        """丢弃。因为 preview 期间世界没被改动，这里什么都不用做。"""
        if self._done:
            raise RuntimeError("这个 preview 已经用过（commit 或 discard 过）")
        self._done = True

    def __repr__(self) -> str:  # noqa: D105
        state = "已提交" if self._done else "待定"
        return f"Preview({self.label}, {self.changed} 格, {state})"


class PreviewMixin:
    """挂在 World 上的干跑能力。"""

    def preview(self, fn, *args, **kwargs) -> Preview:
        """干跑一次操作：执行、收集改动、**立即撤销**，返回影响报告。

        世界、undo 栈、组件实例列表都会回到调用前的状态。
        确认后果后调 ``pv.commit()`` 才真正落盘。

        注意：因为中间撤销过一次，preview 不适合叠加多个操作——
        要比较多个方案就分别 preview，或者 commit 之后再做下一个。
        """
        n0 = len(self._undo)
        i0 = len(self.instances)
        try:
            fn(*args, **kwargs)
        except BaseException:
            patch = [c for sub in self._undo[n0:] for c in sub]
            self._apply(patch, reverse=True)
            del self._undo[n0:]
            del self.instances[i0:]
            raise
        patch = [c for sub in self._undo[n0:] for c in sub]
        self._apply(patch, reverse=True)
        del self._undo[n0:]
        del self.instances[i0:]          # preview 不留实例，commit 重放时会重建
        return Preview(self, patch, _label(fn, args),
                       _fn=fn, _args=args, _kwargs=kwargs)
