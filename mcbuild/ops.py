"""形状原语与变换算符。

所有原语都接受一个 target（World 或 Frame），只调用 target.set / target.fill /
target._tx，因此天然支持在局部坐标系里构建。
"""

from __future__ import annotations

import math
from typing import Iterable, List, Sequence

from .block import (AIR, Fam, STAIRS_UPHILL, Block, classify, make,
                    mirror_block, rotate_block)
from .vec import (CARDINAL_VEC, Box, V, box, mirror_cardinal, norm_yaw,
                  rot_y, rotate_axis, rotate_cardinal)

_OPPOSITE = {"north": "south", "south": "north", "east": "west", "west": "east"}


def _vec_to_cardinal(v: V) -> str:
    for name, d in CARDINAL_VEC.items():
        if (v.x, v.y, v.z) == (d.x, d.y, d.z):
            return name
    raise ValueError(f"不是单位水平方向: {v}")


def _dirvec(direction, target=None) -> V:
    if isinstance(direction, str):
        d = CARDINAL_VEC.get(direction.lower())
        if d is None:
            raise ValueError(f"未知方向: {direction}")
        return d
    return V(int(direction[0]), int(direction[1]), int(direction[2]))


def _blk(target, block, state: dict) -> Block:
    """在 target 的坐标系下把 (id, kwargs) 解析成 Block。"""
    if isinstance(block, Block):
        return rotate_block(block, getattr(target, "yaw", 0))
    return make(block, yaw=getattr(target, "yaw", 0), **state)


# ---------------------------------------------------------------- 基础

def line(target, a, b, block, **state) -> int:
    """3D Bresenham 直线。返回写入格数。"""
    a = V(int(a[0]), int(a[1]), int(a[2]))
    b = V(int(b[0]), int(b[1]), int(b[2]))
    blk = _blk(target, block, state)
    n = 0
    with target._tx("line", a=repr(a), b=repr(b), block=blk.key()):
        for p in _bresenham3(a, b):
            target.set(p, blk)
            n += 1
    return n


def _bresenham3(a: V, b: V):
    x0, y0, z0 = a
    x1, y1, z1 = b
    dx, dy, dz = abs(x1 - x0), abs(y1 - y0), abs(z1 - z0)
    sx = 1 if x1 >= x0 else -1
    sy = 1 if y1 >= y0 else -1
    sz = 1 if z1 >= z0 else -1
    if dx >= dy and dx >= dz:
        p1, p2 = 2 * dy - dx, 2 * dz - dx
        while x0 != x1:
            yield V(x0, y0, z0)
            if p1 >= 0:
                y0 += sy
                p1 -= 2 * dx
            if p2 >= 0:
                z0 += sz
                p2 -= 2 * dx
            p1 += 2 * dy
            p2 += 2 * dz
            x0 += sx
    elif dy >= dx and dy >= dz:
        p1, p2 = 2 * dx - dy, 2 * dz - dy
        while y0 != y1:
            yield V(x0, y0, z0)
            if p1 >= 0:
                x0 += sx
                p1 -= 2 * dy
            if p2 >= 0:
                z0 += sz
                p2 -= 2 * dy
            p1 += 2 * dx
            p2 += 2 * dz
            y0 += sy
    else:
        p1, p2 = 2 * dy - dz, 2 * dx - dz
        while z0 != z1:
            yield V(x0, y0, z0)
            if p1 >= 0:
                y0 += sy
                p1 -= 2 * dz
            if p2 >= 0:
                x0 += sx
                p2 -= 2 * dz
            p1 += 2 * dy
            p2 += 2 * dx
            z0 += sz
    yield V(x0, y0, z0)


def floor(target, bx, block, **state) -> int:
    """铺底面。"""
    bx = box(bx)
    return target.fill(box((bx.lo.x, bx.lo.y, bx.lo.z), (bx.hi.x, bx.lo.y, bx.hi.z)), block, **state)


def ceiling(target, bx, block, **state) -> int:
    """铺顶面。"""
    bx = box(bx)
    return target.fill(box((bx.lo.x, bx.hi.y, bx.lo.z), (bx.hi.x, bx.hi.y, bx.hi.z)), block, **state)


def wall(target, bx, block, thickness: int = 1, skip: Sequence[str] = ()) -> int:
    """四面墙。skip 可写 ('n','s','e','w') 去掉某面。"""
    bx = box(bx)
    skip = {s.lower() for s in skip}
    t = max(1, int(thickness))
    n = 0
    with target._tx("wall", box=repr(bx), block=block, thickness=t):
        if "n" not in skip:
            n += target.fill(box((bx.lo.x, bx.lo.y, bx.lo.z),
                                 (bx.hi.x, bx.hi.y, bx.lo.z + t - 1)), block)
        if "s" not in skip:
            n += target.fill(box((bx.lo.x, bx.lo.y, bx.hi.z - t + 1),
                                 (bx.hi.x, bx.hi.y, bx.hi.z)), block)
        if "w" not in skip:
            n += target.fill(box((bx.lo.x, bx.lo.y, bx.lo.z),
                                 (bx.lo.x + t - 1, bx.hi.y, bx.hi.z)), block)
        if "e" not in skip:
            n += target.fill(box((bx.hi.x - t + 1, bx.lo.y, bx.lo.z),
                                 (bx.hi.x, bx.hi.y, bx.hi.z)), block)
    return n


def hollow_box(target, bx, block, **state) -> int:
    """只写壳体。"""
    bx = box(bx)
    n = 0
    with target._tx("hollow_box", box=repr(bx), block=block):
        for p in bx:
            if (p.x in (bx.lo.x, bx.hi.x) or p.y in (bx.lo.y, bx.hi.y)
                    or p.z in (bx.lo.z, bx.hi.z)):
                target.set(p, _blk(target, block, state))
                n += 1
    return n


def pillar(target, pos, height: int, block, **state) -> int:
    """立柱，从 pos 向上 height 格。"""
    p = V(int(pos[0]), int(pos[1]), int(pos[2]))
    return target.fill(box(p, (p.x, p.y + height - 1, p.z)), block, **state)


# ---------------------------------------------------------------- 圆 / 球 / 顶

def disc_xz(center, r) -> List[V]:
    """水平圆盘（实心）的格子集合。"""
    c = V(int(center[0]), int(center[1]), int(center[2]))
    r = float(r)
    out = []
    lim = int(math.floor(r)) + 1
    for dx in range(-lim, lim + 1):
        for dz in range(-lim, lim + 1):
            if dx * dx + dz * dz <= r * r + 1e-9:
                out.append(V(c.x + dx, c.y, c.z + dz))
    return out


def circle_xz(center, r) -> List[V]:
    """水平圆环（只有边缘）的格子集合。"""
    r = float(r)
    inner = set(disc_xz(center, r - 1)) if r >= 1 else set()
    return [p for p in disc_xz(center, r) if p not in inner]


def cylinder(target, center, r, height: int, block, hollow: bool = False, **state) -> int:
    c = V(int(center[0]), int(center[1]), int(center[2]))
    pts = circle_xz(c, r) if hollow else disc_xz(c, r)
    n = 0
    with target._tx("cylinder", center=repr(c), r=r, height=height):
        for p in pts:
            for dy in range(int(height)):
                target.set(V(p.x, c.y + dy, p.z), _blk(target, block, state))
                n += 1
    return n


def dome(target, center, r, block, hollow: bool = True, **state) -> int:
    c = V(int(center[0]), int(center[1]), int(center[2]))
    r = float(r)
    n = 0
    with target._tx("dome", center=repr(c), r=r):
        for dy in range(int(math.floor(r)) + 1):
            rr = math.sqrt(max(0.0, r * r - dy * dy))
            pts = circle_xz(V(c.x, c.y + dy, c.z), rr) if hollow else disc_xz(V(c.x, c.y + dy, c.z), rr)
            for p in pts:
                target.set(p, _blk(target, block, state))
                n += 1
    return n


def sphere(target, center, r, block, hollow: bool = True, **state) -> int:
    c = V(int(center[0]), int(center[1]), int(center[2]))
    r = float(r)
    n = 0
    lim = int(math.floor(r))
    with target._tx("sphere", center=repr(c), r=r):
        for dy in range(-lim, lim + 1):
            rr = math.sqrt(max(0.0, r * r - dy * dy))
            pts = circle_xz(V(c.x, c.y + dy, c.z), rr) if hollow else disc_xz(V(c.x, c.y + dy, c.z), rr)
            for p in pts:
                target.set(p, _blk(target, block, state))
                n += 1
    return n


# ---------------------------------------------------------------- 楼梯 / 屋顶

def stairs_run(target, start, direction, n: int, block="oak_stairs", **state) -> int:
    """直跑楼梯：每级前进一格、升高一格。"""
    d = _dirvec(direction)
    card = _vec_to_cardinal(d)
    facing = card if STAIRS_UPHILL else _OPPOSITE[card]
    st = dict(state)
    st.setdefault("facing", facing)
    if classify(resolve_id(block)) == Fam.STAIRS:
        st.setdefault("half", "bottom")
    p0 = V(int(start[0]), int(start[1]), int(start[2]))
    k = 0
    with target._tx("stairs_run", start=repr(p0), direction=card, n=n):
        for i in range(int(n)):
            target.set(p0 + d * i + V(0, i, 0), _blk(target, block, st))
            k += 1
    return k


def roof_gable(target, bx, block="oak_stairs", axis: str = "x", **state) -> int:
    """双坡屋顶。axis='x' 表示屋脊沿 X 延伸。"""
    bx = box(bx)
    axis = target.map_axis(axis)
    lo, hi = bx.lo, bx.hi
    n = 0
    with target._tx("roof_gable", box=repr(bx), block=block, axis=axis):
        rise = hi.y - lo.y
        if axis == "x":
            depth = hi.z - lo.z
            d_max = max(1.0, depth / 2.0)
            mid = (lo.z + hi.z) / 2.0
            for z in range(lo.z, hi.z + 1):
                de = min(z - lo.z, hi.z - z)
                y = lo.y + min(rise, int(round(de * rise / d_max)))
                st = dict(state)
                st.setdefault("facing", "south" if z <= mid else "north")
                st.setdefault("half", "bottom")
                n += target.fill(box((lo.x, y, z), (hi.x, y, z)), block, **st)
        else:
            depth = hi.x - lo.x
            d_max = max(1.0, depth / 2.0)
            mid = (lo.x + hi.x) / 2.0
            for x in range(lo.x, hi.x + 1):
                de = min(x - lo.x, hi.x - x)
                y = lo.y + min(rise, int(round(de * rise / d_max)))
                st = dict(state)
                st.setdefault("facing", "east" if x <= mid else "west")
                st.setdefault("half", "bottom")
                n += target.fill(box((x, y, lo.z), (x, y, hi.z)), block, **st)
    return n


def roof_pyramid(target, bx, block="oak_stairs", **state) -> int:
    """攒尖顶：四面向中心收拢。"""
    bx = box(bx)
    lo, hi = bx.lo, bx.hi
    cx = (lo.x + hi.x) / 2.0
    cz = (lo.z + hi.z) / 2.0
    rise = hi.y - lo.y
    d_max = max(1.0, min(hi.x - lo.x, hi.z - lo.z) / 2.0)
    n = 0
    with target._tx("roof_pyramid", box=repr(bx), block=block):
        for x in range(lo.x, hi.x + 1):
            for z in range(lo.z, hi.z + 1):
                d = min(x - lo.x, hi.x - x, z - lo.z, hi.z - z)
                y = lo.y + min(rise, int(round(d * rise / d_max)))
                dx, dz = cx - x, cz - z
                facing = ("east" if dx > 0 else "west") if abs(dx) >= abs(dz) else \
                         ("south" if dz > 0 else "north")
                st = dict(state)
                st.setdefault("facing", facing)
                st.setdefault("half", "bottom")
                target.set(V(x, y, z), _blk(target, block, st))
                n += 1
    return n


def spiral_stairs(target, center, r: int, turns: int, block="oak_stairs", **state) -> int:
    """螺旋楼梯，逆时针上升。"""
    c = V(int(center[0]), int(center[1]), int(center[2]))
    r = int(r)
    n = 0
    with target._tx("spiral_stairs", center=repr(c), r=r, turns=turns):
        y = c.y
        for i in range(int(turns) * 4 * r):
            ang = 2 * math.pi * i / max(1, 4 * r)
            x = c.x + int(round(r * math.cos(ang)))
            z = c.z + int(round(r * math.sin(ang)))
            nxt = 2 * math.pi * (i + 1) / max(1, 4 * r)
            nx = c.x + int(round(r * math.cos(nxt)))
            nz = c.z + int(round(r * math.sin(nxt)))
            dx, dz = nx - x, nz - z
            facing = ("east" if dx > 0 else "west") if abs(dx) >= abs(dz) else \
                     ("south" if dz > 0 else "north")
            st = dict(state)
            st.setdefault("facing", facing)
            st.setdefault("half", "bottom")
            target.set(V(x, y, z), _blk(target, block, st))
            n += 1
            y += 1
    return n


def arch(target, bx, block, axis: str = "z", **state) -> int:
    """拱门：在 bx 内挖出一个拱形开口（写入拱形轮廓）。"""
    bx = box(bx)
    axis = target.map_axis(axis)
    lo, hi = bx.lo, bx.hi
    n = 0
    with target._tx("arch", box=repr(bx), block=block, axis=axis):
        if axis == "z":
            for y in range(lo.y, hi.y + 1):
                t = (y - lo.y) / max(1, (hi.y - lo.y))
                half = (hi.x - lo.x) / 2.0 * math.sqrt(max(0.0, 1 - t * t))
                for x in range(lo.x, hi.x + 1):
                    if abs((x - (lo.x + hi.x) / 2.0)) >= half - 0.5:
                        for z in (lo.z, hi.z):
                            target.set(V(x, y, z), _blk(target, block, state))
                            n += 1
        else:
            for y in range(lo.y, hi.y + 1):
                t = (y - lo.y) / max(1, (hi.y - lo.y))
                half = (hi.z - lo.z) / 2.0 * math.sqrt(max(0.0, 1 - t * t))
                for z in range(lo.z, hi.z + 1):
                    if abs((z - (lo.z + hi.z) / 2.0)) >= half - 0.5:
                        for x in (lo.x, hi.x):
                            target.set(V(x, y, z), _blk(target, block, state))
                            n += 1
    return n


# ---------------------------------------------------------------- 中式屋面 / 装饰

def hip_roof(target, bx, block="oak_stairs", axis: str = "x", inset=None, **state) -> int:
    """四坡顶（庑殿顶）。axis 为屋脊延伸方向，inset 为屋脊端部相对檐口的缩进格数。

    高度场取两个方向坡度中「较陡」的一个（即 y 取较小值），
    因此端部自然形成梯形坡面，屋脊为一条线段而非一个点。
    """
    bx = box(bx)
    axis = target.map_axis(axis)
    lo, hi = bx.lo, bx.hi
    rise = hi.y - lo.y
    n = 0
    with target._tx("hip_roof", box=repr(bx), block=block, axis=axis, inset=inset):
        if axis == "x":
            half_z = max(1.0, (hi.z - lo.z) / 2.0)
            ins = float(inset) if inset is not None else float(min((hi.x - lo.x) // 2, int(half_z)))
            ins = max(1.0, ins)
            cz = (lo.z + hi.z) / 2.0
            x0, x1 = lo.x + ins, hi.x - ins
            for x in range(lo.x, hi.x + 1):
                ax = max(0.0, x0 - x, x - x1)
                for z in range(lo.z, hi.z + 1):
                    tz = abs(z - cz) / half_z
                    tx = ax / ins
                    y = max(lo.y, hi.y - int(round(max(tz, tx) * rise)))
                    st = dict(state)
                    st.setdefault("half", "bottom")
                    if tz >= tx:
                        st.setdefault("facing", "south" if z <= cz else "north")
                    else:
                        st.setdefault("facing", "east" if x < x0 else "west")
                    target.set(V(x, y, z), _blk(target, block, st))
                    n += 1
        else:
            half_x = max(1.0, (hi.x - lo.x) / 2.0)
            ins = float(inset) if inset is not None else float(min((hi.z - lo.z) // 2, int(half_x)))
            ins = max(1.0, ins)
            cx = (lo.x + hi.x) / 2.0
            z0, z1 = lo.z + ins, hi.z - ins
            for z in range(lo.z, hi.z + 1):
                az = max(0.0, z0 - z, z - z1)
                for x in range(lo.x, hi.x + 1):
                    tx = abs(x - cx) / half_x
                    tz = az / ins
                    y = max(lo.y, hi.y - int(round(max(tx, tz) * rise)))
                    st = dict(state)
                    st.setdefault("half", "bottom")
                    if tx >= tz:
                        st.setdefault("facing", "east" if x <= cx else "west")
                    else:
                        st.setdefault("facing", "south" if z < z0 else "north")
                    target.set(V(x, y, z), _blk(target, block, st))
                    n += 1
    return n


def eave_ring(target, bx, block, depth: int = 1, y=None, **state) -> int:
    """环绕挑檐：沿 box 外沿向外挑出 depth 格的一圈，facing 指向外侧。

    默认 half=top（檐口下沿），主体范围内的格子不写（由墙体占据）。
    """
    bx = box(bx)
    lo, hi = bx.lo, bx.hi
    yy = bx.lo.y if y is None else int(y)
    d = max(0, int(depth))
    cx, cz = (lo.x + hi.x) / 2.0, (lo.z + hi.z) / 2.0
    n = 0
    with target._tx("eave_ring", box=repr(bx), block=block, depth=d):
        for x in range(lo.x - d, hi.x + d + 1):
            for z in range(lo.z - d, hi.z + d + 1):
                if lo.x <= x <= hi.x and lo.z <= z <= hi.z:
                    continue
                st = dict(state)
                st.setdefault("half", "top")
                if abs(x - cx) >= abs(z - cz):
                    st.setdefault("facing", "east" if x > cx else "west")
                else:
                    st.setdefault("facing", "south" if z > cz else "north")
                target.set(V(x, yy, z), _blk(target, block, st))
                n += 1
    return n


def railing(target, bx, block, rail_block=None, spacing: int = 3, height: int = 2, **state) -> int:
    """沿 box 底部水平外环做栏杆：转角与对称位置立望柱，其余为地栿 + 寻杖。

    柱位以**每条边的中点对称**分布（min(idx, L-1-idx) % spacing），
    直接从端点起算会在奇数长度边上产生不对称 —— compare.symmetry 会抓出来。
    """
    bx = box(bx)
    lo, hi, y = bx.lo, bx.hi, bx.lo.y
    rail = rail_block or block
    h = max(1, int(height))
    sp = max(1, int(spacing))
    n = 0
    with target._tx("railing", box=repr(bx), block=block, spacing=sp, height=h):
        for x in range(lo.x, hi.x + 1):
            for z in range(lo.z, hi.z + 1):
                if not (x in (lo.x, hi.x) or z in (lo.z, hi.z)):
                    continue
                corner = (x in (lo.x, hi.x)) and (z in (lo.z, hi.z))
                if x in (lo.x, hi.x):
                    idx, L = z - lo.z, hi.z - lo.z + 1
                else:
                    idx, L = x - lo.x, hi.x - lo.x + 1
                post = corner or min(idx, L - 1 - idx) % sp == 0
                if post:
                    for dy in range(h):
                        target.set(V(x, y + dy, z), _blk(target, block, state))
                        n += 1
                else:
                    target.set(V(x, y, z), _blk(target, rail, state))
                    n += 1
                    if h > 1:
                        target.set(V(x, y + h - 1, z), _blk(target, rail, state))
                        n += 1
    return n


# ---------------------------------------------------------------- 区域变换

def _mirror_pos(p: V, axis: str, pivot: float) -> V:
    if axis == "x":
        return p.replace(x=int(round(2 * pivot - p.x)))
    if axis == "z":
        return p.replace(z=int(round(2 * pivot - p.z)))
    return p.replace(y=int(round(2 * pivot - p.y)))


def mirror(target, bx, axis: str = "x", pivot=None) -> int:
    """镜像区域（含朝向翻转）。pivot 为镜面坐标，默认取区域中线。"""
    bx = box(bx)
    if pivot is None:
        pivot = (bx.lo.x + bx.hi.x) / 2 if axis == "x" else \
                ((bx.lo.z + bx.hi.z) / 2 if axis == "z" else (bx.lo.y + bx.hi.y) / 2)
    cells = [(p, target.get(p)) for p in bx]
    n = 0
    with target._tx("mirror", box=repr(bx), axis=axis, pivot=pivot):
        for p, _ in cells:
            target.set(p, AIR)
        for p, b in cells:
            if b.is_air:
                continue
            target.set(_mirror_pos(p, axis, pivot), mirror_block(b, axis))
            n += 1
    return n


def rotate_area(target, bx, yaw: int = 90, pivot=None) -> int:
    """就地旋转区域（含朝向重映射）。"""
    bx = box(bx)
    yaw = norm_yaw(yaw)
    if pivot is None:
        pivot = V((bx.lo.x + bx.hi.x) // 2, bx.lo.y, (bx.lo.z + bx.hi.z) // 2)
    else:
        pivot = V(int(pivot[0]), int(pivot[1]), int(pivot[2]))
    cells = [(p, target.get(p)) for p in bx]
    n = 0
    with target._tx("rotate_area", box=repr(bx), yaw=yaw, pivot=repr(pivot)):
        for p, _ in cells:
            target.set(p, AIR)
        for p, b in cells:
            if b.is_air:
                continue
            q = rot_y(p - pivot, yaw) + pivot
            target.set(q, rotate_block(b, yaw))
            n += 1
    return n


def translate_area(target, bx, delta) -> int:
    """移动区域。"""
    bx = box(bx)
    d = V(int(delta[0]), int(delta[1]), int(delta[2]))
    cells = [(p, target.get(p)) for p in bx]
    n = 0
    with target._tx("translate_area", box=repr(bx), delta=repr(d)):
        for p, _ in cells:
            target.set(p, AIR)
        for p, b in cells:
            if b.is_air:
                continue
            target.set(p + d, b)
            n += 1
    return n


def repeat(target, bx, step, n: int) -> int:
    """沿 step 方向复制 n 份（不含原始）。"""
    bx = box(bx)
    s = V(int(step[0]), int(step[1]), int(step[2]))
    cells = [(p, target.get(p)) for p in bx if not target.get(p).is_air]
    k = 0
    with target._tx("repeat", box=repr(bx), step=repr(s), n=n):
        for i in range(1, int(n) + 1):
            off = s * i
            for p, b in cells:
                target.set(p + off, b)
                k += 1
    return k


def stack(target, bx, dy: int, n: int) -> int:
    """垂直堆叠 n 层（楼层复用）。"""
    return repeat(target, bx, V(0, int(dy), 0), int(n))


def resolve_id(block) -> str:
    """取方块 id（供内部判断方块族）。"""
    from .block import resolve_alias
    if isinstance(block, Block):
        return block.id
    return resolve_alias(str(block))


# ---------------------------------------------------------------- Mixin

class OpsMixin:
    """把原语挂成 World / Frame 的方法。"""

    def line(self, a, b, block, **state): return line(self, a, b, block, **state)
    def floor(self, bx, block, **state): return floor(self, bx, block, **state)
    def ceiling(self, bx, block, **state): return ceiling(self, bx, block, **state)
    def wall(self, bx, block, thickness=1, skip=()): return wall(self, bx, block, thickness, skip)
    def hollow_box(self, bx, block, **state): return hollow_box(self, bx, block, **state)
    def pillar(self, pos, height, block, **state): return pillar(self, pos, height, block, **state)
    def cylinder(self, center, r, height, block, hollow=False, **state):
        return cylinder(self, center, r, height, block, hollow, **state)
    def dome(self, center, r, block, hollow=True, **state):
        return dome(self, center, r, block, hollow, **state)
    def sphere(self, center, r, block, hollow=True, **state):
        return sphere(self, center, r, block, hollow, **state)
    def stairs_run(self, start, direction, n, block="oak_stairs", **state):
        return stairs_run(self, start, direction, n, block, **state)
    def roof_gable(self, bx, block="oak_stairs", axis="x", **state):
        return roof_gable(self, bx, block, axis, **state)
    def roof_pyramid(self, bx, block="oak_stairs", **state):
        return roof_pyramid(self, bx, block, **state)
    def spiral_stairs(self, center, r, turns, block="oak_stairs", **state):
        return spiral_stairs(self, center, r, turns, block, **state)
    def arch(self, bx, block, axis="z", **state):
        return arch(self, bx, block, axis, **state)
    def hip_roof(self, bx, block="oak_stairs", axis="x", inset=None, **state):
        return hip_roof(self, bx, block, axis, inset, **state)
    def eave_ring(self, bx, block, depth=1, y=None, **state):
        return eave_ring(self, bx, block, depth, y, **state)
    def railing(self, bx, block, rail_block=None, spacing=3, height=2, **state):
        return railing(self, bx, block, rail_block, spacing, height, **state)
    def mirror(self, bx, axis="x", pivot=None): return mirror(self, bx, axis, pivot)
    def rotate_area(self, bx, yaw=90, pivot=None): return rotate_area(self, bx, yaw, pivot)
    def translate_area(self, bx, delta): return translate_area(self, bx, delta)
    def repeat(self, bx, step, n): return repeat(self, bx, step, n)
    def stack(self, bx, dy, n): return stack(self, bx, dy, n)
