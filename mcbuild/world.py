"""稀疏体素世界。

世界是派生物：模型写的是 op 脚本，世界每次可从脚本重建。
cells 只存非空气；每次写入都进 undo 补丁并记录 dirty。
"""

from __future__ import annotations

import random
from contextlib import contextmanager
from typing import Dict, Iterable, List, Optional, Tuple

from .block import AIR, Block, classify, make
from .component import ComponentMixin
from .frame import Frame
from .grid import Grid
from .marks import MarkLayer
from .camera import CameraMixin
from .ops import OpsMixin
from .preview import PreviewMixin
from .region import RegionMixin
from .stage import StageMixin
from .vec import V, Box, box

Patch = List[Tuple[V, Block, Block]]


def _pos_hash(seed: int, x: int, y: int, z: int) -> int:
    """位置哈希（FNV-1a 变体，纯整数运算，跨平台且跨进程确定）。

    刻意不用 Python 的 ``hash()`` —— 字符串哈希受 PYTHONHASHSEED 随机化影响，
    会导致同一份脚本在不同机器上产出不同纹理。
    """
    h = (int(seed) & 0xFFFFFFFF) ^ 0x811C9DC5
    for v in (x, y, z):
        h = ((h ^ (int(v) & 0xFFFFFFFF)) * 0x01000193) & 0xFFFFFFFF
        h ^= h >> 15
    return h


class World(OpsMixin, ComponentMixin, StageMixin, PreviewMixin, RegionMixin,
            CameraMixin):
    def __init__(self, seed: int = 0) -> None:
        self.cells: Dict[V, Block] = {}
        self.marks = MarkLayer()
        self.grids: Dict[str, Grid] = {}
        self.block_entities: Dict[V, dict] = {}     # 位置 -> 方块实体 NBT（告示牌文字、箱子内容……）
        self.entities: List[dict] = []              # 实体（盔甲架、画、物品展示框……）
        self.seed = int(seed)
        self.rng = random.Random(seed)
        self.ops_log: List[dict] = []
        self._undo: List[Patch] = []
        self._redo: List[Patch] = []
        self._baseline: Dict[V, Block] = {}
        self._depth = 0
        self._cur: Patch = []
        self._query = None
        self._render = None
        self._image = None
        self._compare = None
        self._material = None
        self._variant_cache: Dict[tuple, Block] = {}
        self._init_components()
        self._init_stages()
        self._init_regions()
        self._init_camera()

    # -------------------------------------------------- 材质混合
    @contextmanager
    def material(self, mapping: Dict[str, Dict[str, float]], seed: Optional[int] = None):
        """材质混合上下文：块内的方块按权重随机换成变体。

        图案由**位置哈希**决定，不是随机序列，所以：

        * 同一份脚本重跑结果完全一致（确定性，跨机器一致）
        * 同一个组件 ``place`` 到不同位置，纹理图案**各不相同** ——
          这正是消除"复制粘贴感"的关键
        * 模板改动不会扰动其他位置的图案

        用法::

            with w.material({"stone_bricks": {"cracked_stone_bricks": 0.12,
                                              "mossy_stone_bricks": 0.08}}):
                w.wall(box(...), "stone_bricks")

        变体与原方块**同族**时继承其 state（朝向 / half 等），
        所以 ``spruce_stairs[facing=east]`` 抖成 ``oak_stairs`` 后朝向仍在。
        """
        old = self._material
        self._material = (mapping, self.seed if seed is None else int(seed))
        try:
            yield self
        finally:
            self._material = old

    def _variant(self, base: Block, name) -> Block:
        key = (base.id, str(name))
        v = self._variant_cache.get(key)
        if v is None:
            v = make(name)
            self._variant_cache[key] = v
        if v.is_air:
            return v
        if base.state and classify(v.id) == classify(base.id):
            return v.with_state(**base.props())
        return v

    def _mix(self, block: Block, pos: V) -> Block:
        table, seed = self._material
        variants = table.get(block.id)
        if variants is None:
            variants = table.get(block.name)
        if not variants:
            return block
        r = _pos_hash(seed, pos.x, pos.y, pos.z) / 0x100000000
        acc = 0.0
        for name, weight in variants.items():
            acc += float(weight)
            if r < acc:
                return self._variant(block, name)
        return block

    # -------------------------------------------------- 事务 / undo
    @contextmanager
    def _tx(self, name: str = "", **kw):
        outermost = self._depth == 0
        if outermost:
            self._cur = []
        self._depth += 1
        try:
            yield
        finally:
            self._depth -= 1
            if outermost:
                if self._cur:
                    if name:
                        self.ops_log.append({"op": name, "cells": len(self._cur), **kw})
                    self._undo.append(self._cur)
                    self._redo.clear()
                self._cur = []

    def _write(self, pos: V, block: Block) -> None:
        if self._material is not None and not block.is_air:
            block = self._mix(block, pos)
        old = self.cells.get(pos, AIR)
        if old == block:
            return
        if block.is_air:
            self.cells.pop(pos, None)
        else:
            self.cells[pos] = block
        self._cur.append((pos, old, block))
        if self._depth == 0 and self._cur:
            self._undo.append(self._cur)
            self._redo.clear()
            self._cur = []

    def _apply(self, patch: Patch, reverse: bool) -> None:
        seq = reversed(patch) if reverse else patch
        for pos, old, new in seq:
            b = old if reverse else new
            if b.is_air:
                self.cells.pop(pos, None)
            else:
                self.cells[pos] = b

    def undo(self) -> bool:
        if not self._undo:
            return False
        patch = self._undo.pop()
        self._apply(patch, reverse=True)
        self._redo.append(patch)
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        patch = self._redo.pop()
        self._apply(patch, reverse=False)
        self._undo.append(patch)
        return True

    def checkpoint(self) -> None:
        """把当前状态设为 diff 基线。"""
        self._baseline = dict(self.cells)

    # -------------------------------------------------- 读写
    def set(self, pos, block=None, nbt=None, **state) -> Block:
        """写一个方块。

        ``nbt`` 给方块实体数据（告示牌文字、箱子内容、旗帜图案……）::

            w.set((0, 65, 0), "oak_sign", rotation=8,
                  nbt={"front_text": {"messages": ['{"text":"滕王阁"}']}})
            w.set((1, 64, 0), "chest",
                  nbt={"Items": [{"Slot": 0, "id": "minecraft:diamond", "Count": 3}]})

        方块被清空时对应的方块实体一并移除；换成别的方块则保留 `nbt` 不动的旧行为
        只在显式传参时改变。
        """
        if block is None and not state:
            raise ValueError("set() 需要 block 或 blockstate 参数")
        pos = V(int(pos[0]), int(pos[1]), int(pos[2]))
        b = block if isinstance(block, Block) else make(block, **state)
        with self._tx("set", pos=repr(pos), block=b.key()):
            self._write(pos, b)
            if nbt is not None:
                self.block_entities[pos] = nbt
            elif b.is_air:
                self.block_entities.pop(pos, None)
        return b

    def entity(self, pos, id: str, **nbt) -> dict:
        """放置一个实体。

            w.entity((4, 64, 4), "armor_stand", ShowArms=1, Pose={...})
            w.entity((2, 66, 2), "painting", Facing=2, Motive="Kebab")

        ``pos`` 是方块坐标，落库时会自动加 0.5 居中（实体坐标是浮点）。
        """
        p = V(int(pos[0]), int(pos[1]), int(pos[2]))
        e = {
            "id": id if ":" in id else f"minecraft:{id}",
            "Pos": [p.x + 0.5, float(p.y), p.z + 0.5],
        }
        e.update(nbt)
        self.entities.append(e)
        return e

    def get(self, pos) -> Block:
        return self.cells.get(V(int(pos[0]), int(pos[1]), int(pos[2])), AIR)

    def fill(self, bx, block=None, **state) -> int:
        if block is None and not state:
            raise ValueError("fill() 需要 block 或 blockstate 参数")
        bx = box(bx)
        b = block if isinstance(block, Block) else make(block, **state)
        n = 0
        with self._tx("fill", box=repr(bx), block=b.key()):
            for p in bx:
                self._write(p, b)
                n += 1
        return n

    def clear(self, bx) -> int:
        bx = box(bx)
        n = 0
        with self._tx("clear", box=repr(bx)):
            for p in bx:
                if p in self.cells:
                    self._write(p, AIR)
                    n += 1
        return n

    def replace(self, bx, src=None, dst="air") -> int:
        """把区域里等于 src 的方块换成 dst。src=None 表示空气。"""
        bx = box(bx)
        src_b = None if src is None else (src if isinstance(src, Block) else make(src))
        dst_b = dst if isinstance(dst, Block) else make(dst)
        n = 0
        with self._tx("replace", box=repr(bx), src=src, dst=dst_b.key()):
            for p in list(bx):
                cur = self.cells.get(p, AIR)
                if (src_b is None and cur.is_air) or (src_b is not None and cur == src_b):
                    self._write(p, dst_b)
                    n += 1
        return n

    # -------------------------------------------------- 坐标 / 标记
    def frame(self, at=(0, 0, 0), yaw: int = 0) -> Frame:
        return Frame(self, at, yaw)

    def map_axis(self, axis: str) -> str:
        return axis

    def mark(self, name: str, pos) -> V:
        return self.marks.set_point(name, pos)

    def mark_box(self, name: str, bx) -> Box:
        return self.marks.set_box(name, bx)

    def anchor(self, name: str) -> V:
        return self.marks.anchor(name)

    # -------------------------------------------------- 轴网
    def grid(self, name: str, origin=(0, 0, 0), axis: str = "z",
             spacing: int = 1, n: int = 1, axes=None) -> Grid:
        """定义轴网。一维写 axis/spacing/n，二维写 axes=[("x",6,5),("z",6,8)]。"""
        if axes is None:
            axes = [(axis, int(spacing), int(n))]
        g = Grid(name=name, origin=V(int(origin[0]), int(origin[1]), int(origin[2])),
                 axes=[tuple(a) for a in axes])
        self.grids[name] = g
        return g

    def _grid(self, name: str) -> Grid:
        if name not in self.grids:
            raise KeyError(f"未定义的轴网: {name}（可用: {sorted(self.grids)}）")
        return self.grids[name]

    def grid_at(self, name: str, *idx) -> V:
        """第 i（, j）个格点的世界坐标。"""
        return self._grid(name).at(*idx)

    def grid_cell(self, name: str, *idx, size: int = 0) -> Box:
        """第 i 格占据的范围。"""
        return self._grid(name).cell(*idx, size=size)

    def grid_span(self, name: str, *idx) -> Box:
        """格点到格点的包围盒。"""
        return self._grid(name).span(*idx)

    def grid_cover(self, name: str, *idx) -> Box:
        """覆盖第 i0..i1 格的全部范围（末格按整格宽度计入）。"""
        return self._grid(name).cover(*idx)

    # -------------------------------------------------- 形状 / 材质
    def paint(self, shape, brush, bx=None) -> int:
        """用 Shape 定义几何、Brush 定义材质，写进世界。

        ``fill(box, block)`` 是它的特例（形状 = 长方体、材质 = 常数）。
        这里形状和材质可以各自独立替换 —— 同一个形状换 brush 就换效果。

            w.paint(Shape.sphere((0, 80, 0), 12), Brush.solid("glass"))
            w.paint(Shape.box(bx), Brush.by_height([...]))       # 按高度风化
            w.paint(Shape.subtract(a, b), Brush.by_normal({...}))  # 按法线换材质

        ``bx`` 可覆盖遍历范围（默认用 shape.bounds，必须包住所有命中坐标）。
        返回写入格数。
        """
        b = shape.bounds if bx is None else box(bx)
        n = 0
        with self._tx("paint", shape=repr(shape), brush=repr(brush)):
            for p in b:
                if not shape.contains(p):
                    continue
                blk = brush.of(p, shape)
                if blk is None or blk.is_air:
                    continue
                self._write(p, blk)
                n += 1
        return n

    def erase(self, shape, bx=None) -> int:
        """按 Shape 挖空（paint 的形状版 clear）。"""
        b = shape.bounds if bx is None else box(bx)
        n = 0
        with self._tx("erase", shape=repr(shape)):
            for p in b:
                if shape.contains(p) and p in self.cells:
                    self._write(p, AIR)
                    n += 1
        return n

    # -------------------------------------------------- 换配色
    def repaint(self, mapping=None, *, family=None) -> int:
        """整体换材质，返回改动格数。

            w.repaint(family=("stone", "quartz"))            # 石材 → 石英
            w.repaint({"stone_bricks": "deepslate_tiles"})    # 只换一种
            w.repaint(lambda b: "gold_block" if b.name.endswith("_bricks") else None)

        callable 返回新方块 id（``str`` / ``Block``），或 ``None`` 表示不动。
        映射时**继承原 blockstate**（朝向 / half / type），楼梯换材质后还是楼梯。
        """
        from .palette import family_map, retexture

        if family is not None:
            src, dst = family
            table = family_map(src, dst)
            fn = lambda b: retexture(b, table)          # noqa: E731
        elif callable(mapping):
            def fn(b):
                v = mapping(b)
                if v is None or v is False or v == b.id:
                    return None
                return v if isinstance(v, Block) else make(v, **b.props())
        elif isinstance(mapping, dict):
            fn = lambda b: retexture(b, mapping)        # noqa: E731
        else:
            raise ValueError("repaint 需要 mapping(dict/callable) 或 family=(src,dst)")

        n = 0
        with self._tx("repaint", family=family):
            for p, old in list(self.cells.items()):
                new = fn(old)
                if new is None or new == old:
                    continue
                self._write(p, new)
                n += 1
        return n

    # -------------------------------------------------- 查询 / 渲染
    @property
    def query(self):
        if self._query is None:
            from .query import Query
            self._query = Query(self)
        return self._query

    @property
    def render(self):
        if self._render is None:
            from .render import Render
            self._render = Render(self)
        return self._render

    @property
    def image(self):
        """等距投影 PNG 渲染器（美术验收用，见 `image.py`）。"""
        if self._image is None:
            from .image import Image
            self._image = Image(self)
        return self._image

    @property
    def compare(self):
        if self._compare is None:
            from .compare import Compare
            self._compare = Compare(self)
        return self._compare

    def bounds(self):
        if not self.cells:
            return None
        xs = [p.x for p in self.cells]
        ys = [p.y for p in self.cells]
        zs = [p.z for p in self.cells]
        return box(V(min(xs), min(ys), min(zs)), V(max(xs), max(ys), max(zs)))

    def unknown_blocks(self) -> List[tuple]:
        """列出世界里**拼错的**方块（每种一次，带拼写建议）。

        非 ``minecraft:`` 命名空间（mod 方块）会被跳过，不当错误。
        返回 ``[(位置, 方块 id, 诊断), ...]``::

            for pos, bid, msg in w.unknown_blocks():
                print(pos, msg)

        逐格写错名不会报错（那样太吵），所以这是事后自查的入口。
        """
        from .registry import check

        out = []
        seen = set()
        for p in sorted(self.cells, key=lambda v: (v.y, v.z, v.x)):
            bid = self.cells[p].id
            if bid in seen:
                continue
            seen.add(bid)
            msg = check(bid)
            if msg:
                out.append((p, bid, msg))
        return out

    def count(self) -> int:
        return len(self.cells)

    def dirty_box(self):
        """本轮改动（相对基线）的包围盒。"""
        changed = {p for p, b in self.cells.items() if self._baseline.get(p, AIR) != b}
        changed |= {p for p, b in self._baseline.items() if self.cells.get(p, AIR) != b}
        if not changed:
            return None
        xs = [p.x for p in changed]
        ys = [p.y for p in changed]
        zs = [p.z for p in changed]
        return box(V(min(xs), min(ys), min(zs)), V(max(xs), max(ys), max(zs)))

    # -------------------------------------------------- 校验 / 导出 / 会话
    def lint(self, **kw):
        """物理校验。可用 ``region=`` / ``level=`` / ``codes=`` 收窄（大建筑必备）。"""
        from .lint import lint
        return lint(self, **kw)

    def lint_summary(self, **kw):
        """按码汇总并分解到区域 —— 一眼看出"哪个建筑有问题"。"""
        from .lint import lint_summary
        return lint_summary(self, **kw)

    def report(self, exec_line: str = "", render_box=None):
        from .session import report
        return report(self, exec_line=exec_line, render_box=render_box)

    def export_schem(self, path, **kw):
        from .io import export_schem
        return export_schem(self, path, **kw)

    def import_schem(self, path, at=None, **kw):
        """读外部 ``.schem`` 并合并进本世界。

        ``at=None``（默认）用文件里的 Offset，即还原到导出时的位置；
        显式给 ``at`` 则落到指定坐标：:

            w.import_schem("castle_tower.schem", at=(10, 64, 10))

        ``regions=True``（默认）会还原文件里的命名分区；外部文件没有分区信息时，
        用文件名建一个区域把整块圈进去（`name=` / `prefix=` 可覆盖）。
        方块实体与实体一并还原。
        """
        from .io import import_schem
        return import_schem(path, self, at=at, **kw)

    @classmethod
    def from_schem(cls, path, at=None, **kw) -> "World":
        """从 ``.schem`` 新建一个 World（默认还原到它导出时的位置）。"""
        from .io import import_schem
        return import_schem(path, None, at=at, **kw)

    def merge(self, other, **kw) -> dict:
        """把另一个世界（或 ``{位置: 方块}``）合并进来，返回**冲突报告**。

            rep = w.merge(part_b, on_conflict="report")
            if rep["conflict_count"]:
                for pos, mine, theirs in rep["conflicts"][:10]:
                    print(pos, mine.short(), "->", theirs.short())

        ``on_conflict`` 取 ``"overwrite"``（默认）/ ``"skip"`` / ``"report"``。
        对方世界里的命名区域会一并带过来（重名加 ``@2`` 后缀）。
        """
        from .io import merge
        return merge(self, other, **kw)

    def export_nbt(self, path, **kw):
        from .io import export_nbt
        return export_nbt(self, path, **kw)

    def export_tiled(self, out_dir, chunk: int = 48, prefix: str = "part",
                     ext: str = "nbt", **kw):
        """分块导出（结构方块单块上限 48³）。

        返回清单，每项含 ``file`` / ``box``（该块在世界坐标里的范围）/ ``blocks``::

            for it in w.export_tiled("out/church"):
                print(it["file"], it["box"])
        """
        from .io import export_tiled
        return export_tiled(self, out_dir, chunk=chunk, prefix=prefix,
                            ext=ext, **kw)

    def export_json(self, path, **kw):
        from .io import export_json
        return export_json(self, path, **kw)

    def save(self, path):
        return self.export_json(path)

    @classmethod
    def load(cls, path) -> "World":
        from .io import import_json
        return import_json(path, cls())

    def __repr__(self) -> str:  # noqa: D105
        b = self.bounds()
        return f"World(blocks={len(self.cells)}, bounds={b})"
