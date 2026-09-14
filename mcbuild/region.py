"""命名区域：把建筑群拆成可以独立操作的块。

`stage` 管的是**时间**（构建顺序），`region` 管的是**空间**（命名分区）。
稀疏空岛、建筑群这类场景里，每个岛/每栋楼都需要能独立搬移、旋转、导出。

    with w.region("tower_a") as a:
        build_tower(w)

    with w.region("tower_b") as b:
        build_smaller_tower(w)

    a.box                      # 这一块的世界范围
    a.translate((30, 0, 0))    # 搬走
    b.mirror(axis="x")         # 镜像
    a.copy_to((0, 0, 60), name="tower_c")   # 复制一份
    a.export_schem("out/tower_a.schem")     # 单独导出

区域记的是**精确格子集合**（不是包围盒），所以就算形状不规则、
或者与别的区域交错，搬移和导出都不会多带或漏掉方块。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set

from .block import AIR, Block, mirror_block, rotate_block
from .vec import V, Box, box, rot_y


def _bbox(cells: Set[V]) -> Optional[Box]:
    if not cells:
        return None
    xs = [p.x for p in cells]
    ys = [p.y for p in cells]
    zs = [p.z for p in cells]
    return box(V(min(xs), min(ys), min(zs)), V(max(xs), max(ys), max(zs)))


def _mirror_pos(p: V, axis: str, pivot: float) -> V:
    if axis == "x":
        return p.replace(x=int(round(2 * pivot - p.x)))
    if axis == "z":
        return p.replace(z=int(round(2 * pivot - p.z)))
    return p.replace(y=int(round(2 * pivot - p.y)))


class Region:
    """一块有名字的建筑。可以嵌套（岛上的楼阁是岛的子区域）。"""

    def __init__(self, name: str, world, parent: "Region | None" = None) -> None:
        self.name = name
        self.world = world
        self.parent = parent
        self.cells: Set[V] = set()
        self.box: Optional[Box] = None
        self.instances: List = []

    # ------------------------------------------------------------ 查询
    def __len__(self) -> int:
        return len(self.cells)

    def __contains__(self, pos) -> bool:
        return V(int(pos[0]), int(pos[1]), int(pos[2])) in self.cells

    def count(self) -> int:
        return len(self.cells)

    # ------------------------------------------------------------ 亲缘
    def _ancestors(self):
        """沿父链向上。带环检测 —— 误用（A 里开 B、B 里又开 A）不该挂死。"""
        seen = set()
        p = self.parent
        while p is not None and id(p) not in seen:
            seen.add(id(p))
            yield p
            p = p.parent

    def _is_ancestor_of(self, other: "Region") -> bool:
        return any(a is self for a in other._ancestors())

    def depth(self) -> int:
        return sum(1 for _ in self._ancestors())

    def children(self) -> List["Region"]:
        return [r for r in self.world.regions.values() if self._is_ancestor_of(r)]

    def _kin(self, other: "Region") -> bool:
        """是否有亲缘（祖先或后代）—— 亲缘之间不互相扣格子。"""
        return self._is_ancestor_of(other) or other._is_ancestor_of(self)

    def owned(self) -> Set[V]:
        """本区域**独占**的格子。

        两条规则：

        * **后定义的区域拥有重叠部分** —— 那格的内容确实是它写的。
          岛先铺了地面、塔后立在上面并自己铺了地基，地基就归塔，
          搬走塔会连带把地基搬走（原地留个洞，这是拆除的正常结果）。
        * **祖先 / 后代互相豁免** —— 岛上的楼阁可以独立搬移，
          哪怕它的地板和岛面是同一批格子；搬岛时楼阁也跟着走。

        变换与导出都用这个集合，`cells` 保留"我写过什么"的原始语义。
        """
        taken: Set[V] = set()
        mine = False
        for n, r in self.world.regions.items():
            if n == self.name:
                mine = True
                continue                    # 后面的区域才可能扣我
            if not mine or self._kin(r):
                continue                    # 先定义的、以及父/子，都不扣
            taken |= r.cells
        return self.cells - taken if taken else set(self.cells)

    def blocks(self) -> Dict[V, Block]:
        """区域内当前实际存在的方块（独占部分）。"""
        return {p: self.world.get(p) for p in sorted(self.owned())
                if not self.world.get(p).is_air}

    def _op_cells(self) -> Set[V]:
        """变换 / 导出实际作用的格子 = 自己的独占 + 各后代的独占。

        搬走一座岛要连岛上的楼阁一起搬走，所以操作集合取并集；
        而楼阁单独搬时只用它自己的那部分。
        """
        out = set(self.owned())
        for r in self.children():
            out |= r.owned()
        return out

    def _sync_descendants(self, mapping: Dict[V, V]) -> None:
        """本区域变换后，同步后代区域的记录（否则它们的 cells 会指向旧位置）。"""
        for r in self.children():
            kept = {p for p in r.cells if p not in mapping}
            r.cells = kept | {mapping[p] for p in r.cells if p in mapping}
            r.box = _bbox(r.cells)

    def _sync_ancestors(self, mapping: Dict[V, V]) -> None:
        """子区域变换后，同步祖先区域的记录位置。"""
        for a in self._ancestors():
            kept = {p for p in a.cells if p not in mapping}
            a.cells = kept | {mapping[p] for p in a.cells if p in mapping}
            a.box = _bbox(a.cells)

    def histogram(self, top: int = 8) -> List[tuple]:
        d: Dict[str, int] = {}
        for b in self.blocks().values():
            d[b.key()] = d.get(b.key(), 0) + 1
        return sorted(d.items(), key=lambda kv: -kv[1])[:top]

    # ------------------------------------------------------------ 变换
    def _guard(self) -> None:
        """区域内涉及组件实例时先断开同步 —— 位置变了之后 patch 记录不再有效。"""
        if not self.instances:
            return
        for inst in self.instances:
            if inst.linked:
                self.world.unlink(inst)

    def translate(self, delta) -> int:
        """搬移整个区域。返回搬移的格数。"""
        d = V(int(delta[0]), int(delta[1]), int(delta[2]))
        if d == V(0, 0, 0):
            return 0
        self._guard()
        snap = [(p, self.world.get(p)) for p in sorted(self._op_cells())]
        with self.world._tx("region.translate", region=self.name, delta=repr(d)):
            for p, _ in snap:
                self.world._write(p, AIR)
            for p, b in snap:
                self.world._write(p + d, b)
        mapping = {p: p + d for p, _ in snap}
        self.cells = set(mapping.values())
        self.box = _bbox(self.cells)
        self._sync_descendants(mapping)
        self._sync_ancestors(mapping)
        return len(snap)

    def mirror(self, axis: str = "x", pivot=None) -> int:
        """镜像整个区域（含朝向翻转）。pivot 默认取区域中线。"""
        self._guard()
        b = self.box
        if b is None:
            return 0
        if pivot is None:
            pivot = ((b.lo.x + b.hi.x) / 2 if axis == "x"
                     else (b.lo.z + b.hi.z) / 2 if axis == "z"
                     else (b.lo.y + b.hi.y) / 2)
        snap = [(p, self.world.get(p)) for p in sorted(self._op_cells())]
        moved = {p: _mirror_pos(p, axis, pivot) for p, _ in snap}
        with self.world._tx("region.mirror", region=self.name, axis=axis):
            for p, _ in snap:
                self.world._write(p, AIR)
            for p, bk in snap:
                self.world._write(moved[p], mirror_block(bk, axis))
        self.cells = set(moved.values())
        self.box = _bbox(self.cells)
        self._sync_descendants(moved)
        self._sync_ancestors(moved)
        return len(snap)

    def rotate(self, yaw: int = 90, center=None) -> int:
        """绕 Y 旋转整个区域（含朝向重映射）。center 默认取区域中心。"""
        self._guard()
        b = self.box
        if b is None:
            return 0
        if center is None:
            center = V((b.lo.x + b.hi.x) // 2, b.lo.y, (b.lo.z + b.hi.z) // 2)
        else:
            center = V(int(center[0]), int(center[1]), int(center[2]))
        snap = [(p, self.world.get(p)) for p in sorted(self._op_cells())]
        moved = {p: rot_y(p - center, yaw) + center for p, _ in snap}
        with self.world._tx("region.rotate", region=self.name, yaw=yaw):
            for p, _ in snap:
                self.world._write(p, AIR)
            for p, bk in snap:
                self.world._write(moved[p], rotate_block(bk, yaw))
        self.cells = set(moved.values())
        self.box = _bbox(self.cells)
        self._sync_descendants(moved)
        self._sync_ancestors(moved)
        return len(snap)

    def copy_to(self, delta, name: Optional[str] = None, yaw: int = 0,
                with_children: bool = True, _parent=None,
                _pivot: Optional[V] = None) -> "Region":
        """把区域复制一份到别处（**原区域保留**）。返回新区域。

        ``with_children=True``（默认）会连**子区域**一起复制并重建层级 ——
        复制一座有楼阁的岛，新岛上的楼阁仍然是独立可操作的区域，
        名字是 ``新父名/原子名``（如 ``island_b/pav_1``）。

        空岛场景最常用的一招：造好一个岛，复制若干个再各自微调。
        """
        d = V(int(delta[0]), int(delta[1]), int(delta[2]))
        b = self.box
        if b is None:
            raise ValueError(f"区域 {self.name!r} 是空的")
        # 旋转时子区域必须绕**父区域的中心**转，否则会和父错开
        c = _pivot if _pivot is not None else V(
            (b.lo.x + b.hi.x) // 2, b.lo.y, (b.lo.z + b.hi.z) // 2)

        def move(p: V) -> V:
            return (rot_y(p - c, yaw) + c + d) if yaw else (p + d)

        new_name = name or f"{self.name}_copy"
        snap = [(p, self.world.get(p)) for p in sorted(self._op_cells())]
        new = Region(new_name, self.world, parent=_parent)
        with self.world._tx("region.copy", region=self.name, to=new_name):
            for p, bk in snap:
                self.world._write(move(p), rotate_block(bk, yaw) if yaw else bk)
        new.cells = {move(p) for p, _ in snap}
        new.box = _bbox(new.cells)
        self.world.regions[new_name] = new

        if with_children:
            for child in self.children():
                # child.name 已经是 "父/子" 的路径形式，拼新名字时只能取末段，
                # 否则会拼出 "island_a2/island_a/pav" 这种重复前缀。
                leaf = child.name.split("/")[-1]
                child.copy_to(d, name=f"{new_name}/{leaf}", yaw=yaw,
                              with_children=True, _parent=new, _pivot=c)
        return new

    def clear(self) -> int:
        """清空整个区域（含子区域）。"""
        n = 0
        with self.world._tx("region.clear", region=self.name):
            for p in sorted(self._op_cells()):
                if p in self.world.cells:
                    self.world._write(p, AIR)
                    n += 1
        for r in self.children():
            r.cells = set()
            r.box = None
        self.cells = set()
        self.box = None
        return n

    # ------------------------------------------------------------ 导出
    def export_schem(self, path, **kw):
        """只导出这个区域（**连同它的子区域结构**）。

        导出文件里带区域元数据，导入回来时区域与层级会自动重建 ——
        这是多 agent 分工的关键：各自建的岛导出后合并，仍然能按区域操作，
        而不是退化成一堆体素。
        """
        from .io import export_schem
        from .world import World

        sub = World()
        sub.cells = {p: b for p, b in self.blocks().items()}
        sub.block_entities = {p: v for p, v in self.world.block_entities.items()
                              if p in self.cells}
        lo = self.box.lo if self.box else V(0, 0, 0)
        for e in self.world.entities:
            pos = e.get("Pos")
            if pos is None or len(pos) != 3:
                continue
            if self.box and V(int(pos[0]), int(pos[1]), int(pos[2])) in self.box:
                d = dict(e)
                d["Pos"] = [pos[0] - lo.x, pos[1] - lo.y, pos[2] - lo.z]
                sub.entities.append(d)
        # 平移到原点导出，方便直接粘贴
        sub.cells = {p - lo: b for p, b in sub.cells.items()}
        sub.block_entities = {p - lo: v for p, v in sub.block_entities.items()}

        # 区域结构：自己 + 后代，一并平移到 sub 的坐标系
        groups = [self] + self.children()
        made: Dict[str, Region] = {}
        for r in groups:
            nr = Region(r.name, sub)
            nr.cells = {(p - lo) for p in r.cells if (p - lo) in sub.cells}
            if not nr.cells:
                continue
            nr.box = _bbox(nr.cells)
            sub.regions[r.name] = nr
            made[r.name] = nr
        for r in groups:
            if r.name in made and r.parent is not None and r.parent.name in made:
                made[r.name].parent = made[r.parent.name]
        return export_schem(sub, path, **kw)

    def export_tiled(self, out_dir, **kw):
        """只导出这个区域，并按 48³ 分块。"""
        from .io import export_tiled
        from .world import World

        sub = World()
        sub.cells = {p: b for p, b in self.blocks().items()}
        sub.block_entities = {p: v for p, v in self.world.block_entities.items()
                              if p in self.cells}
        return export_tiled(sub, out_dir, **kw)

    def __repr__(self) -> str:  # noqa: D105
        return (f"Region({self.name!r}, {len(self.cells)} 格, "
                f"{self.box}, {len(self.instances)} 实例)")


class _RegionCtx:
    """``with w.region("name") as r:`` 的上下文对象。支持嵌套。"""

    def __init__(self, world, name: str) -> None:
        self.w = world
        self.name = name
        self.n0 = 0
        self.i0 = 0

    def __enter__(self) -> Region:
        self.n0 = len(self.w._undo)
        self.i0 = len(self.w.instances)
        stack = self.w._region_stack
        parent = stack[-1] if stack else None
        r = self.w.regions.get(self.name)
        if r is None:
            r = self.w.regions[self.name] = Region(self.name, self.w)
        # 挂父：首次以嵌套方式出现时才挂，且**不能成环**
        # （`with A: with B: with A:` 这种写法不该把 A 挂到 B 下面）
        if parent is not None and r.parent is None and not r._is_ancestor_of(parent):
            r.parent = parent
        stack.append(r)
        return r

    def __exit__(self, *exc) -> None:
        if self.w._region_stack:
            self.w._region_stack.pop()
        patch = [c for sub in self.w._undo[self.n0:] for c in sub]
        # 合并进已有区域（同一个名字可以分多次 with 块累积）
        r = self.w.regions[self.name]
        r.cells |= {p for p, old, new in patch if not new.is_air}
        for p, old, new in patch:
            if new.is_air:
                r.cells.discard(p)
        r.box = _bbox(r.cells)
        for inst in self.w.instances[self.i0:]:
            if inst not in r.instances:
                r.instances.append(inst)
        return None


class RegionMixin:
    """挂在 World 上的区域能力。"""

    def _init_regions(self) -> None:
        self.regions: Dict[str, Region] = {}
        self._region_stack: List[Region] = []

    def region(self, name: str) -> _RegionCtx:
        """定义一个命名区域。可对同一个名字多次开启（内容累积），也可嵌套。

            with w.region("island_a") as isl:
                w.fill(..., "grass_block")
                with w.region("pav_1") as p:      # 岛上的楼阁
                    build_pavilion(w)

        嵌套之后：搬走岛会连楼阁一起搬；楼阁也能单独搬（哪怕它的地板和岛面同格）。
        """
        return _RegionCtx(self, name)

    def region_of(self, name: str) -> Region:
        """取已有区域（不存在则报错）。"""
        if name not in self.regions:
            raise KeyError(f"未定义的区域: {name!r}（已有: {sorted(self.regions)}）")
        return self.regions[name]

    def region_at(self, pos, solid_only: bool = True) -> Optional[Region]:
        """某个坐标属于哪个区域。

        ``solid_only=True``（默认）时**空位置返回 None** —— 问"这一点属于谁"，
        通常关心的是实际有内容的地方。要查历史归属（比如 diff 里的"移除"）
        就传 ``False``。

        多个区域都命中时：**先取层级最深的**（岛上的楼阁优先于岛），
        同深度则取**后定义的**（那格的内容通常是它写的，与 `owned()` 一致）。
        """
        p = V(int(pos[0]), int(pos[1]), int(pos[2]))
        if solid_only and self.get(p).is_air:
            return None
        order = {n: i for i, n in enumerate(self.regions)}
        hits = [r for r in self.regions.values() if p in r.cells]
        if not hits:
            return None
        hits.sort(key=lambda r: (-r.depth(), -order[r.name]))
        return hits[0]

    def region_table(self, sort_by: str = "name") -> List[dict]:
        """区域一览（含层级与大小）。建筑群开工前先看这张表::

            [{'name': 'island_a', 'parent': None, 'depth': 0,
              'cells': 381, 'owned': 256, 'op': 381, 'box': ...},
             {'name': 'pav_1', 'parent': 'island_a', 'depth': 1,
              'cells': 150, 'owned': 150, 'op': 150, 'box': ...}]

        ``op`` 是变换/导出实际作用的格数（自己 + 后代的独占）。
        """
        rows = []
        for r in self.regions.values():
            rows.append({
                "name": r.name,
                "parent": r.parent.name if r.parent is not None else None,
                "depth": r.depth(),
                "cells": len(r.cells),
                "owned": len(r.owned()),
                "op": len(r._op_cells()),
                "box": r.box,
            })
        if sort_by == "size":
            rows.sort(key=lambda d: -d["op"])
        else:
            rows.sort(key=lambda d: (d["depth"], d["name"]))
        return rows
