"""ASCII 渲染。

设计要点：
  * 1 格 1 字符 + 自动图例，字符在同一次渲染内稳定
  * 每 5 格一个坐标刻度，行首带 z=NN | 前缀
  * 指北针标注；超预算自动降采样并标 scale
  * diff 模式只画相对基线的改动
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from .block import AIR, Block
from .vec import V, Box, box

OVERLAY_CHARS = {"north": "^", "south": "v", "east": ">", "west": "<"}
RESERVED = set(".^<>v ")


def _ruler(n: int, indent: int, labels: List[Optional[str]]) -> str:
    buf = [" "] * (indent + n + 8)
    for i, s in enumerate(labels):
        if s is None:
            continue
        for j, ch in enumerate(str(s)):
            if indent + i + j < len(buf):
                buf[indent + i + j] = ch
    return "".join(buf).rstrip()


def _assign_chars(keys: List[str]) -> Dict[str, str]:
    """给每种方块分配字符：优先用 id 首字母，冲突后退化到字母池。"""
    used = set(RESERVED)
    out: Dict[str, str] = {}
    pool = ("abcdefghijklmnopqrstuvwxyz"
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            "0123456789"
            "#*+=%&$@?/\\|:;!")
    for key in keys:
        name = key.split(":")[-1].split("[")[0]
        cands = []
        for ch in name:
            if ch.isalnum():
                cands.append(ch.lower())
                cands.append(ch.upper())
        cands.extend(pool)
        for c in cands:
            if c not in used:
                out[key] = c
                used.add(c)
                break
        else:
            out[key] = "?"
    return out


class Render:
    def __init__(self, world) -> None:
        self.w = world
        self.max_cells = 4000

    def budget(self, n: int) -> "Render":
        """设置本次渲染的字符预算，超出自动降采样。"""
        self.max_cells = max(64, int(n))
        return self

    def _auto_step(self, w: int, h: int, step: int) -> int:
        if step > 1:
            return step
        s = 1
        while ((w + s - 1) // s) * ((h + s - 1) // s) > self.max_cells and s < 64:
            s += 1
        return s

    # ---------------------------------------------------------------- 切片
    def slice(self, y: int, bx=None, overlay: Optional[str] = None, step: int = 1) -> str:
        b = self.w.bounds()
        if b is None:
            return "(空世界)"
        y = int(y)
        if bx is None:
            lo, hi = V(b.lo.x, y, b.lo.z), V(b.hi.x, y, b.hi.z)
        else:
            bx = box(bx)
            lo, hi = V(bx.lo.x, y, bx.lo.z), V(bx.hi.x, y, bx.hi.z)

        w = hi.x - lo.x + 1
        h = hi.z - lo.z + 1
        step = self._auto_step(w, h, step)

        xs = list(range(lo.x, hi.x + 1, step))
        zs = list(range(lo.z, hi.z + 1, step))
        zw = max(len(str(lo.z)), len(str(hi.z)), 1)
        indent = zw + 4

        keys, grid = [], []
        for z in zs:
            row = [self.w.get(V(x, y, z)) for x in xs]
            for blk in row:
                if not blk.is_air and overlay != "facing":
                    keys.append(blk.key())
            grid.append((z, row))

        cmap = _assign_chars(sorted(set(keys)))
        head = (f"slice y={y}   x:{lo.x}..{hi.x}  z:{lo.z}..{hi.z}   N↑ = z 减小"
                + (f"   scale=1:{step}" if step > 1 else ""))
        labels = [str(x) if i % 5 == 0 else None for i, x in enumerate(xs)]
        lines = [head, _ruler(len(xs), indent, labels)]
        for z, row in grid:
            lines.append(f"z={z:0{zw}d} |" + "".join(
                self._char_of(blk, cmap, overlay) for blk in row))
        lines.append("")
        lines.append(self._legend_text(cmap, overlay))
        return "\n".join(lines)

    def _char_of(self, blk: Block, cmap: Dict[str, str], overlay: Optional[str]) -> str:
        if blk.is_air:
            return "."
        if overlay == "facing":
            return OVERLAY_CHARS.get(blk.get("facing"), ".")
        return cmap.get(blk.key(), "?")

    # ---------------------------------------------------------------- 视口
    def _center(self, c) -> V:
        """center 接受 V / tuple / 锚点名 / Box（取中心）。"""
        if isinstance(c, str):
            return self.w.anchor(c)
        if isinstance(c, Box):
            return V((c.lo.x + c.hi.x) // 2, (c.lo.y + c.hi.y) // 2,
                     (c.lo.z + c.hi.z) // 2)
        return V(int(c[0]), int(c[1]), int(c[2]))

    def view(self, center, size=(16, 12, 16), step: int = 1,
             overlay: Optional[str] = None) -> str:
        """以 center 为中心的局部视图：水平 + X 剖面 + Z 剖面。

        大建筑里模型不可能一次看全，靠这个下钻到具体开间。
        center 可以是坐标、锚点名，也可以是 ``w.stage_box("nave")``
        或 ``w.instance("bay", 3).box`` 这类 Box（自动取中心）。
        """
        b = self.w.bounds()
        if b is None:
            return "(空世界)"
        c = self._center(center)
        sx, sy, sz = int(size[0]), int(size[1]), int(size[2])
        half = V(sx // 2, sy // 2, sz // 2)
        bx = box(c - half, c + half)
        return "\n".join([
            f"view @ {c}   size {sx}x{sy}x{sz}   box {bx.lo}..{bx.hi}",
            "",
            "[水平] " + self.slice(c.y, bx, overlay, step),
            "",
            "[X 剖面] " + self.section(axis="x", at=c.x, bx=bx, step=step),
            "",
            "[Z 剖面] " + self.section(axis="z", at=c.z, bx=bx, step=step),
        ])

    def overview(self, y=None, step: int = 8, center=None, size=None) -> str:
        """全景缩略图（默认 1:8），并把当前视口在图上标出来（行首 ``>``）。

        只给 y/step 就是纯全景；给了 center/size 会额外标出视口范围——
        这是模型在大建筑里"我在哪"的唯一依据。
        """
        b = self.w.bounds()
        if b is None:
            return "(空世界)"
        c = self._center(center) if center is not None else None
        yy = int(y) if y is not None else (
            c.y if c is not None else (b.lo.y + b.hi.y) // 2)
        body = self.slice(yy, step=step)
        if c is None or size is None:
            return f"overview  y={yy}   scale=1:{step}\n" + body

        sx, sy, sz = int(size[0]), int(size[1]), int(size[2])
        half = V(sx // 2, sy // 2, sz // 2)
        vb = box(c - half, c + half)
        out = []
        for ln in body.split("\n"):
            m = re.match(r"^(z=-?\d+) \|(.*)$", ln)
            if m:
                z = int(m.group(1)[2:])
                mark = ">" if vb.lo.z <= z <= vb.hi.z else "|"
                out.append(f"{m.group(1)} {mark}{m.group(2)}")
            else:
                out.append(ln)
        head = (f"overview  y={yy}   scale=1:{step}   "
                f"viewport x {vb.lo.x}..{vb.hi.x}  z {vb.lo.z}..{vb.hi.z}"
                f"（行首 > 为视口内）")
        return head + "\n" + "\n".join(out)

    def _legend_text(self, cmap: Dict[str, str], overlay: Optional[str]) -> str:
        if overlay == "facing":
            return "^ -z(N)   v +z(S)   > +x(E)   < -x(W)   . 无朝向"
        if not cmap:
            return "（空）"
        return "   ".join(f"{c} {k.split(':')[-1]}" for k, c in sorted(cmap.items(), key=lambda kv: kv[1]))

    # ---------------------------------------------------------------- 剖面
    def section(self, axis: str = "z", at: int = 0, bx=None, step: int = 1) -> str:
        b = self.w.bounds()
        if b is None:
            return "(空世界)"
        axis = axis.lower()
        if axis == "y":
            return self.slice(at, bx, step=step)
        bx = box(bx) if bx is not None else b
        at = int(at)
        if axis == "z":
            lo, hi = V(bx.lo.x, bx.lo.y, at), V(bx.hi.x, bx.hi.y, at)
            col_range = range(bx.lo.x, bx.hi.x + 1)
            col_name = "x"
        elif axis == "x":
            lo, hi = V(at, bx.lo.y, bx.lo.z), V(at, bx.hi.y, bx.hi.z)
            col_range = range(bx.lo.z, bx.hi.z + 1)
            col_name = "z"
        else:
            raise ValueError("axis 只能是 x / y / z")

        w = len(col_range)
        h = hi.y - lo.y + 1
        step = self._auto_step(w, h, step)
        cols = list(col_range)[::step]
        ys = list(range(hi.y, lo.y - 1, -step))
        yw = max(len(str(lo.y)), len(str(hi.y)), 1)
        indent = yw + 4

        keys = []
        cmap = {}
        rows = []
        for y in ys:
            row = []
            for c in cols:
                p = V(c, y, at) if axis == "z" else V(at, y, c)
                blk = self.w.get(p)
                if not blk.is_air:
                    keys.append(blk.key())
                row.append(blk)
            rows.append((y, row))
        cmap = _assign_chars(sorted(set(keys)))

        head = (f"section axis={axis} at={at}   {col_name}:{cols[0]}..{cols[-1]}  "
                f"y:{lo.y}..{hi.y}"
                + (f"   scale=1:{step}" if step > 1 else ""))
        labels = [str(c) if i % 5 == 0 else None for i, c in enumerate(cols)]
        lines = [head, _ruler(len(cols), indent, labels)]
        for y, row in rows:
            lines.append(f"y={y:0{yw}d} |" + "".join(
                "." if blk.is_air else cmap.get(blk.key(), "?") for blk in row))
        lines.append("")
        lines.append(self._legend_text(cmap, None))
        return "\n".join(lines)

    # ---------------------------------------------------------------- 单列
    def column(self, x: int, z: int) -> str:
        b = self.w.bounds()
        if b is None:
            return "(空世界)"
        lines = [f"column x={x} z={z}   y:{b.lo.y}..{b.hi.y}"]
        for y in range(b.hi.y, b.lo.y - 1, -1):
            blk = self.w.get(V(int(x), y, int(z)))
            lines.append(f"y={y:03d} | {'air' if blk.is_air else blk.short()}")
        return "\n".join(lines)

    # ---------------------------------------------------------------- diff
    def diff(self, step: int = 1) -> str:
        """只画相对基线的改动。"""
        base = self.w._baseline
        cur = self.w.cells
        changed = {}
        for p, b in cur.items():
            if base.get(p, AIR) != b:
                changed[p] = ("~" if p in base else "+")
        for p, b in base.items():
            if p not in cur and not b.is_air:
                changed[p] = "-"
        if not changed:
            return "diff   （无改动）"
        xs = [p.x for p in changed]
        ys = [p.y for p in changed]
        zs = [p.z for p in changed]
        bx = box(V(min(xs), min(ys), min(zs)), V(max(xs), max(ys), max(zs)))

        y_levels = sorted({p.y for p in changed})
        lines = [f"diff   +{sum(1 for v in changed.values() if v == '+')} "
                 f"-{sum(1 for v in changed.values() if v == '-')} "
                 f"~{sum(1 for v in changed.values() if v == '~')}"
                 f"     dirty box {bx.lo}..{bx.hi}   y={y_levels}"]
        for y in y_levels:
            zw = max(len(str(bx.lo.z)), len(str(bx.hi.z)), 1)
            indent = zw + 4
            cols = list(range(bx.lo.x, bx.hi.x + 1, step))
            rows = list(range(bx.lo.z, bx.hi.z + 1, step))
            if (len(cols) * len(rows)) > self.max_cells:
                lines.append(f"  y={y}: 改动区域过大，已省略（用 step 或 budget 调整）")
                continue
            labels = [str(c) if i % 5 == 0 else None for i, c in enumerate(cols)]
            lines.append(f"  y={y}")
            lines.append(_ruler(len(cols), indent + 2, labels))
            for z in rows:
                ch = []
                for x in cols:
                    p = V(x, y, z)
                    ch.append(changed.get(p, "." if not self.w.get(p).is_air else " "))
                lines.append("  " + f"z={z:0{zw}d} |" + "".join(ch))
        lines.append("")
        lines.append("+ 新增   - 移除   ~ 替换")
        return "\n".join(lines)

    # ---------------------------------------------------------------- 统计
    def summary(self) -> str:
        b = self.w.bounds()
        lines = ["summary"]
        if b is None:
            lines.append("  （空世界）")
            return "\n".join(lines)
        s = b.size
        lines.append(f"  bounds   {b.lo}..{b.hi}    {s.x} x {s.y} x {s.z}")
        lines.append(f"  blocks   {len(self.w.cells)} occupied / "
                     f"{b.volume() - len(self.w.cells)} air in bounds")
        hist = self.w.query.histogram(6)
        if hist:
            lines.append("  top      " + "   ".join(f"{k.split(':')[-1]} {v}" for k, v in hist))
        if self.w.marks.points or self.w.marks.boxes:
            pts = "   ".join(f"{k} {v}" for k, v in self.w.marks.points.items())
            boxes = "   ".join(f"{k} {v}" for k, v in self.w.marks.boxes.items())
            if pts:
                lines.append("  marks    " + pts)
            if boxes:
                lines.append("  regions  " + boxes)
        d = self.w.dirty_box()
        if d:
            lines.append(f"  dirty    {d.lo}..{d.hi}")
        return "\n".join(lines)

    def legend(self) -> str:
        """当前世界全部方块类型的字符表。"""
        keys = sorted({b.key() for b in self.w.cells.values()})
        cmap = _assign_chars(keys)
        return self._legend_text(cmap, None)

    # ---------------------------------------------------------------- 等距视图
    def iso(self, bx=None, step: int = 1) -> str:
        """等距投影（2:1）。

        step>1 时水平降采样（每 step 格取 1 格），大建筑务必开，
        否则 25x25 的平面会输出近 100 列 x 60 行，token 直接爆掉。
        """
        b = self.w.bounds()
        if b is None:
            return "(空世界)"
        bx = box(bx) if bx is not None else b
        step = max(1, int(step))
        cells = []
        for p in bx:
            if (p.x - bx.lo.x) % step or (p.z - bx.lo.z) % step:
                continue
            blk = self.w.get(p)
            if not blk.is_air:
                cells.append((p, blk))
        if not cells:
            return "(空区域)"
        keys = sorted({blk.key() for _, blk in cells})
        cmap = _assign_chars(keys)

        proj = []
        minc = minr = 10 ** 9
        maxc = maxr = -10 ** 9
        tmp = []
        for p, blk in cells:
            c = 2 * (p.x - p.z)
            r = (p.x + p.z) + 2 * (bx.hi.y - p.y)
            tmp.append((c, r, p, blk))
            minc, maxc = min(minc, c), max(maxc, c)
            minr, maxr = min(minr, r), max(maxr, r)
        # 深度排序：远的先画
        tmp.sort(key=lambda t: (t[2].x + t[2].z, t[2].y))
        canvas: Dict[tuple, str] = {}
        for c, r, p, blk in tmp:
            canvas[(r - minr, c - minc)] = cmap.get(blk.key(), "?")
        lines = [f"iso   {bx.lo}..{bx.hi}   （上=远，下=近）"
                 + (f"   scale=1:{step}" if step > 1 else "")]
        for rr in range(maxr - minr + 1):
            lines.append("".join(canvas.get((rr, cc), " ") for cc in range(maxc - minc + 1)))
        lines.append("")
        lines.append(self._legend_text(cmap, None))
        return "\n".join(lines)
