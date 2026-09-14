#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 务必先阅读同目录下README.txt!!!
"""云海浮阁 —— mcbuild 大型场景示例（只调用库 API，不改库代码）。

主题：漂浮在云海上的东方楼阁
--------------------------------------------------------------------
    云海之上悬一座分台地浮岛；岛心起 21×21 月台，
    月台上立三层重檐楼阁（面阔 15 → 11 → 7）：腰檐逐层收进、
    逐层收进的攒尖顶 + 宝顶；前 (+Z) 设大踏道下岛、断桥探入云海，
    台上左右对称列两座四角攒尖亭，后 (-Z) 以露道接后轩（庑殿顶）；
    岛缘植松、缀朱樱、散置山石，檐角 / 栏柱 / 桥头挂灯。

主轴沿 Z，关于 x=0 严格镜像 —— 所有噪声函数一律取 |x|，
所以整场（含云海、植被）都能用 compare.symmetry(axis="x") 当验收标准。

关键标高
    岛心 64 · 中台 61 · 下台 58 · 岛底锥尖 44 · 云海面 52..58 · 远景浮石 57
    月台 65..67（外铺散水两圈）
    主阁  一层地坪 67 / 墙 68..72 / 额枋 73 / 斗拱 74 / 腰檐 75..79
          二层平坐 80 / 墙 81..85 / 额枋 86 / 斗拱 87 / 腰檐 88..92
          三层平坐 93 / 墙 94..98 / 额枋 99 / 斗拱 100 / 攒尖 101..107
          宝顶 108..110（整场最高点）
    配亭  台基 62..64 / 地坪 65 / 柱 66..71 / 檐 74..79 / 宝顶 80..82
    后轩  台面 67 / 墙 68..71 / 庑殿 74..76 / 正脊 77
    观景台 64..67 · 断桥 64..67 · 露道 67

材质配色（青绿瓦 + 白粉墙 + 深色木构 + 朱红栏 + 金饰 + 樱粉）
    主阁瓦 prismarine_stairs / 戗脊与檐口 dark_prismarine*（明亮→主体）
    配亭瓦 dark_prismarine_stairs / 戗脊 prismarine（压深→次级，拉开主次层级）
    墙 white_concrete / 木 dark_oak_* / 栏 crimson_planks + crimson_fence
    石 stone_bricks 系 / 饰面 gold_block + sea_lantern
    云 white_wool + white_concrete + snow_block + light_gray_concrete + 白玻璃

用到的库能力
    stage 分步 · component 组件（pingzuo / ting）· Frame 局部坐标与相对朝向
    中式原语 hip_roof / eave_ring / railing · 形状原语 fill/pillar/stairs_run
    compare.symmetry 自查 · render.slice/section/view/overview · lint · 导出 schem/json

运行： python examples/cloud_pavilion.py
"""

from __future__ import annotations

import math
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcbuild import Block, World, box, make              # noqa: E402

# ============================================================ 材质表

STONE = "stone_bricks"
STONE_T = "chiseled_stone_bricks"
STONE_S = "stone_bricks_stairs"
STONE_W = "stone_bricks_wall"
MOSSY = "mossy_cobblestone"
COB = "cobblestone"

WOOD = "dark_oak_planks"
LOGG = "dark_oak_log"
WOOD_S = "dark_oak_stairs"
WOOD_SLAB = "dark_oak_slab"
WOOD_F = "dark_oak_fence"
DOOR = "dark_oak_door"
RED = "crimson_planks"
RED_F = "crimson_fence"

WALL = "white_concrete"
GLASS = "glass_pane"

TILE = "prismarine_stairs"          # 主阁青绿琉璃瓦
TILE_R = "dark_prismarine"          # 主阁戗脊 / 正脊
TILE_E = "dark_prismarine_stairs"   # 主阁檐口滴水
TILE2 = "dark_prismarine_stairs"    # 次级屋面（亭）：深青瓦，与主阁拉开层级
TILE2_R = "prismarine"              # 次级戗脊：浅色反衬

GOLD = "gold_block"
PEARL = "sea_lantern"
CHAIN = "chain"

GRASS = "grass_block"
MOSS = "moss_block"
MOSS_C = "moss_carpet"
DIRT = "dirt"

CL_TOP = "white_wool"
CL_MID = "white_concrete"
CL_HI = "snow_block"
CL_BOT = "light_gray_concrete"
CL_WISP = "white_stained_glass"

PINE = "spruce_leaves"
PINE_L = "spruce_log"
SAKURA = "cherry_leaves"
SAKURA_L = "cherry_log"
PETAL = "pink_petals"

# 悬挂灯笼：库的方块族表把 lantern 归入 solid（无属性），
# 因此直接构造 Block 写 hanging=true —— 导出后游戏内不会掉落，也不再触发 W1。
LAMP_H = Block("minecraft:lantern", (("hanging", "true"),))

# ============================================================ 标高 / 半径

Y_G = 64
R_PLATEAU = 20
R_MID = 24
R_EDGE = 27
Y_MID = 61
Y_EDGE = 58
Y_BOT = 44

CLOUD_R = 56
Y_TERRACE = 67

# 主阁：(墙半宽, 地坪, 额枋, 斗拱, 腰檐外半径, 腰檐层数, 平坐半径)
PAV1 = (7, 67, 73, 74, 10, 5, 6)
PAV2 = (5, 80, 86, 87, 8, 5, 6)
Y3 = 93


# ============================================================ 确定性噪声

def h2(a, b, s=0) -> float:
    n = (int(a) * 374761393 + int(b) * 668265263 + int(s) * 2246822519) & 0xFFFFFFFF
    n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
    n ^= (n >> 16)
    return (n & 0xFFFF) / 65535.0


def _sm(t: float) -> float:
    return t * t * (3 - 2 * t)


def vnoise(x: float, z: float, s: int = 0) -> float:
    ix, iz = math.floor(x), math.floor(z)
    fx, fz = _sm(x - ix), _sm(z - iz)
    a = h2(ix, iz, s)
    b = h2(ix + 1, iz, s)
    c = h2(ix, iz + 1, s)
    d = h2(ix + 1, iz + 1, s)
    return (a * (1 - fx) + b * fx) * (1 - fz) + (c * (1 - fx) + d * fx) * fz


def fbm(x: float, z: float, s: int = 0, oct_: int = 4) -> float:
    tot, amp, fr, nrm = 0.0, 1.0, 1.0, 0.0
    for i in range(oct_):
        tot += amp * vnoise(x * fr, z * fr, s + i * 97)
        nrm += amp
        amp *= 0.5
        fr *= 2.0
    return tot / nrm


# ============================================================ 几何小工具

def ring_cells(cx: int, cz: int, r: int):
    """半径 r 的方环格子（max(|dx|,|dz|) == r）。"""
    if r <= 0:
        return [(cx, cz)]
    pts = set()
    for i in range(-r, r + 1):
        pts.add((cx + i, cz - r))
        pts.add((cx + i, cz + r))
        pts.add((cx - r, cz + i))
        pts.add((cx + r, cz + i))
    return sorted(pts)


def out_facing(dx: int, dz: int) -> str:
    """方环上某格朝外的方向（与库 eave_ring 同规则）。"""
    if abs(dx) >= abs(dz):
        return "east" if dx > 0 else "west"
    return "south" if dz > 0 else "north"


def ring_stairs(t, cx, cz, r, y, block, half="bottom"):
    for px, pz in ring_cells(cx, cz, r):
        t.set((px, y, pz), make(block, facing=out_facing(px - cx, pz - cz), half=half))


def roof_skirt(t, cx, cz, levels, deck_i=None, lip=True):
    """腰檐 / 屋面。levels 外→内 [(r, y)]。

    只在 deck_i 这层铺实心盘（天花 / 楼板），其余各层只写一圈朝外楼梯，
    于是屋面是"逐层收进的壳"，屋内不被填实；最外层再由库原语 eave_ring
    挑出一圈深色滴水。
    """
    if deck_i is None:
        deck_i = len(levels) - 1
    dr, dy = levels[deck_i]
    t.fill(box((cx - dr, dy, cz - dr), (cx + dr, dy, cz + dr)), TILE_R)
    for r, y in levels:
        ring_stairs(t, cx, cz, r, y, TILE)
    if lip:
        r0, y0 = levels[0]
        t.eave_ring(box((cx - r0, y0, cz - r0), (cx + r0, y0, cz + r0)),
                    TILE_E, depth=1)


def corner_lift(t, cx, cz, r, y, edge=TILE_E):
    """四角起翘：外圈檐角向外上挑一格。"""
    for sx in (-1, 1):
        for sz in (-1, 1):
            t.set((cx + sx * (r + 2), y + 1, cz + sz * (r + 2)),
                  make(edge, facing="east" if sx > 0 else "west", half="bottom"))


def crown(t, cx, cz, levels, deck_i=0, tile=TILE, ridge=TILE_R, edge=TILE_E):
    """攒尖顶：逐层收进，四角连成戗脊，顶端接宝顶。"""
    dr, dy = levels[deck_i]
    t.fill(box((cx - dr, dy, cz - dr), (cx + dr, dy, cz + dr)), ridge)
    for r, y in levels:
        for px, pz in ring_cells(cx, cz, r):
            if abs(px - cx) == r and abs(pz - cz) == r:
                t.set((px, y, pz), ridge)                     # 戗脊
            else:
                t.set((px, y, pz), make(tile, half="bottom",
                                        facing=out_facing(px - cx, pz - cz)))
    r0, y0 = levels[0]
    t.eave_ring(box((cx - r0, y0, cz - r0), (cx + r0, y0, cz + r0)), edge, depth=1)
    corner_lift(t, cx, cz, r0, y0, edge)
    ay = levels[-1][1]
    t.set((cx, ay + 1, cz), GOLD)
    t.set((cx, ay + 2, cz), PEARL)
    t.set((cx, ay + 3, cz), GOLD)


def cornice(t, cx, cz, half, y_ef, y_dg):
    """额枋 + 斗拱 + 挑檐垫板，全按半径在世界坐标里算，天然对称。"""
    for px, pz in ring_cells(cx, cz, half):
        t.set((px, y_ef, pz), WOOD)
    r = half + 1
    for px, pz in ring_cells(cx, cz, r):
        corner = abs(px - cx) == r and abs(pz - cz) == r
        if corner or (abs(px - cx) + abs(pz - cz)) % 2 == 0:
            t.set((px, y_dg, pz), LOGG)                        # 斗（角科用整木）
        else:
            t.set((px, y_dg, pz), make(WOOD_S, half="top",
                                       facing=out_facing(px - cx, pz - cz)))
    for px, pz in ring_cells(cx, cz, half + 2):
        t.set((px, y_dg, pz), make(WOOD_SLAB, half="top"))     # 挑檐垫板


def balustrade(t, x0, x1, z0, z1, y, post, rail, spacing=3, height=3, skip=()):
    """矩形栏干。柱位以每条边中点对称分布（mirror 后位置不变），支持留口。"""
    sk = set(skip)
    for x in range(x0, x1 + 1):
        for z in range(z0, z1 + 1):
            if not (x in (x0, x1) or z in (z0, z1)):
                continue
            if (x, z) in sk:
                continue
            corner = (x in (x0, x1)) and (z in (z0, z1))
            if z in (z0, z1):
                idx, L = x - x0, x1 - x0 + 1
            else:
                idx, L = z - z0, z1 - z0 + 1
            if corner or min(idx, L - 1 - idx) % spacing == 0:
                for dy in range(height):
                    t.set((x, y + dy, z), post)
            else:
                t.set((x, y, z), rail)
                if height > 1:
                    t.set((x, y + height - 1, z), rail)


def hang_lamp(t, x, y, z, drop=1):
    """自 (x,y,z) 向下挂灯：(x,y,z) 必须已有方块作支点。"""
    for i in range(1, drop + 1):
        t.set((x, y - i, z), CHAIN)
    t.set((x, y - drop - 1, z), LAMP_H)


def arm_lamp(t, x, y, z, dx, dz):
    """灯柱挑臂：(x,y,z) 是已有立柱的顶格，朝 (dx,dz) 挑出一格木臂，臂下挂灯。"""
    t.set((x + dx, y, z + dz), LOGG)
    hang_lamp(t, x + dx, y, z + dz, drop=1)


def surface_y(w: World, x: int, z: int, ymax: int = 80, ymin: int = 30):
    for y in range(ymax, ymin - 1, -1):
        if not w.get((x, y, z)).is_air:
            return y
    return None


# ------------------------------------------------------------ 立面 / 开间

_FACES = ("south", "north", "east", "west")


def side_pt(cx, cz, hx, hz, side, u, y):
    if side == "south":
        return (cx + u, y, cz + hz)
    if side == "north":
        return (cx + u, y, cz - hz)
    if side == "east":
        return (cx + hx, y, cz + u)
    return (cx - hx, y, cz + u)


def window_cells(u0, u1):
    """开间窗格：宽 ≥3 每隔一格出竖棂，宽 ≤2 整窗。"""
    w = u1 - u0 + 1
    if w <= 2:
        return [(u, "glass") for u in range(u0, u1 + 1)]
    return [(u, "beam" if min(u - u0, u1 - u) % 2 == 0 else "glass")
            for u in range(u0, u1 + 1)]


def storey(t, cx, cz, hx, hz, y0, h, posts_x, posts_z, door_side=None):
    """一层：四面墙 + 檐柱 + 开间门窗。

    posts_x / posts_z 是相对该面中心的**偏移**（南/北面沿 x，东/西面沿 z），
    这样矩形平面（如后轩）也能直接复用。
    door_side 那一面的居中开间做隔扇门（左右门扇 hinge 互补 + 中央隔心 + 亮窗），
    其余开间与其它三面做直棂窗 —— 镜像后完全一致。
    """
    for side in _FACES:
        if side in ("south", "north"):
            zz = cz + hz if side == "south" else cz - hz
            t.fill(box((cx - hx, y0 + 1, zz), (cx + hx, y0 + h, zz)), WALL)
            posts = posts_x
        else:
            xx = cx + hx if side == "east" else cx - hx
            t.fill(box((xx, y0 + 1, cz - hz), (xx, y0 + h, cz + hz)), WALL)
            posts = posts_z

        for u in posts:
            t.pillar(side_pt(cx, cz, hx, hz, side, u, y0 + 1), h, LOGG)

        for i in range(len(posts) - 1):
            a, b = posts[i], posts[i + 1]
            if b - a < 3:
                continue
            u0, u1 = a + 1, b - 1
            if door_side == side and (a + b) == 0:
                for u in range(u0, u1 + 1):
                    hinge = "left" if u < 0 else "right"
                    if u == 0:
                        for yy in (y0 + 1, y0 + 2):
                            t.set(side_pt(cx, cz, hx, hz, side, u, yy), GLASS)
                    else:
                        t.set(side_pt(cx, cz, hx, hz, side, u, y0 + 1),
                              make(DOOR, facing=side, half="lower", hinge=hinge))
                        t.set(side_pt(cx, cz, hx, hz, side, u, y0 + 2),
                              make(DOOR, facing=side, half="upper", hinge=hinge))
                    for yy in (y0 + 3, y0 + 4):                # 亮窗
                        t.set(side_pt(cx, cz, hx, hz, side, u, yy), GLASS)
                    t.set(side_pt(cx, cz, hx, hz, side, u, y0 + h), WOOD)
            else:
                for u, kind in window_cells(u0, u1):
                    blk = WOOD if kind == "beam" else GLASS
                    for yy in (y0 + 2, y0 + 3):                # 窗只占两行，其余留白墙
                        t.set(side_pt(cx, cz, hx, hz, side, u, yy), blk)
                for u in (u0, u1):                             # 窗楣一道木线
                    t.set(side_pt(cx, cz, hx, hz, side, u, y0 + h), WOOD)


# ============================================================ 组件

def pingzuo(t, r=6, mat=WOOD):
    """平坐：挑出的木楼板 + 朱红栏干（柱位由库的 railing 中点对称分布）。"""
    t.fill(box((-r, 0, -r), (r, 0, r)), mat)
    t.railing(box((-r, 1, -r), (r, 1, r)), RED, rail_block=RED_F, spacing=3, height=3)


def ting(t, h=6):
    """四角攒尖亭。原点 = 台基中心（岛面标高），局部 y=1 即地坪。

    台基 + 四角木柱 + 朱红栏（南面留口）+ 额枋斗拱 + 攒尖顶 + 宝顶 + 宫灯 + 踏跺。
    """
    t.fill(box((-4, -2, -4), (4, 0, 4)), STONE)                # 台基（下探两格）
    t.fill(box((-3, 1, -3), (3, 1, 3)), WOOD)                  # 地坪
    for px, pz in ring_cells(0, 0, 3):
        if abs(px) == 3 and abs(pz) == 3:
            t.set((px, 1, pz), STONE_T)                        # 台明角石
    balustrade(t, -3, 3, -3, 3, 2, RED, RED_F, spacing=3, height=3,
               skip={(u, 3) for u in (-1, 0, 1)})              # 南面留口
    for sx in (-3, 3):
        for sz in (-3, 3):
            t.pillar((sx, 2, sz), h, LOGG)                     # 四角柱压住栏干角
    for u in (-1, 0, 1):                                       # 踏跺
        t.set((u, 0, 5), make(STONE_S, facing="north", half="bottom"))
    y_ef = 2 + h
    for px, pz in ring_cells(0, 0, 3):
        t.set((px, y_ef, pz), WOOD)                            # 额枋
    for px, pz in ring_cells(0, 0, 4):
        if (abs(px) == 4 and abs(pz) == 4) or (abs(px) + abs(pz)) % 2 == 0:
            t.set((px, y_ef + 1, pz), LOGG)
        else:
            t.set((px, y_ef + 1, pz), make(WOOD_S, half="top",
                                           facing=out_facing(px, pz)))
    for px, pz in ring_cells(0, 0, 5):
        t.set((px, y_ef + 1, pz), make(WOOD_SLAB, half="top"))
    lv = [(5 - i, y_ef + 2 + i) for i in range(6)]
    crown(t, 0, 0, lv, deck_i=2, tile=TILE2, ridge=TILE2_R,
          edge=TILE2)                                          # 天花在 r=3 那层
    hang_lamp(t, 0, y_ef + 4, 0, drop=1)                       # 宫灯


# ============================================================ 1. 浮岛

def _island_top(rj: float) -> int:
    if rj <= R_PLATEAU:
        return Y_G
    if rj <= R_MID:
        return Y_MID
    return Y_EDGE


def _island_r(x, z) -> float:
    return math.hypot(x, z) + (fbm(abs(x) * 0.3, z * 0.3, 7, 3) - 0.5) * 2.6


def build_island(w: World) -> None:
    with w._tx("island"):
        for x in range(-R_EDGE - 1, R_EDGE + 2):
            for z in range(-R_EDGE - 1, R_EDGE + 2):
                rj = _island_r(x, z)
                if rj > R_EDGE + 0.4:
                    continue
                top = _island_top(rj)
                bot = min(top - 1, Y_BOT + int(round(rj * 0.62)))
                for y in range(bot, top + 1):
                    n2 = fbm(abs(x) * 0.9, z * 0.7 + y * 0.5, 31, 2)
                    d = top - y
                    if d == 0:
                        blk = GRASS if (top == Y_G and n2 > 0.42) else MOSS
                    elif d <= 3:
                        blk = DIRT if top == Y_G else MOSS
                    elif d <= 5:
                        blk = MOSSY if n2 > 0.62 else STONE
                    elif y > 58:
                        blk = "stone" if n2 > 0.35 else "andesite"
                    elif y > 52:
                        blk = "tuff" if n2 > 0.5 else "stone"
                    else:
                        blk = "deepslate" if n2 > 0.3 else COB
                    w.set((x, y, z), blk)
        # 岛底石笋
        for x in range(-12, 13):
            for z in range(-12, 13):
                n = h2(abs(x), z, 41)
                if n < 0.66:
                    continue
                tip = Y_BOT + int(round(_island_r(x, z) * 0.62)) - 1
                for k in range(1 + int(n * 4)):
                    if k and h2(abs(x) * 3 + k, z * 3, 43) < 0.25:
                        break
                    w.set((x, tip - k, z), "deepslate" if k > 1 else COB)


# ============================================================ 2. 云海

def cloud_blob(t, cx, cy, cz, rx, ry, rz, s=0):
    """椭球云团，只填空气，边缘按散列碎化。"""
    for dx in range(-int(rx) - 1, int(rx) + 2):
        for dz in range(-int(rz) - 1, int(rz) + 2):
            for dy in range(-int(ry) - 1, int(ry) + 2):
                q = (dx / rx) ** 2 + (dy / ry) ** 2 + (dz / rz) ** 2
                if q > 1.0:
                    continue
                px, pz = cx + dx, cz + dz
                if q > 0.72 and h2(abs(px), pz, s) < 0.38:
                    continue
                p = (px, cy + dy, pz)
                if not t.get(p).is_air:
                    continue
                if dy >= 1:
                    blk = CL_TOP if h2(abs(px), pz, s + 1) > 0.35 else CL_HI
                elif dy >= -2:
                    blk = CL_MID
                else:
                    blk = CL_BOT
                t.set(p, blk)


def _cloud_surface(ax: float, z: float) -> float:
    """云海高度场 0..1（只取 |x|，保证镜像一致；岛脚附近压低）。

    刻意用低频 + 少倍频：云是柔的，高频一多就从"云海"变成"碎冰"。
    """
    r = math.hypot(ax, z)
    n1 = fbm(ax * 0.026, z * 0.026, 101, 2)
    n2 = fbm(ax * 0.075, z * 0.075, 211, 2)
    v = n1 * 0.72 + n2 * 0.28
    v = (v - 0.33) / 0.34                            # 拉开对比
    if r > CLOUD_R - 14:                             # 外缘渐薄
        v -= (r - (CLOUD_R - 14)) / 14.0 * 0.95
    if r < 34:                                       # 岛脚附近云薄，让岛"压"在云上
        v -= (34 - r) * 0.030
    return v


def build_clouds(w: World) -> None:
    with w._tx("clouds"):
        for x in range(-CLOUD_R, CLOUD_R + 1):
            for z in range(-CLOUD_R, CLOUD_R + 1):
                if math.hypot(x, z) > CLOUD_R:
                    continue
                ax = abs(x)
                v = _cloud_surface(ax, z)
                if 0.02 <= v < 0.14:                           # 絮状外围
                    w.set((x, 51 + int(round(v * 30)), z), CL_WISP)
                    continue
                if v < 0.14:
                    continue
                hole = fbm(ax * 0.19, z * 0.19, 601, 2)        # 云隙
                if v < 0.45:                                   # 外缘散成云带，不连片
                    if hole < 0.55:
                        continue
                elif hole < 0.17:                              # 海面留空，透出天光
                    continue
                top = 52 + int(round(min(1.0, v) * 5))         # 云顶 52..57
                th = 1 + int(round(fbm(ax * 0.15, z * 0.15, 401, 2)
                                   * (1.3 if v < 0.45 else 4.2)))
                bot = max(44, top - th)
                for y in range(bot, top + 1):
                    if not w.get((x, y, z)).is_air:
                        continue
                    if y == top:
                        blk = CL_TOP if h2(ax, z, 307) > 0.42 else CL_HI
                    elif y >= top - 1:
                        blk = CL_HI if h2(ax, z, 311) > 0.5 else CL_MID
                    elif y > bot:
                        blk = CL_MID
                    else:
                        blk = CL_BOT
                    w.set((x, y, z), blk)
    # 云顶绒球：低频大团，嵌进海面而不是插在上面
    with w._tx("cloud_bumps"):
        for xi in range(0, CLOUD_R, 7):
            for z in range(-CLOUD_R, CLOUD_R + 1, 7):
                if math.hypot(xi, z) > CLOUD_R - 8:
                    continue
                v = _cloud_surface(xi, z)
                if v < 0.34:
                    continue
                cx = xi + int(h2(xi, z, 509) * 6.99)
                cz = z + int(h2(xi, z, 521) * 6.99)
                top = 52 + int(round(min(1.0, v) * 5))         # 云顶 52..57
                rr = 3.5 + h2(xi, z, 541) * 4.2
                for sx in (-1, 1):
                    cloud_blob(w, sx * cx, top, cz, rr,
                               rr * 0.52, rr * 0.98, s=xi * 7 + z * 13)
    # 低层碎云：从主云海的缝隙里透出来，撑出纵深
    with w._tx("cloud_low"):
        for xi in range(0, CLOUD_R, 3):
            for z in range(-CLOUD_R, CLOUD_R + 1, 3):
                if math.hypot(xi, z) > CLOUD_R - 10:
                    continue
                v2 = fbm(xi * 0.06, z * 0.06, 701, 2)
                if not (0.50 < v2 < 0.60):
                    continue
                for sx in (-1, 1):
                    cloud_blob(w, sx * xi, 46, z, 2.6, 1.1, 3.4, s=xi + z * 5 + 77)


def build_puffs(w: World) -> None:
    """岛身掠云 + 崖边云瀑 + 岛下雾絮（一律成对，保持 x 对称）。"""
    with w._tx("puffs"):
        for k, (cx, cy, cz, rx, ry, rz) in enumerate([
                (26, 60, 4, 3.0, 1.6, 5.0), (30, 56, -6, 4.0, 1.8, 6.5),
                (34, 62, 12, 3.5, 1.5, 4.5), (24, 52, 16, 3.0, 1.4, 4.0),
                (38, 58, -16, 4.5, 2.0, 7.0), (40, 54, 6, 4.0, 1.7, 6.0)]):
            for sx in (-1, 1):
                cloud_blob(w, sx * cx, cy, cz, rx, ry, rz, s=k * 17 + 1)
        # 崖边云瀑：云自岛缘垂落，接住整座浮岛
        for k, (cx, cz) in enumerate([(25, 11), (27, -5), (23, -17)]):
            for sx in (-1, 1):
                for i in range(10):
                    rr = 1.8 + i * 0.26
                    cloud_blob(w, sx * (cx + i // 4), 63 - i, cz + i // 5,
                               rr, 1.0, rr * 0.95, s=700 + k * 31 + i)
        # 岛下雾絮
        for k, (cx, cy, cz) in enumerate([(16, 47, 6), (22, 45, -10), (12, 44, -16),
                                          (18, 42, 2)]):
            for sx in (-1, 1):
                cloud_blob(w, sx * cx, cy, cz, 4.0, 1.6, 5.0, s=900 + k)


# ============================================================ 3. 远景浮石

def islet(t, cx, cy, cz, r, s=0):
    """云海里的浮石小岛：苔石顶 + 向下收锥的岩体。"""
    for dx in range(-r - 1, r + 2):
        for dz in range(-r - 1, r + 2):
            d = math.hypot(dx, dz)
            if d > r + (h2(abs(cx + dx), cz + dz, s) - 0.5) * 1.5:
                continue
            depth = 2 + int((1.0 - min(1.0, d / max(1, r))) * r * 1.25)
            for k in range(depth):
                y = cy - k
                p = (cx + dx, y, cz + dz)
                if not t.get(p).is_air:
                    continue
                n = h2(abs(cx + dx), (cz + dz) * 3 + y * 7, s + 31)
                if k == 0:
                    blk = GRASS if n > 0.45 else MOSS
                elif k <= depth * 0.4:
                    blk = DIRT if n > 0.35 else MOSS
                elif n > 0.62:
                    blk = MOSSY
                else:
                    blk = "stone" if n > 0.3 else COB
                t.set(p, blk)
    # 只留苔石与山石，不点树 —— 远景浮石一旦长树就会跟主岛抢主体
    for dx in range(-r + 1, r):
        for dz in range(-r + 1, r):
            if h2(abs(cx + dx), cz + dz, s + 17) < 0.78:
                continue
            p2 = (cx + dx, cy + 1, cz + dz)
            if t.get(p2).is_air and t.get((cx + dx, cy, cz + dz)).name in (GRASS, MOSS):
                t.set(p2, MOSSY)


def build_islets(w: World) -> None:
    with w._tx("islets"):
        for k, (cx, cz, rr) in enumerate([(48, 12, 4), (52, -21, 3),
                                          (45, -34, 4), (55, 26, 3)]):
            for sx in (-1, 1):
                islet(w, sx * cx, 57, cz, rr, s=k * 13 + 5)


# ============================================================ 4. 月台

def build_podium(w: World) -> None:
    for r in (11, 12):                                         # 散水：台基外两圈石铺
        for px, pz in ring_cells(0, 0, r):
            w.set((px, 64, pz), STONE_T if r == 12 else STONE)
    w.fill(box((-11, 65, -11), (11, 65, 11)), STONE)           # 三级收分
    w.fill(box((-10, 66, -10), (10, 66, 10)), STONE)
    w.fill(box((-10, 67, -10), (10, 67, 10)), STONE)
    for px, pz in ring_cells(0, 0, 10):
        w.set((px, 67, pz), STONE_T)                           # 压边石
    for u in range(-3, 4):                                     # 南面大踏道
        w.stairs_run((u, 64, 13), "north", 3, STONE_S)
    for sx in (-1, 1):                                         # 抱鼓石
        w.pillar((sx * 4, 64, 13), 1, STONE)
        w.set((sx * 4, 65, 13), STONE_W)
        w.set((sx * 4, 66, 13), STONE_T)
    skip = {(x, 10) for x in range(-3, 4)} | {(x, -10) for x in range(-2, 3)}
    balustrade(w, -10, 10, -10, 10, 68, RED, RED_F, spacing=3, height=3, skip=skip)
    for sx in (-1, 1):                                         # 台明四角灯
        for sz in (-1, 1):
            arm_lamp(w, sx * 10, 70, sz * 10, sx, 0)
    w.mark("terrace", (0, Y_TERRACE, 0))


# ============================================================ 5. 主阁

def build_pavilion(w: World) -> None:
    # ---- 一层 面阔 15
    half, y0, y_ef, y_dg, r0, n, pr = PAV1
    storey(w, 0, 0, half, half, y0, 5, [-7, -3, 3, 7], [-7, -3, 3, 7], door_side="south")
    w.fill(box((-half + 1, y0, -half + 1), (half - 1, y0, half - 1)), WOOD)
    cornice(w, 0, 0, half, y_ef, y_dg)
    roof_skirt(w, 0, 0, [(r0 - i, y_ef + 2 + i) for i in range(n)])
    for sx in (-1, 1):                                         # 室内金柱
        for sz in (-1, 1):
            w.pillar((sx * 4, y0 + 1, sz * 4), 11, LOGG)
    for px, pz in ((0, 5), (0, -5), (5, 0), (-5, 0)):          # 藻井灯（嵌在天花上）
        w.set((px, y_ef + 6, pz), PEARL)
    hang_lamp(w, 0, y_ef + 6, -5, drop=1)

    # ---- 二层 面阔 11
    half, y0, y_ef, y_dg, r0, n, pr = PAV2
    w.place("pingzuo", at=(0, y0, 0), r=pr)
    storey(w, 0, 0, half, half, y0, 5, [-5, -2, 2, 5], [-5, -2, 2, 5], door_side="south")
    cornice(w, 0, 0, half, y_ef, y_dg)
    roof_skirt(w, 0, 0, [(r0 - i, y_ef + 2 + i) for i in range(n)])

    # ---- 三层 面阔 7
    half, y0, y_ef, y_dg, r0, n, pr = 3, Y3, 99, 100, 6, 7, 4
    w.place("pingzuo", at=(0, Y3, 0), r=4)
    storey(w, 0, 0, 3, 3, Y3, 5, [-3, -1, 1, 3], [-3, -1, 1, 3])
    cornice(w, 0, 0, 3, y_ef, y_dg)
    crown(w, 0, 0, [(6 - i, 101 + i) for i in range(7)], deck_i=2)

    # ---- 楼梯：左右对称两部直跑梯，自一层地坪上到二层平坐
    for sx in (-1, 1):
        w.stairs_run((sx * 5, 68, 6), "north", 12, WOOD_S)
    hang_lamp(w, 0, 92, -2, drop=1)
    hang_lamp(w, 0, 103, -2, drop=1)
    w.mark("pavilion_top", (0, 110, 0))


# ============================================================ 6. 配亭 / 后轩 / 露道

def build_tings(w: World) -> None:
    for sx in (-1, 1):
        w.place("ting", at=(sx * 16, Y_G, 9))
        for ax in (-1, 1):                                     # 檐角挂灯
            for az in (-1, 1):
                hang_lamp(w, 16 * sx + ax * 6, 74, 9 + az * 6, drop=1)


def build_rear(w: World) -> None:
    """后轩：石台基 + 白墙木柱 + 庑殿顶。墙线 x=±5、z=-24/-18，台面 67。"""
    w.fill(box((-7, 58, -26), (7, 63, -16)), STONE)            # 台基（下宽上收）
    w.fill(box((-6, 64, -25), (6, 67, -17)), STONE)
    for x in range(-6, 7):
        w.set((x, 67, -17), STONE_T)
        w.set((x, 67, -25), STONE_T)
    for z in range(-25, -16):
        w.set((6, 67, z), STONE_T)
        w.set((-6, 67, z), STONE_T)
    w.fill(box((-5, 67, -24), (5, 67, -18)), WOOD)             # 室内木地
    storey(w, 0, -21, 5, 3, 67, 4, [-5, -2, 2, 5], [-3, 0, 3], door_side="south")
    # 额枋环 + 斗拱环
    for x in range(-5, 6):
        w.set((x, 72, -24), WOOD)
        w.set((x, 72, -18), WOOD)
    for z in range(-24, -17):
        w.set((-5, 72, z), WOOD)
        w.set((5, 72, z), WOOD)
    for x in range(-6, 7):
        for z in range(-25, -16):
            if not (x in (-6, 6) or z in (-25, -17)):
                continue
            if (x in (-6, 6) and z in (-25, -17)) or (abs(x) + abs(z)) % 2 == 0:
                w.set((x, 73, z), LOGG)
            else:
                w.set((x, 73, z), make(WOOD_S, half="top",
                                       facing=out_facing(x, z + 21)))
    w.hip_roof(box((-8, 74, -26), (8, 76, -16)), TILE, axis="x", inset=3)
    for x in range(-5, 6):
        w.set((x, 77, -21), TILE_R)                            # 正脊
    for sx in (-1, 1):
        w.set((sx * 5, 77, -21), GOLD)                         # 垂兽
        w.set((sx * 6, 76, -21), GOLD)
    balustrade(w, -6, 6, -25, -17, 68, RED, RED_F, spacing=3, height=3,
               skip={(x, -17) for x in range(-2, 3)})
    w.fill(box((-4, 73, -23), (4, 73, -19)), WOOD)             # 天花（兼作灯架）
    hang_lamp(w, 0, 73, -21, drop=1)


def build_link(w: World) -> None:
    """月台北口 -> 后轩的露道（标高 67），下砌石墩、两侧朱栏。"""
    w.fill(box((-3, 67, -16), (3, 67, -11)), WOOD)
    for z in (-16, -14, -12):
        for sx in (-1, 1):
            w.pillar((sx * 3, 65, z), 2, STONE)                # 露道石墩
    skip = {(x, z) for z in (-16, -11) for x in range(-3, 4)}
    balustrade(w, -3, 3, -16, -11, 68, RED, RED_F, spacing=3, height=3, skip=skip)
    for z in (-15, -13):                                       # 栏柱挑臂挂灯
        for sx in (-1, 1):
            w.pillar((sx * 3, 68, z), 3, RED)
            arm_lamp(w, sx * 3, 70, z, sx, 0)


# ============================================================ 7. 观景台与断桥

def build_overlook(w: World) -> None:
    w.fill(box((-4, 64, 14), (4, 64, 19)), STONE)
    w.fill(box((-3, 65, 15), (3, 65, 18)), WOOD)
    for x in range(-3, 4):
        w.set((x, 65, 19), STONE_T)
    balustrade(w, -4, 4, 14, 19, 65, RED, RED_F, spacing=3, height=3,
               skip={(x, 14) for x in range(-1, 2)})
    for sx in (-1, 1):                                         # 四角挑臂挂灯
        for sz in (14, 19):
            arm_lamp(w, sx * 4, 67, sz, sx, 0)


def build_bridge(w: World) -> None:
    """断桥：自观景台南缘探入云海，中段塌断。"""
    plan = {20: (-3, 3), 21: (-3, 3), 22: (-3, 3), 23: (-3, 3),
            24: (-2, 2), 25: (-1, 1), 26: (0, 0)}
    for z, (a, b) in plan.items():
        for x in range(a, b + 1):
            w.set((x, 64, z), STONE)
            if z <= 23:
                w.set((x, 65, z), STONE_T)                     # 桥面
    for z in (22, 25):                                         # 桥墩（落到岛台）
        gy = surface_y(w, 2, z)
        gy = min(gy if gy is not None else Y_EDGE, 63)
        for sx in (-2, 2):
            for y in range(gy + 1, 64):
                w.set((sx, y, z), STONE)
    for z in (20, 21, 22):                                     # 前段完整石栏
        for sx in (-3, 3):
            w.set((sx, 66, z), STONE_W)
            w.set((sx, 67, z), RED_F)
    for sx in (-1, 1):                                         # 桥头挑臂挂灯
        w.set((sx * 3, 67, 20), STONE)
        arm_lamp(w, sx * 3, 67, 20, sx, 0)
    w.set((0, 65, 24), MOSSY)                                  # 断口残迹
    for sx in (-1, 1):
        w.set((sx * 2, 65, 24), COB)


# ============================================================ 8. 植被 / 山石

def pine(t, x, y, z):
    h = 3 + int(h2(abs(x), z, 71) * 3)
    for i in range(h):
        t.set((x, y + i, z), PINE_L)
    top = y + h - 1
    for r, dy in ((3, 0), (2, 1), (3, 2), (1, 3), (2, 4)):
        for dx in range(-r, r + 1):
            for dz in range(-r, r + 1):
                if (dx == 0 and dz == 0) or abs(dx) + abs(dz) > r + 1:
                    continue
                p = (x + dx, top + dy, z + dz)
                if t.get(p).is_air:
                    t.set(p, PINE)
    t.set((x, top + 5, z), PINE)


def sakura(t, x, y, z):
    h = 4
    for i in range(h):
        t.set((x, y + i, z), SAKURA_L)
    for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        t.set((x + dx, y + h - 1, z + dz), SAKURA_L)
    for dy in range(-1, 3):
        r = 3 if dy <= 1 else 2
        for dx in range(-r, r + 1):
            for dz in range(-r, r + 1):
                if abs(dx) + abs(dz) > r + 1:
                    continue
                p = (x + dx, y + h + dy, z + dz)
                if t.get(p).is_air:
                    t.set(p, SAKURA)


def rock(t, x, y, z, r=2, s=0):
    for dx in range(-r, r + 1):
        for dz in range(-r, r + 1):
            for dy in (-1, 0, 1):
                if abs(dx) + abs(dz) + abs(dy) > r + 1:
                    continue
                n = h2(abs(x + dx), z + dz, s + dy * 7)
                if n < 0.32:
                    continue
                p = (x + dx, y + dy, z + dz)
                cur = t.get(p)
                if not (cur.is_air or cur.name in (GRASS, MOSS, DIRT)):
                    continue
                t.set(p, MOSSY if n > 0.62 else (COB if n > 0.4 else "andesite"))


def build_greenery(w: World) -> None:
    # 位置刻意避开正面（+z）的大踏道—观景台—断桥这条中轴视线
    spots = [(18, 10, "pine"), (20, -8, "pine"), (17, -15, "rock"),
             (23, 4, "rock"), (19, 18, "sakura"), (25, -12, "pine"),
             (20, -18, "rock"), (21, 17, "rock"), (13, -14, "sakura"),
             (16, 8, "rock")]
    soil = (GRASS, MOSS, DIRT)
    stone_like = soil + ("stone", "andesite", "tuff", MOSSY, COB)
    for sx in (-1, 1):
        for x, z, kind in spots:
            xx = sx * x
            gy = surface_y(w, xx, z)
            if gy is None or gy > Y_G:                         # 不许长到台基/亭顶上
                continue
            cur = w.get((xx, gy, z)).name
            if cur not in (soil if kind != "rock" else stone_like):
                continue
            if kind == "pine":
                pine(w, xx, gy + 1, z)
                w.set((xx, gy, z), MOSS)
            elif kind == "sakura":
                sakura(w, xx, gy + 1, z)
                w.set((xx, gy, z), GRASS)
            else:
                rock(w, xx, gy + 1, z, r=2, s=abs(xx))
    # 苔毯 / 花丛：只取非负半边算一次，左右各放一份，保证镜像
    for i in range(40):
        x = 1 + int(h2(i, 1, 51) * 25)
        z = -26 + int(h2(i, 2, 53) * 53)
        if x < 13 and abs(z) < 21:
            continue
        n = h2(x, z, 61)
        blk = PETAL if n > 0.6 else ("allium" if n > 0.5 else
                                     ("white_tulip" if n > 0.4 else MOSS_C))
        if n <= 0.25:
            continue
        for sx in (-1, 1):
            xx = sx * x
            gy = surface_y(w, xx, z)
            if gy is None or gy > Y_G:
                continue
            if w.get((xx, gy, z)).name not in (GRASS, MOSS):
                continue
            if not w.get((xx, gy + 1, z)).is_air:
                continue
            w.set((xx, gy + 1, z), blk)


# ============================================================ 9. 檐角灯

def build_lamps(w: World) -> None:
    for r, y in ((10, 75), (8, 88), (6, 101)):                 # 主阁三层檐角
        for sx in (-1, 1):
            for sz in (-1, 1):
                hang_lamp(w, sx * r, y, sz * r, drop=1)
    for r, y in ((6, 83), (4, 96)):                            # 平坐角柱挑臂挂灯
        for sx in (-1, 1):
            for sz in (-1, 1):
                w.pillar((sx * r, y, sz * r), 1, RED)
                arm_lamp(w, sx * r, y, sz * r, sx, 0)


# ============================================================ 组装

def define_templates(w: World) -> None:
    w.define("pingzuo", pingzuo)
    w.define("ting", ting)


STAGES = [
    ("island", build_island),
    ("cloudsea", build_clouds),
    ("puffs", build_puffs),
    ("islets", build_islets),
    ("podium", build_podium),
    ("pavilion", build_pavilion),
    ("tings", build_tings),
    ("rear", build_rear),
    ("link", build_link),
    ("overlook", build_overlook),
    ("bridge", build_bridge),
    ("greenery", build_greenery),
    ("lamps", build_lamps),
]


def build(w: World) -> None:
    for name, fn in STAGES:
        w.stage(name, fn)


# ============================================================ 输出

def main() -> None:
    w = World(seed=20260910)
    define_templates(w)
    build(w)

    print("=" * 72)
    print("云海浮阁 · 分步构建完成")
    print("=" * 72)
    for s in w.stages:
        print(f"  {s.name:<10} {len(s.patch):>7} 格   box {s.box}")
    print()
    print(w.render.summary())
    print()

    print("=" * 72)
    print("东西对称自查 compare.symmetry(axis='x') —— 整场（含云海与植被）")
    print("=" * 72)
    diffs = w.compare.symmetry(w.bounds(), axis="x")
    print(w.compare.report(diffs, limit=14))
    print()

    print("=" * 72)
    print("中轴剖面 section z=0 —— 由南向北切主阁（重檐 / 平坐 / 攒尖 / 宝顶）")
    print("=" * 72)
    print(w.render.section(axis="z", at=0, bx=box((-13, 40, -28), (13, 112, 22))))
    print()

    print("=" * 72)
    print("平面 slice y=67 —— 月台层（台明栏干 + 大踏道 + 配亭 + 露道 + 后轩）")
    print("=" * 72)
    print(w.render.slice(67, bx=box((-30, 67, -30), (30, 67, 30))))
    print()

    issues = w.lint()
    print(f"lint 共 {len(issues)} 条：{dict(Counter(i.code for i in issues))}")
    for i in issues[:6]:
        print("   ", i)
    print(f"\n方块 {len(w.cells)} 个 · 范围 {w.bounds()}")

    os.makedirs("out", exist_ok=True)
    w.export_schem("out/cloud_pavilion.schem")
    w.export_json("out/cloud_pavilion.json")
    print("已导出 out/cloud_pavilion.schem（Sponge v3）与 out/cloud_pavilion.json")

    with open("out/cloud_pavilion.txt", "w", encoding="utf-8") as f:
        f.write("阶段表\n")
        for st in w.stages:
            f.write(f"  {st.name:<10} {len(st.patch):>7} 格   box {st.box}\n")
        f.write("\n")
        f.write(w.render.summary() + "\n\n")
        f.write("symmetry:\n" + w.compare.report(diffs, limit=60) + "\n\n")
        f.write(w.render.section(axis="z", at=0) + "\n\n")
        f.write(w.render.section(axis="x", at=0) + "\n\n")
        f.write(w.render.slice(67) + "\n\n")
        f.write(w.render.slice(74) + "\n\n")
        f.write(w.render.view(center=(0, 74, 8), size=(30, 28, 30)) + "\n\n")
        f.write(w.render.view(center=(15, 70, 2), size=(20, 24, 20)) + "\n\n")
        f.write(w.render.overview(y=54, step=4) + "\n\n")
        f.write("lint:\n" + "\n".join(str(i) for i in issues[:80]) + "\n")
    print("完整报告 -> out/cloud_pavilion.txt")


if __name__ == "__main__":
    main()
