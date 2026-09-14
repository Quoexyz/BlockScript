"""参数化组件：写一次，多处实例化，改模板全部生效。

设计要点
--------
1. **世界仍以体素为真相** —— 组件只是「展开器」，渲染 / 查询 / lint 一行都不用改。
2. **实例记的是 patch 不是包围盒** —— 精确撤销，相邻实例重叠也不会互相破坏。
3. **覆盖记实例内局部坐标** —— 模板改动后实例位置/尺寸变了，覆盖依然跟着走。
4. **重放显式触发** —— 一个建筑几百个实例时，自动重放每次微调都会全量重算。
5. **组件可嵌套** —— 组件内部的 ``t.place("子组件", ...)`` 会被记成父子关系，
   父组件重放时子孙实例级联重建。``t`` 可以是 World 或 Frame。
6. **展开失败回滚** —— 组件写到一半抛异常，不会在世界里留半截残骸。

    def pier(t, h=8, mat="stone_bricks"):
        t.pillar((0, 0, 0), h, mat)

    def bay(t, w=6, d=6, h=8, pier="stone_bricks"):
        t.fill(box((0, 0, 0), (w - 1, 0, d - 1)), pier)
        t.place("pier", at=(0, 1, 0), h=h - 1)          # 组件嵌套：复用子组件
        t.place("pier", at=(w - 1, 1, d - 1), h=h - 1)

    w.define("pier", pier)
    w.define("bay", bay)
    w.grid("bays", origin=(0, 64, 0), axis="z", spacing=6, n=8)
    for i in range(8):
        w.place("bay", at=w.grid_at("bays", i))

    w.patch(w.instance("bay", 3), (2, 5, 0), "gold_block")   # 只改第 4 个
    w.unlink(w.instance("bay", 5))                            # 第 6 个断开同步
    w.replay("bay")                                           # 其余按新模板（含子组件）重放
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set

from .block import AIR, Block, make
from .vec import V, Box, box, rot_y

Patch = List[tuple]


def _bbox(cells) -> Optional[Box]:
    if not cells:
        return None
    xs = [p.x for p in cells]
    ys = [p.y for p in cells]
    zs = [p.z for p in cells]
    return box(V(min(xs), min(ys), min(zs)), V(max(xs), max(ys), max(zs)))


def _descendants(inst: "Instance") -> List["Instance"]:
    """递归收集所有后代实例。"""
    out: List["Instance"] = []
    for c in inst.children:
        out.append(c)
        out.extend(_descendants(c))
    return out


def _has_ancestor_in(inst: "Instance", ids: Set[int]) -> bool:
    """该实例是否存在祖先也落在 ids 里（决定它会不会被祖先的重展开接管）。"""
    p = inst.parent
    while p is not None:
        if id(p) in ids:
            return True
        p = p.parent
    return False


@dataclass
class Instance:
    """一个组件实例。可以是另一个实例的子实例（组件嵌套）。"""

    name: str
    at: V
    yaw: int
    params: dict
    patch: Patch = field(default_factory=list)          # 展开产生的完整 patch
    cells: Set[V] = field(default_factory=set)          # 本次写入的非空格
    box: Optional[Box] = None
    linked: bool = True                                  # False = 已断开同步
    overrides: Dict[V, Block] = field(default_factory=dict)   # 局部坐标 -> 方块
    parent: Optional["Instance"] = None
    children: List["Instance"] = field(default_factory=list)

    # ---------------------------------------------------------- 坐标
    def to_world(self, p) -> V:
        return rot_y(V(int(p[0]), int(p[1]), int(p[2])), self.yaw) + self.at

    def to_local(self, p) -> V:
        return rot_y(V(int(p[0]), int(p[1]), int(p[2])) - self.at, -self.yaw)

    @property
    def depth(self) -> int:
        """嵌套深度，顶层实例为 0。"""
        d, p = 0, self.parent
        while p is not None:
            d, p = d + 1, p.parent
        return d

    def __repr__(self) -> str:  # noqa: D105
        flag = "" if self.linked else ", unlinked"
        ov = f", {len(self.overrides)} overrides" if self.overrides else ""
        ch = f", {len(self.children)} children" if self.children else ""
        return (f"Instance({self.name} at={self.at} yaw={self.yaw}"
                f"{flag}{ov}{ch})")


class ComponentMixin:
    """挂在 World 上的组件能力（Frame 通过转发 world.place 使用）。"""

    def _init_components(self) -> None:
        self._components: Dict[str, Callable] = {}
        self.instances: List[Instance] = []
        self._place_stack: List[Instance] = []

    # ---------------------------------------------------------- 定义
    def define(self, name: str, fn: Callable, replay: bool = False) -> None:
        """注册/替换模板。默认不自动重放（显式调用 replay）。"""
        if not callable(fn):
            raise TypeError(f"模板必须是可调用对象: {name}")
        self._components[name] = fn
        if replay:
            self.replay(name)

    def template(self, name: str) -> Callable:
        if name not in self._components:
            raise KeyError(f"未定义的组件: {name}（可用: {sorted(self._components)}）")
        return self._components[name]

    # ---------------------------------------------------------- 放置
    def place(self, name: str, at=(0, 0, 0), yaw: int = 0, **params) -> Instance:
        """展开一个实例并记录。返回 Instance 供后续 unlink / patch。

        展开过程中若抛异常，本次写入的方块与创建的实例（含后代）会全部回滚。
        """
        fn = self.template(name)
        at = V(int(at[0]), int(at[1]), int(at[2]))
        yaw = int(yaw)
        parent = self._place_stack[-1] if self._place_stack else None
        n0 = len(self._undo)
        i0 = len(self.instances)

        inst = Instance(name=name, at=at, yaw=yaw, params=params, parent=parent)
        self.instances.append(inst)
        self._place_stack.append(inst)
        try:
            fn(self.frame(at=at, yaw=yaw), **params)
        except BaseException:
            self._apply([c for sub in self._undo[n0:] for c in sub], reverse=True)
            del self._undo[n0:]
            del self.instances[i0:]              # 自己 + 全部后代
            raise
        finally:
            self._place_stack.pop()

        patch = [c for sub in self._undo[n0:] for c in sub]
        inst.patch = patch
        inst.cells = {p for p, old, new in patch if not new.is_air}
        inst.box = _bbox(inst.cells)
        inst.children = [x for x in self.instances[i0 + 1:] if x.parent is inst]
        return inst

    # ---------------------------------------------------------- 查询
    def instances_of(self, name: str) -> List[Instance]:
        return [i for i in self.instances if i.name == name]

    def instance(self, name: str, index: int = 0) -> Instance:
        lst = self.instances_of(name)
        if not lst:
            raise KeyError(f"没有 {name} 的实例")
        if not -len(lst) <= index < len(lst):
            raise IndexError(f"{name} 实例索引越界: {index}（共 {len(lst)} 个）")
        return lst[index]

    # ---------------------------------------------------------- 重放 / 断开 / 覆盖
    def replay(self, name: Optional[str] = None) -> int:
        """按当前模板重新展开。逆序精确撤销、正序重新展开，重叠实例也安全。

        name=None 表示重放所有仍链接的实例。
        被重放实例的**子孙实例会级联清理并重建**；某个后代若其祖先也在待重放集合里，
        就交给祖先的重展开接管，不重复展开。
        实例对象本身保持同一个引用，其 ``overrides`` 在重放后继续有效。
        """
        cands = [i for i in self.instances
                 if i.linked and (name is None or i.name == name)]
        if not cands:
            return 0
        ids = {id(i) for i in cands}
        targets = [i for i in cands if not _has_ancestor_in(i, ids)]

        # 后代实例会被重建，先按 (名字, 世界位置) 记下它们的局部覆盖以便继承
        legacy: Dict[tuple, List[dict]] = {}
        for inst in targets:
            for d in _descendants(inst):
                legacy.setdefault((d.name, tuple(d.at)), []).append(dict(d.overrides))

        for inst in reversed(targets):                 # 后写的先撤
            self._apply(inst.patch, reverse=True)

        # 清掉各目标的后代（它们会在重展开时重建）；目标实例本身留在原位不动
        for inst in targets:
            sub = _descendants(inst)
            if sub:
                dead = {id(x) for x in sub}
                self.instances = [x for x in self.instances if id(x) not in dead]
            inst.children = []

        for inst in targets:                           # 原引用原地重展开
            fn = self.template(inst.name)
            n0 = len(self._undo)
            i0 = len(self.instances)
            self._place_stack.append(inst)
            try:
                fn(self.frame(at=inst.at, yaw=inst.yaw), **inst.params)
            finally:
                self._place_stack.pop()
            for lp, blk in inst.overrides.items():     # 目标自身的覆盖保持有效
                self.set(inst.to_world(lp), blk)
            inst.children = [x for x in self.instances[i0:] if x.parent is inst]

            # 重建出来的后代：按 (name, at) 继承覆盖；这些写入依旧落在 n0 之后，
            # 因此会一并并入父实例的 patch，父的精确撤销依然完整。
            for d in self.instances[i0:]:
                pool = legacy.get((d.name, tuple(d.at)))
                if not pool:
                    continue
                ov = pool.pop(0)
                if not ov:
                    continue
                d.overrides = ov
                n1 = len(self._undo)
                for lp, blk in ov.items():
                    self.set(d.to_world(lp), blk)
                extra = [c for sub in self._undo[n1:] for c in sub]
                d.patch = list(d.patch) + extra
                d.cells |= {p for p, old, new in extra if not new.is_air}
                d.box = _bbox(d.cells)

            inst.patch = [c for sub in self._undo[n0:] for c in sub]
            inst.cells = {p for p, old, new in inst.patch if not new.is_air}
            inst.box = _bbox(inst.cells)
        return len(targets)

    def unlink(self, inst: Instance) -> Instance:
        """断开同步：它自己的模板改动不再跟随，后续 replay 不重放它。

        注意：若它的**父组件**被重放，它仍会随父的 patch 一起重建 ——
        因为它的体素归属父的展开过程。
        """
        inst.linked = False
        return inst

    def relink(self, inst: Instance) -> Instance:
        """恢复同步（下一次 replay 起生效）。"""
        inst.linked = True
        return inst

    def patch(self, inst: Instance, local, block, **state) -> Block:
        """局部覆盖：只改这一个实例，且 replay 之后仍然保留。

        local 是**实例内局部坐标** —— 模板改动导致实例移动或变形后，
        覆盖依然跟着实例走；记世界坐标则会指错地方。
        """
        lp = V(int(local[0]), int(local[1]), int(local[2]))
        b = block if isinstance(block, Block) else make(block, **state)
        inst.overrides[lp] = b
        self.set(inst.to_world(lp), b)
        return b

    def unpatch(self, inst: Instance, local) -> bool:
        """移除一处局部覆盖（恢复模板内容，需 replay 才生效）。"""
        lp = V(int(local[0]), int(local[1]), int(local[2]))
        return inst.overrides.pop(lp, None) is not None
