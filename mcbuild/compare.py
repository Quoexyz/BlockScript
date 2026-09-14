"""几何比较：对称性校验与区域/实例比对。

大建筑里对称错误是最常见的低级错误（左塔画完、右侧手滑少一格），
而它在 ASCII 切片里极难用肉眼发现。`mirror` / `rotate_area` 负责**生成**对称，
本模块负责**验证**对称。

    w.compare.symmetry(box((-12, 64, -12), (12, 90, 12)), axis="x")
    w.compare.rotational(bx, yaw=90)
    w.compare.regions(boxA, boxB, yaw=0)
    w.compare.instances("bay", 0, 3)      # 8 个开间本应完全一致
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .block import AIR, Block, mirror_block, normalize, rotate_block
from .vec import V, Box, box, rot_y


@dataclass
class Diff:
    """一处不一致。"""

    kind: str          # mirror / rotate / region / instance
    a: V               # A 侧位置
    b: V               # B 侧位置
    got: Block         # A 侧实际
    want: Block        # B 侧按变换后应有的样子

    def __str__(self) -> str:  # noqa: D105
        return (f"{self.kind}: {self.a} = {self.got.short() or 'air'} "
                f"≠ {self.b} = {self.want.short() or 'air'}")

    def __repr__(self) -> str:  # noqa: D105
        return str(self)


def _mirror_pos(p: V, axis: str, pivot: float) -> V:
    if axis == "x":
        return p.replace(x=int(round(2 * pivot - p.x)))
    if axis == "z":
        return p.replace(z=int(round(2 * pivot - p.z)))
    return p.replace(y=int(round(2 * pivot - p.y)))


def _by_id(b: Block) -> Block:
    """剥掉 blockstate，只留下方块 id（朝向盲比较用）。"""
    return b if b.is_air or not b.state else Block(b.id, ())


@dataclass
class Change:
    """一处变化。"""

    pos: V
    old: Block
    new: Block

    @property
    def kind(self) -> str:
        if self.old.is_air:
            return "added"
        if self.new.is_air:
            return "removed"
        return "changed"

    def __str__(self) -> str:  # noqa: D105
        return (f"{self.pos} {self.old.short() or 'air'} -> "
                f"{self.new.short() or 'air'}")


@dataclass
class DiffReport:
    """结构化的差异报告（不是画出来的图，是能直接读/统计的数据）。"""

    changes: List[Change] = field(default_factory=list)
    label: str = ""

    def __len__(self) -> int:
        return len(self.changes)

    @property
    def added(self) -> List[Change]:
        return [c for c in self.changes if c.kind == "added"]

    @property
    def removed(self) -> List[Change]:
        return [c for c in self.changes if c.kind == "removed"]

    @property
    def changed(self) -> List[Change]:
        return [c for c in self.changes if c.kind == "changed"]

    @property
    def empty(self) -> bool:
        return not self.changes

    def box(self) -> Optional[Box]:
        """变化范围的包围盒。"""
        if not self.changes:
            return None
        ps = [c.pos for c in self.changes]
        return box(V(min(p.x for p in ps), min(p.y for p in ps), min(p.z for p in ps)),
                   V(max(p.x for p in ps), max(p.y for p in ps), max(p.z for p in ps)))

    def by_region(self, world) -> Dict[str, int]:
        """按区域汇总改动数 —— 大建筑里"哪一块被动了"比"哪几格被动了"有用。

        查的是**历史归属**（``solid_only=False``），否则被移除的格子会因为
        现在是空气而归不进任何区域。
        """
        out: Dict[str, int] = {}
        for c in self.changes:
            r = world.region_at(c.pos, solid_only=False)
            key = r.name if r is not None else "(未分区)"
            out[key] = out.get(key, 0) + 1
        return out

    def by_kind(self) -> Dict[str, int]:
        return {"added": len(self.added), "removed": len(self.removed),
                "changed": len(self.changed)}

    def report(self, limit: int = 10, world=None) -> str:
        if self.empty:
            return f"diff {self.label}：无变化"
        k = self.by_kind()
        lines = [f"diff {self.label}：共 {len(self.changes)} 处"
                 f"（新增 {k['added']} · 移除 {k['removed']} · 替换 {k['changed']}）"]
        b = self.box()
        if b:
            lines.append(f"  范围 {b.lo}..{b.hi}")
        if world is not None:
            regs = self.by_region(world)
            if regs:
                top = sorted(regs.items(), key=lambda kv: -kv[1])
                lines.append("  按区域：" + " · ".join(f"{n} {v}"
                                                     for n, v in top[:6]))
        for c in self.changes[:limit]:
            lines.append(f"  [{c.kind[:3]}] {c}")
        if len(self.changes) > limit:
            lines.append(f"  … 还有 {len(self.changes) - limit} 处")
        return "\n".join(lines)


class Compare:
    def __init__(self, world) -> None:
        self.w = world

    def _candidates(self, bx: Box) -> List[V]:
        """bx 内**已占**的格子（按 y,z,x 排序，保证输出稳定）。

        遍历已占格子而不是整个包围盒体积 —— 这是 compare 能上规模的关键：
        100³ 的盒子里可能只有几百个方块，逐格遍历体积要 2.4 秒，
        只遍历方块只要几毫秒。差异是双向的（一侧缺、一侧多）都能覆盖到，
        因为对每个存在的方块都会检查它在另一侧的镜像位置。
        """
        pts = [p for p in self.w.cells if p in bx]
        pts.sort(key=lambda v: (v.y, v.z, v.x))
        return pts

    # ------------------------------------------------------------ 对称
    def symmetry(self, bx=None, axis: str = "x", pivot=None) -> List[Diff]:
        """镜像对称校验：bx 内沿 axis 对折，逐格比对（含朝向翻转）。"""
        bx = box(bx) if bx is not None else self.w.bounds()
        if bx is None:
            return []
        if pivot is None:
            pivot = ((bx.lo.x + bx.hi.x) / 2 if axis == "x"
                     else (bx.lo.z + bx.hi.z) / 2 if axis == "z"
                     else (bx.lo.y + bx.hi.y) / 2)
        out: List[Diff] = []
        seen = set()
        for p in self._candidates(bx):
            q = _mirror_pos(p, axis, pivot)
            if q == p or p in seen or q in seen or q not in bx:
                continue
            seen.add(p)
            seen.add(q)
            got = self.w.get(p)
            want = mirror_block(self.w.get(q), axis)
            if normalize(got) != normalize(want):
                out.append(Diff("mirror", p, q, got, want))
        return out

    def rotational(self, bx=None, yaw: int = 90, center=None) -> List[Diff]:
        """旋转对称校验。要求 bx 在 x/z 上等长（否则旋转后不自洽）。"""
        bx = box(bx) if bx is not None else self.w.bounds()
        if bx is None:
            return []
        if (bx.hi.x - bx.lo.x) != (bx.hi.z - bx.lo.z):
            raise ValueError("rotational 要求区域在 x/z 上等长")
        if center is None:
            center = V((bx.lo.x + bx.hi.x) // 2, bx.lo.y, (bx.lo.z + bx.hi.z) // 2)
        else:
            center = V(int(center[0]), int(center[1]), int(center[2]))
        out: List[Diff] = []
        for p in self._candidates(bx):
            q = rot_y(p - center, yaw) + center
            if q not in bx:
                continue
            got = self.w.get(p)
            want = rotate_block(self.w.get(q), yaw)
            if normalize(got) != normalize(want):
                out.append(Diff("rotate", p, q, got, want))
        return out

    # ------------------------------------------------------------ 区域 / 实例
    def regions(self, a, b, yaw: int = 0) -> List[Diff]:
        """比较两个同尺寸区域（b 相对 a 可旋转 yaw）。"""
        ba, bb = box(a), box(b)
        if ba.size != bb.size:
            raise ValueError(f"两区域尺寸不同: {ba.size} vs {bb.size}")
        pts = set(self._candidates(ba)) | set(self._candidates(bb))
        out: List[Diff] = []
        for p in sorted(pts, key=lambda v: (v.y, v.z, v.x)):
            if p in ba:                      # 以 A 侧为基准找对应点
                off = p - ba.lo
                q = bb.lo + rot_y(off, yaw)
                got, want = self.w.get(p), rotate_block(self.w.get(q), yaw)
                if normalize(got) != normalize(want):
                    out.append(Diff("region", p, q, got, want))
            else:                            # 只存在于 B 侧的格子，反查 A 侧
                off = rot_y(p - bb.lo, -yaw)
                q = ba.lo + off
                got, want = self.w.get(q), rotate_block(self.w.get(p), yaw)
                if normalize(got) != normalize(want):
                    out.append(Diff("region", q, p, got, want))
        return out

    def instances(self, name: str, i: int = 0, j: int = 1,
                  orientation_blind: bool = False) -> List[Diff]:
        """比较两个实例的局部布局。yaw 不同会自动补偿旋转。

        ``orientation_blind=True`` 时忽略 blockstate 只比方块 id ——
        于是"同一个开间转了 90° 放进耳堂"也能判定为一致
        （对应 Nucleation fingerprint 的 ``shape`` 档）。

        只遍历 i 号实例写入过的格子，因此 j 号缺失的格子也会被检出。
        """
        a = self.w.instance(name, i)
        b = self.w.instance(name, j)
        dyaw = b.yaw - a.yaw
        out: List[Diff] = []
        for p in sorted(a.cells):
            lp = a.to_local(p)
            q = b.to_world(lp)
            got = self.w.get(p)
            want = rotate_block(self.w.get(q), dyaw)
            if orientation_blind:
                got, want = _by_id(got), _by_id(want)
            if normalize(got) != normalize(want):
                out.append(Diff("instance", p, q, got, want))
        return out

    # ------------------------------------------------------------ 差异
    def _diff_cells(self, old: Dict[V, Block], new: Dict[V, Block],
                    mode: str, label: str) -> DiffReport:
        by_id = mode == "shape"
        changes: List[Change] = []

        def same(a: Block, b: Block) -> bool:
            if by_id:
                return a.id == b.id
            return normalize(a) == normalize(b)

        for p in new:
            if p not in old:
                changes.append(Change(p, AIR, new[p]))
        for p in old:
            if p not in new:
                changes.append(Change(p, old[p], AIR))
            elif not same(old[p], new[p]):
                changes.append(Change(p, old[p], new[p]))
        changes.sort(key=lambda c: (c.pos.y, c.pos.z, c.pos.x))
        return DiffReport(changes, label)

    def diff(self, after, before=None, mode: str = "exact") -> DiffReport:
        """拿另一个状态和**当前世界**比（``before`` 默认就是 ``self.w``）。

            report = w.compare.diff(w_old)          # 旧版 -> 现在
            report = w.compare.diff(b, before=a)    # 显式指定两边

        参数也可以是 ``{位置: 方块}`` 字典。返回**结构化**结果而不是画一张图 ——
        模型可以直接读分类统计、按区域汇总，不必从 ASCII 图里找变化。

        | mode | 判定"没变"的依据 |
        |---|---|
        | ``exact``（默认） | 方块 id + 属性（默认值已归一化，写不写等价） |
        | ``shape`` | 只看方块 id（忽略朝向等属性） |
        """
        if mode not in ("exact", "shape"):
            raise ValueError(f"mode 只能是 exact / shape，收到 {mode!r}")
        b = self.w if before is None else before
        oc = getattr(b, "cells", b)
        nc = getattr(after, "cells", after)
        return self._diff_cells(oc, nc, mode, "before -> after")

    def since_checkpoint(self, mode: str = "exact") -> DiffReport:
        """当前状态相对最近一次 ``w.checkpoint()`` 的变化。

        适合回给模型一句话：'你这轮改了 37 处，其中中殿 30 处、塔 7 处'。
        """
        return self._diff_cells(self.w._baseline, self.w.cells, mode,
                               "since checkpoint")

    def duplicates(self, boxes: List, mode: str = "shape") -> List[tuple]:
        """在一组区域里找出**重复的**（按指纹，平移不变）。

        返回 ``[(指纹, [区域下标, ...]), ...]``，长度 > 1 的即为重复组。
        抄来的、镜像出来的、旋转放置的同一栋楼会被归到一起。
        """
        groups: Dict[frozenset, List[int]] = {}
        for i, bx in enumerate(boxes):
            groups.setdefault(self.fingerprint(bx, mode=mode), []).append(i)
        return [(fp, idx) for fp, idx in groups.items() if len(idx) > 1]

    # ------------------------------------------------------------ 指纹
    def fingerprint(self, bx=None, mode: str = "exact"):
        """把一块区域压成可哈希的指纹，**平移不变**。

        直接比较两个区域的指纹即可判断"是不是同一个东西"::

            w.compare.fingerprint(a) == w.compare.fingerprint(b)

        | mode | 对什么不敏感 | 一块砖是 |
        |---|---|---|
        | ``exact`` | 平移 | id + 属性 |
        | ``shape`` | 平移 + **全部朝向** | 只有 id |

        注意 ``shape`` 档丢掉了属性，别拿它做内容去重（玻璃板之类的差异会被忽略）。
        """
        if mode not in ("exact", "shape"):
            raise ValueError(f"mode 只能是 exact / shape，收到 {mode!r}")
        bx = box(bx) if bx is not None else self.w.bounds()
        if bx is None:
            return frozenset()
        pts = self._candidates(bx)
        if not pts:
            return frozenset()
        lo = V(min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts))
        out = set()
        for p in pts:
            b = self.w.get(p)
            rel = (p.x - lo.x, p.y - lo.y, p.z - lo.z)
            out.add((rel, b.id) if mode == "shape"
                    else (rel, b.id, normalize(b).state))
        return frozenset(out)

    # ------------------------------------------------------------ 汇总
    def report(self, diffs: List[Diff], limit: int = 20) -> str:
        if not diffs:
            return "一致：无差异"
        lines = [f"共 {len(diffs)} 处不一致" + (f"（显示前 {limit} 条）" if len(diffs) > limit else "")]
        for d in diffs[:limit]:
            lines.append("  " + str(d))
        return "\n".join(lines)

    def is_symmetric(self, bx=None, axis: str = "x") -> bool:
        return not self.symmetry(bx, axis)
