#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 务必先阅读同目录下README.txt!!!
"""哥特式大教堂 —— mcbuild 大型建筑示例（只调用库 API，不改库代码）。

形制（主轴沿 +Z：西立面在 z=0，半圆室在后）
------------------------------------------------------------
    双塔西立面（z 0..7）
    中殿 6 开间（z 8..55）+ 两侧侧廊（各 5 宽）
    十字袖廊（z 56..67，向 ±X 挑出到 |x|=23）+ 交叉尖塔
    后殿 3 开间（z 68..91）
    半圆室 Chevet（z 92..107）

横剖面（关于 x=0 严格对称）
    中殿净宽 13      |x| ≤ 6
    连拱墩 / 中殿墙  x = 7..8
    侧廊净宽 5       x = 9..13
    外侧墙           x = 14..15（外皮 15）

关键标高
    台基 61..63 · 地坪 64 · 墙脚 65 · 柱头 73 · 连拱 74..81
    楼层廊 83..87 · 高侧窗 88..95 · 拱顶起拱 96 · 拱顶顶 106
    中殿屋面 99..111 · 侧廊檐口 80 · 西塔 122/146 · 交叉塔 136/166

外观细部
    西立面凸出 2 格的三层券套门廊 + 玫瑰窗 + 山花 + 门廊角尖饰（z=-2 处的檐口前）
    双塔：塔基段三联盲券 · 两道外挑束腰线 · 四面双联高窗 · 角尖饰 · 带卷叶饰的尖顶
    飞扶壁：两段收分的墩 + 上下两道飞券 + 墩顶小尖塔（每墩线一道，东西各 10 道）
    外墙两道束腰线 + 檐下齿饰 · 正脊 11 座石十字 · 各山墙十字
    半圆室 + 三座放射小室（chevet）：攒尖顶 + 尖券窗 + 室内小祭坛

内饰
    四分肋券（每开间两条对角肋 + 横向肋 + 脊肋节点石）
    束柱（墩心 + 中殿侧/侧廊侧附柱）· 楼层廊凹龛 · 三叶高侧窗
    地面铺装（中央走道 + 侧走道 + 横向石带 + 方形回纹）
    两列长椅（座面/靠背/端板/跪凳）· 唱诗席 · 圣坛屏（中央留门洞）
    侧廊四座小祭坛 · 主祭坛 · 双讲道台 · 洗礼池 · 四处吊灯 · 苦路十四处

用到的库能力
    grid 轴网 · component 组件（pier / flyer）· stage 分步 · Frame 相对朝向
    compare.symmetry 自查 · render.slice/section/view/overview/iso · lint · 导出

运行： python examples/cathedral.py
"""

from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcbuild import Frame, World, box                        # noqa: E402
from mcbuild.ops import circle_xz                            # noqa: E402

# ============================================================ 材质

STONE = "stone_bricks"
STONE_T = "chiseled_stone_bricks"
STONE_C = "cracked_stone_bricks"
STONE_M = "mossy_stone_bricks"
PIER = "polished_diorite"
RIB = "smooth_quartz"
FLOOR = "polished_diorite"
FLOOR2 = "smooth_stone"
SLATE = "deepslate_tiles"
SLATE_S = "deepslate_tile_stairs"
SLATE_L = "deepslate_tile_slab"
LEAD = "deepslate_bricks"
GLASS = "glass_pane"
GA = "blue_stained_glass_pane"
GB = "red_stained_glass_pane"
GC = "yellow_stained_glass_pane"
GD = "purple_stained_glass_pane"
WOOD = "dark_oak_planks"
DOOR = "dark_oak_door"
GOLD = "gold_block"
LAMP = "lantern"

# ============================================================ 平面

NAVE_HALF = 6
PIER_LO, PIER_HI = 7, 8
AISLE_LO, AISLE_HI = 9, 13
WALL_LO, WALL_HI = 14, 15
OUT_X = WALL_HI
TWR_LO, TWR_HI = 7, 15            # 西塔：9×9
TWR_Z0, TWR_Z1 = -1, 7

BAY = 8
PIER_Z = [8, 16, 24, 32, 40, 48, 56, 68, 76, 84, 92]
Z_CROSS0, Z_CROSS1 = 55, 67        # 袖廊体块（含两端墙），13 深 → 中轴 z=61 为整数
TRANS_X = 23
Z_END = 113                        # 含半圆室外三座放射小室
NAVE_BAYS = [(8, 16), (16, 24), (24, 32), (32, 40), (40, 48)]
CHOIR_BAYS = [(68, 76), (76, 84), (84, 92)]

# ============================================================ 标高

GY = 61
YF = 64
Y0 = 65
Y_ARC_SPRING = 74
Y_TRI0, Y_TRI1 = 83, 87
Y_CLER0, Y_CLER1 = 88, 96
Y_VSPRING = 96
Y_VAULT = 106
Y_ROOF0, Y_ROOF1 = 99, 111     # 檐口 99 / 正脊 111（坡度 1.5，且与拱顶留 2 格净空）
Y_AISLE_SPRING = 72
Y_AISLE_TOP = 80
Y_TRANS_TOP = 96
Y_TRANS_RIDGE = 107
Y_APSE_TOP = 96
Y_APSE_TIP = 109
Y_TOWER_TOP = 122
Y_TOWER_TIP = 146
Z_SPIRE = 140
Y_CTOP = 136
Y_CTIP = 166

K_NAVE = 0.5
K_ARCADE = 1.0


# ============================================================ 尖券数学

def arch_profile(half: float, k: float = 1.0):
    """两心尖券 → [(dy, 半宽)]，从起拱线到顶点（最后一行收于 0）。

    拱心在 (±k*half, 0)，半径 R = half*(1+k)，顶点高 sqrt(half²+2*k*half²)。
    k=0 → 半圆券；k≈0.414 → 四分之一圆券；k=1 → 等边尖券。
    """
    s = float(half)
    c = k * s
    r = s + c
    apex = math.sqrt(max(0.0, s * s + 2 * s * c))
    return [(dy, max(0.0, -c + math.sqrt(max(0.0, r * r - dy * dy))))
            for dy in range(int(math.ceil(apex)) + 1)]


def _hole(h: float) -> int:
    """券线半宽 → 可挖空的半宽（严格落在券线之内）。"""
    return int(math.floor(h - 0.5))


def arch_cells(uc: int, y_bot: int, y_spring: int, prof):
    """尖券窗的内部格集合（(u, y)）—— 直段矩形 + 券内。"""
    out = []
    w0 = _hole(prof[0][1])
    if w0 >= 0:
        for y in range(y_bot, y_spring):
            for du in range(-w0, w0 + 1):
                out.append((uc + du, y))
    for dy, h in prof:
        w = _hole(h)
        if w < 0:
            continue
        for du in range(-w, w + 1):
            out.append((uc + du, y_spring + dy))
    return out


def carve_arch(f: Frame, uc: int, y_bot: int, y_spring: int, prof, vi, vo):
    for u, y in arch_cells(uc, y_bot, y_spring, prof):
        f.fill(box((u, y, vi), (u, y, vo)), "air")


def draw_arch(f: Frame, uc: int, y_spring: int, prof, vi, vo, block, **st):
    """画尖券石带（含相邻两行的补空，保证连续）。"""
    prev = None
    for dy, h in prof:
        cur = int(round(h))
        if prev is None:
            prev = cur
        for x in range(min(prev, cur), max(prev, cur) + 1):
            for v in range(vi, vo + 1):
                f.set((uc + x, y_spring + dy, v), block, **st)
                f.set((uc - x, y_spring + dy, v), block, **st)
        prev = cur


def gothic_window(f: Frame, uc: int, half: int, y_bot: int, y_spring: int,
                  k: float = 1.0, vi: int = -1, vo: int = 0, glass=GLASS,
                  trim=STONE_T, mullions=(), pattern=None, sill=True) -> list:
    """尖券窗：挖空 + 铺玻璃 + 券线窗套 + 竖棂。返回窗内 (u, y) 集合。"""
    prof = arch_profile(half, k)
    cells = arch_cells(uc, y_bot + 1, y_spring, prof)
    carve_arch(f, uc, y_bot + 1, y_spring, prof, vi, vo)
    for u, y in cells:
        f.set((u, y, vo), pattern(u - uc, y) if pattern else glass)
    for m in mullions:
        for u, y in cells:
            if u == uc + m:
                f.set((u, y, vo), trim)
                f.set((u, y, vi), trim)
    draw_arch(f, uc, y_spring, prof, vi, vo, trim)
    if sill:
        f.fill(box((uc - half, y_bot, vi), (uc + half, y_bot, vo)), trim)
    return cells


def rose_window(f: Frame, uc: int, yc: int, r: int, vi: int = -1, vo: int = 0,
                trim=STONE_T, ring=RIB, glass=GLASS) -> None:
    """玫瑰窗：外圈石环 + 12 根辐射窗棂 + 内环 + 彩色玻璃。"""
    disc = {(dx, dz) for dx in range(-r, r + 1) for dz in range(-r, r + 1)
            if dx * dx + dz * dz <= r * r}
    for dx, dz in disc:
        f.fill(box((uc + dx, yc + dz, vi), (uc + dx, yc + dz, vo)), "air")
    inner = {(dx, dz) for dx, dz in disc if dx * dx + dz * dz <= (r - 1) ** 2}
    for dx, dz in inner:
        f.set((uc + dx, yc + dz, vo), glass)
    for i in range(12):                                  # 辐射窗棂
        a = math.pi * i / 6.0
        for t in range(1, r):
            du = int(round(math.cos(a) * t))
            dv = int(round(math.sin(a) * t))
            if du * du + dv * dv <= (r - 1) ** 2:
                f.set((uc + du, yc + dv, vo), ring)
                f.set((uc + du, yc + dv, vo - 1 if vo else vi), ring)
    for dx, dz in inner:                                 # 内环
        d2 = dx * dx + dz * dz
        if (r - 2) ** 2 < d2 <= (r - 1) ** 2:
            f.set((uc + dx, yc + dz, vo), ring)
    f.fill(box((uc - 1, yc - 1, vo), (uc + 1, yc + 1, vo)), ring)
    f.set((uc, yc, vo), GC)
    for dx, dz in disc:                                  # 外圈石环
        if (r - 1) ** 2 < dx * dx + dz * dz:
            for v in range(vi, vo + 1):
                f.set((uc + dx, yc + dz, v), trim)
        else:
            f.set((uc + dx, yc + dz, vi), trim)


def stained(du, dy, palette=(GA, GB, GC, GD)):
    """粗略的彩色玻璃花纹。"""
    return palette[(abs(du) + dy // 3) % len(palette)]


def gable_y(x: int, half: int, y0: int, y1: int) -> int:
    """山墙轮廓：|x|=half 处取 y0，x=0 处取 y1。"""
    d = max(0, half - abs(x))
    return y0 + int(round(d * (y1 - y0) / half))


def spire(w: World, x0: int, x1: int, z0: int, z1: int, y0: int,
          taper: int = 4, a=SLATE, b=LEAD, cap=GOLD) -> int:
    """方尖塔：每 taper 层四周各收 1 格，收成一点后加宝顶。返回塔高。

    每隔一层在四个棱角上点一颗 chiseled 白石，就是哥特塔尖的卷叶饰（crocket）。
    """
    y = y0
    d = 0
    while x0 + d <= x1 - d and z0 + d <= z1 - d:
        xa, xb, za, zb = x0 + d, x1 - d, z0 + d, z1 - d
        for k in range(taper):
            for x in range(xa, xb + 1):
                for z in range(za, zb + 1):
                    if xa < x < xb and za < z < zb and (xb - xa) > 1:
                        continue
                    w.set((x, y + k, z), a if (abs(x) + z) % 3 else b)
        if d % 2 == 1 and xa < xb:
            for cx, cz in ((xa, za), (xa, zb), (xb, za), (xb, zb)):
                w.set((cx, y + taper - 1, cz), STONE_T)
        y += taper
        d += 1
    w.set(((x0 + x1) // 2, y, (z0 + z1) // 2), cap)
    return y - y0


def cross_finial(w: World, x: int, y: int, z: int, mat=STONE_T, h: int = 3) -> None:
    """山墙/屋脊上的石十字。"""
    w.pillar((x, y, z), h, mat)
    w.set((x - 1, y + h - 2, z), mat)
    w.set((x + 1, y + h - 2, z), mat)


# ============================================================ 侧墙坐标系

def nave_wall_frame(w: World, sx: int, zb: int, ze: int) -> Frame:
    """中殿墙（x=±7..8）开间坐标系：u 沿墙 0..ze-zb，+v 指向侧廊。"""
    if sx > 0:
        return Frame(w, (PIER_HI, 0, zb), 90)
    return Frame(w, (-PIER_HI, 0, ze), 270)


def aisle_wall_frame(w: World, sx: int, zb: int, ze: int) -> Frame:
    """外侧墙（x=±14..15）开间坐标系：v=0 内皮、v=1 外皮。"""
    if sx > 0:
        return Frame(w, (WALL_LO, 0, ze), 270)
    return Frame(w, (-WALL_LO, 0, zb), 90)


# ============================================================ 组件

def c_pier(t, h: int = 9, mat=STONE) -> None:
    """连拱墩：方墩 + 四角附柱（束柱）+ 柱础 + 柱头。

    ★ v 方向必须对称（-1..1）：实例若在 v 上不对称，
      yaw=180 的镜像兄弟就会整体错开一格，compare.symmetry 会报出来。
    """
    t.fill(box((-1, 0, -1), (0, h - 1, 1)), mat)         # 墩心 2×3
    for du in (-2, 1):                                   # 中殿侧 / 侧廊侧的附柱
        t.fill(box((du, 0, -1), (du, h - 1, 1)), RIB)
    t.fill(box((-2, 0, -2), (1, 1, 2)), STONE_C)         # 柱础
    t.fill(box((-2, 2, -2), (1, 2, 2)), STONE_T)         # 束腰线
    t.fill(box((-2, h - 4, -2), (1, h - 4, 2)), STONE_T)
    t.fill(box((-2, h - 2, -2), (1, h - 1, 2)), STONE_T)  # 柱头
    t.fill(box((-1, h - 1, -1), (0, h, 1)), PIER)


def c_flyer(t, span: int = 10) -> None:
    """飞扶壁：外侧墩（带收分与小尖塔）+ 上下两道飞券 + 中殿墙上的承券墩。

    +u 指向室外（东侧 yaw=0 / 西侧 yaw=180），v 方向对称。
    """
    # ---- 外侧墩：两段收分，下大上小
    t.fill(box((6, 0, -1), (9, 9, 1)), STONE)
    t.fill(box((7, 9, -1), (9, 9, 1)), STONE_T)
    t.fill(box((7, 10, -1), (9, 15, 1)), STONE)
    t.fill(box((7, 15, -1), (9, 15, 1)), STONE_T)
    t.fill(box((8, 16, -1), (9, 18, 1)), STONE)
    t.fill(box((8, 18, -1), (9, 18, 1)), STONE_T)
    # ---- 墩顶小尖塔
    t.fill(box((8, 19, -1), (9, 19, 1)), SLATE_L)
    t.pillar((8, 20, 0), 3, STONE_T)
    t.set((8, 23, 0), STONE)
    t.set((8, 24, 0), GOLD)
    # ---- 下道飞券
    for i in range(9):
        u = 7 - round(i * 6 / 8)
        w = 18 + round(i * 5 / 8)
        t.fill(box((u, w, -1), (u, w + 1, 1)), STONE_T)
    # ---- 上道飞券
    for i in range(9):
        u = 7 - round(i * 6 / 8)
        w = 25 + round(i * 5 / 8)
        t.fill(box((u, w, -1), (u, w + 1, 1)), STONE_T)
    # ---- 中殿高侧墙上的承券墩（顶到拱顶起拱线）
    t.fill(box((0, 21, -1), (1, 30, 1)), STONE)
    for w in (23, 26, 29):
        t.fill(box((0, w, -1), (1, w, 1)), STONE_T)
    t.fill(box((0, 30, -1), (1, 30, 1)), SLATE_L)
    t.pillar((0, 31, 0), 2, STONE_T)
    t.set((0, 33, 0), STONE)
    t.set((0, 34, 0), GOLD)


# ============================================================ ① 台基

def build_foundation(w: World) -> None:
    """三层收分台基（台面 y=63）+ 建筑地坪基座（y=64）+ 西面踏道。

    ★ 台面必须比室内地坪低一格，否则门外那一格是实体方块，门打不开（lint W3）。
    """
    w.fill(box((-20, GY, -6), (20, GY, Z_END + 3)), FLOOR2)          # 61
    w.fill(box((-18, GY + 1, -5), (18, GY + 1, Z_END + 2)), STONE)   # 62
    w.fill(box((-17, GY + 2, -4), (17, GY + 2, Z_END + 1)), STONE_M)  # 63 台面
    w.fill(box((-16, GY + 3, 0), (16, GY + 3, Z_END)), STONE)        # 64 地坪基座
    w.fill(box((-TRANS_X, GY + 3, Z_CROSS0), (TRANS_X, GY + 3, Z_CROSS1)), STONE)
    for i in range(5):                                   # 西面五级踏道（向南降）
        z = -4 - i
        w.fill(box((-6, GY + 2 - i, z), (6, GY + 2 - i, z)), STONE_T)
        w.fill(box((-6, GY + 1 - i, z), (6, GY - i, z)), STONE)
    w.mark("ground", (0, YF, -5))


# ============================================================ ② 地坪

def build_floor(w: World) -> None:
    w.fill(box((-AISLE_HI, YF, 0), (AISLE_HI, YF, 92)), FLOOR)
    w.fill(box((-TRANS_X + 1, YF, Z_CROSS0 + 2), (TRANS_X - 1, YF, Z_CROSS1 - 2)), FLOOR)
    for p in circle_xz((0, 0, 92), AISLE_HI):
        if p.z > 92:
            w.set((p.x, YF, p.z), FLOOR)
    w.mark("floor", (0, YF, 30))


# ============================================================ ③ 连拱廊 + 中殿墙

def build_arcade(w: World) -> None:
    """束墩 + 连拱 + 中殿墙（楼层廊盲拱 / 高侧窗）。"""
    # 整面墙先填实，再按开间挖连拱，最后压上束墩
    for sx in (1, -1):
        w.fill(box((sx * PIER_LO, Y_ARC_SPRING, 1), (sx * PIER_HI, Y_ROOF0 - 1, 92)), STONE)

    spans = [(z, z + BAY) for z in PIER_Z[:-1] if z + BAY in PIER_Z]
    for sx in (1, -1):
        for zb, ze in spans:
            f = nave_wall_frame(w, sx, zb, ze)
            uc = 4
            prof = arch_profile(3, K_ARCADE)             # 券洞 5 宽，墩占 u 0..2
            carve_arch(f, uc, Y0, Y_ARC_SPRING, prof, 0, 1)
            draw_arch(f, uc, Y_ARC_SPRING, prof, 0, 1, STONE_T)
            # 楼层廊：凹龛必须朝中殿开（v=1 才是中殿面），否则从室内看不见
            f.fill(box((0, Y_TRI0, 1), (8, Y_TRI1, 1)), "air")
            f.fill(box((0, Y_TRI0, 0), (8, Y_TRI1, 0)), STONE_T)
            for cu in (0, 2, 4, 6, 8):                   # 五根小柱
                f.fill(box((cu, Y_TRI0, 1), (cu, Y_TRI1, 1)), RIB if cu % 4 == 0 else STONE_T)
            f.fill(box((0, Y_TRI1 + 1, 0), (8, Y_TRI1 + 1, 1)), STONE_T)
            f.fill(box((0, Y_TRI0 - 1, 1), (8, Y_TRI0 - 1, 1)), STONE_T)
            # 高侧窗：v=1 是中殿面，玻璃落在中殿这一侧
            gothic_window(f, uc, 3, Y_CLER0, 93, k=1.0, vi=0, vo=1,
                          pattern=stained)
    # 束墩最后压上去（组件实例，改模板可整体 replay）
    for z in PIER_Z:
        w.place("pier", at=(PIER_HI, Y0, z))
        w.place("pier", at=(-PIER_HI, Y0, z), yaw=180)
    w.mark("clerestory", (0, Y_CLER0 + 2, 30))


# ============================================================ ④ 侧廊

def build_aisles(w: World) -> None:
    """外侧墙 + 尖券窗 + 侧廊尖券筒拱 + 单坡屋面。"""
    segs = [(1, 54), (68, 91)]
    bays = NAVE_BAYS + CHOIR_BAYS
    out = lambda z: Z_CROSS0 <= z <= Z_CROSS1          # noqa: E731
    for sx in (1, -1):
        # ---- 外侧墙
        for z0, z1 in segs:
            w.fill(box((sx * WALL_LO, Y0, z0), (sx * WALL_HI, Y_AISLE_TOP, z1)), STONE)
            w.fill(box((sx * WALL_LO, Y0, z0), (sx * WALL_HI, Y0 + 2, z1)), STONE_M)
            w.fill(box((sx * WALL_LO, Y_AISLE_TOP - 1, z0),
                       (sx * WALL_HI, Y_AISLE_TOP, z1)), STONE_T)
        for zb, ze in bays:                            # 一开间一扇尖券窗
            f = aisle_wall_frame(w, sx, zb, ze)
            gothic_window(f, 4, 3, 66, 74, k=1.0, vi=0, vo=1,
                          glass=GLASS, pattern=stained)
        # ---- 侧廊筒拱（两心尖券，沿 z 铺）
        c = (AISLE_LO + AISLE_HI) / 2.0
        half = (AISLE_HI - AISLE_LO) / 2.0
        prof = arch_profile(half, 0.7)
        for z in range(1, 92):
            if out(z):
                continue
            for dy, h in prof:
                for x in (int(round(c - h)), int(round(c + h))):
                    w.set((sx * x, Y_AISLE_SPRING + dy, z), STONE)
            w.set((sx * int(round(c)), Y_AISLE_SPRING + len(prof) - 1, z), RIB)
        # ---- 单坡屋面
        steps = WALL_LO - (PIER_HI + 1)
        facing = "west" if sx > 0 else "east"
        for i in range(steps + 1):
            x = PIER_HI + 1 + i
            y = Y_AISLE_TOP + 5 - int(round(i * 5 / steps))
            for z in range(0, 92):
                if out(z):
                    continue
                w.set((sx * x, y, z), SLATE_S, facing=facing, half="bottom")
                w.set((sx * x, y - 1, z), SLATE)
    w.mark("aisle_top", (0, Y_AISLE_TOP, 30))


# ============================================================ ⑤ 拱顶 + 屋面

def _barrel(w: World, axis: str, c0: int, c1: int, y_spring: int, k: float,
            a0: int, a1: int, block, ribs=(), skip=()) -> None:
    """筒拱：剖面由 (c0..c1) 定，沿 axis 从 a0 铺到 a1（axis 为 'z' 时剖面在 x）。"""
    c = (c0 + c1) / 2.0
    half = (c1 - c0) / 2.0
    prof = arch_profile(half, k)
    for a in range(a0, a1 + 1):
        if any(lo <= a <= hi for lo, hi in skip):
            continue
        for dy, h in prof:
            for p in {int(round(c - h)), int(round(c + h))}:
                w.set((p, y_spring + dy, a) if axis == "z" else (a, y_spring + dy, p),
                      block)
        w.set((int(round(c)), y_spring + len(prof) - 1, a) if axis == "z"
              else (a, y_spring + len(prof) - 1, int(round(c))), RIB)


def build_vaults(w: World) -> None:
    """中殿 / 交叉 / 后殿主拱顶 + 袖廊筒拱。"""
    _barrel(w, "z", -PIER_HI + 1, PIER_HI - 1, Y_VSPRING, K_NAVE, 1, 92,
            STONE, ribs=tuple(PIER_Z))
    # 横向肋券（每个墩线一道）
    c = 0.0
    half = float(PIER_HI - 1)
    prof = arch_profile(half, K_NAVE)
    for z in PIER_Z:
        if z > 92:
            continue
        for dy, h in prof:
            for x in (-int(round(h)), int(round(h))):
                w.set((x, Y_VSPRING + dy, z), RIB)
    # 袖廊两臂
    zc = (Z_CROSS0 + 2 + Z_CROSS1 - 2) / 2.0
    zh = (Z_CROSS1 - 2 - (Z_CROSS0 + 2)) / 2.0
    prof2 = arch_profile(zh, 0.5)
    for sx in (1, -1):
        for x in range(AISLE_LO, TRANS_X):
            for dy, h in prof2:
                for z in {int(round(zc - h)), int(round(zc + h))}:
                    w.set((sx * x, 88 + dy, z), STONE)
    w.mark("vault", (0, Y_VAULT, 30))


def _vault_y(prof, y_spring, xa: float) -> int:
    """拱顶曲面上 |x| = xa 处的标高（查券线）。"""
    for dy, h in prof:
        if h <= xa + 0.5:
            return y_spring + dy
    return y_spring


def build_ribs(w: World) -> None:
    """四分肋券：每个开间两条对角肋 + 一道横向肋 + 脊肋。

    对角肋在平面投影上是开间的两条对角线，高度跟着尖券筒拱的曲面走。
    """
    prof = arch_profile(PIER_HI - 1, K_NAVE)
    spans = ([(z, z + BAY) for z in range(8, 56, BAY)]
             + [(z, z + BAY) for z in range(68, 92, BAY)])
    steps = 3 * PIER_HI
    for zb, ze in spans:
        for flip in (0, 1):
            for i in range(steps + 1):
                t = i / steps
                x = int(round(-PIER_HI + 2 * PIER_HI * (t if flip == 0 else 1 - t)))
                z = int(round(zb + (ze - zb) * t))
                w.set((x, _vault_y(prof, Y_VSPRING, abs(x)), z), RIB)
        # 横向肋（开间端部的券）
        for dy, h in prof:
            for x in (-int(round(h)), int(round(h))):
                w.set((x, Y_VSPRING + dy, zb), RIB)
        # 脊肋两端的雕饰
        w.set((0, Y_VAULT, zb), SLATE_L)
        w.set((0, Y_VAULT + 1, zb), STONE_T)
    # 脊肋上的节点石
    for z in range(4, 92, 4):
        if w.get((0, Y_VAULT, z)).is_air:
            continue
        w.set((0, Y_VAULT + 1, z), SLATE_L if (z // 4) % 2 else STONE_T)


def build_roof(w: World) -> None:
    """中殿双坡屋面 + 正脊 + 两端山墙。"""
    w.roof_gable(box((-8, Y_ROOF0, 1), (8, Y_ROOF1, 92)), SLATE_S, axis="z")
    for z in range(1, 93):
        w.set((0, Y_ROOF1 + 1, z), LEAD)
        w.set((0, Y_ROOF1 + 2, z), SLATE_L)
        if z % BAY == 0:
            w.set((0, Y_ROOF1 + 3, z), STONE_T)
    for sx in (1, -1):
        for z in range(1, 93):
            w.set((sx * 8, Y_ROOF0 - 1, z), SLATE_L)
            w.set((sx * 8, Y_ROOF0, z), SLATE)
    for z in (92,):                                     # 后殿侧山墙
        for x in range(-8, 9):
            w.fill(box((x, Y_VSPRING, z), (x, gable_y(x, 8, Y_ROOF0, Y_ROOF1), z)), STONE)


# ============================================================ ⑥ 外观线脚与剪影

def build_mouldings(w: World) -> None:
    """外观细部：外墙束腰线、齿饰、正脊十字、各山墙十字。"""
    def out(z):
        return Z_CROSS0 <= z <= Z_CROSS1

    for sx in (1, -1):
        # ---- 侧廊外墙面上的两道束腰线 + 檐下齿饰
        for y in (67, 77):
            for z in range(-1, 92):
                if out(z):
                    continue
                w.set((sx * (WALL_HI + 1), y, z), STONE_T)
        for z in range(-1, 92, 2):
            if out(z):
                continue
            w.set((sx * (WALL_HI + 1), Y_AISLE_TOP - 3, z), STONE_T)
        for z in range(0, 92, 8):                    # 檐上釉面小兽
            if out(z):
                continue
            w.set((sx * (WALL_HI + 1), Y_AISLE_TOP - 1, z), RIB)
    # ---- 正脊上的石十字
    for z in range(6, 92, 8):
        cross_finial(w, 0, Y_ROOF1 + 3, z, STONE_T, 3)
    # ---- 各处山墙十字
    cross_finial(w, 0, Y_ROOF1 + 3, 1, STONE_T, 3)          # 西立面山花
    cross_finial(w, 0, Y_ROOF1 + 3, 92, STONE_T, 3)          # 后殿侧山墙
    for sx in (1, -1):                                       # 袖廊两山墙
        cross_finial(w, sx * (TRANS_X - 1), Y_TRANS_RIDGE + 1, 61, STONE_T, 3)
    cross_finial(w, 0, Y_APSE_TIP + 3, 92, STONE_T, 3)       # 半圆室锥顶


# ============================================================ ⑦ 袖廊 + 交叉塔

def build_transept(w: World) -> None:
    """十字袖廊：两臂墙 + 端墙（尖券门 + 玫瑰窗）+ 山墙屋面。"""
    for sx in (1, -1):
        for z0, z1 in ((Z_CROSS0, Z_CROSS0 + 1), (Z_CROSS1 - 1, Z_CROSS1)):
            w.fill(box((sx * WALL_LO, Y0, z0), (sx * TRANS_X, Y_TRANS_TOP, z1)), STONE)
            w.fill(box((sx * WALL_LO, Y0, z0), (sx * TRANS_X, Y0 + 2, z1)), STONE_M)
        w.fill(box((sx * (TRANS_X - 1), Y0, Z_CROSS0),
                   (sx * TRANS_X, Y_TRANS_TOP, Z_CROSS1)), STONE)
        w.fill(box((sx * (TRANS_X - 1), Y0, Z_CROSS0),
                   (sx * TRANS_X, Y0 + 2, Z_CROSS1)), STONE_M)
        # 端墙：13 深 → 中轴 u=6（整数），两侧镜像严丝合缝
        f = Frame(w, (sx * TRANS_X, 0, Z_CROSS1 if sx > 0 else Z_CROSS0),
                  270 if sx > 0 else 90)
        gothic_window(f, 6, 3, 66, 76, k=1.0, vi=-1, vo=0, pattern=stained)
        rose_window(f, 6, 86, 4, vi=-1, vo=0)
        # 两臂侧墙窗
        ff = Frame(w, (0, 0, Z_CROSS0), 180)
        gothic_window(ff, -sx * 18, 3, 70, 80, k=1.0, vi=-1, vo=0, pattern=stained)
        # 臂屋面
        w.roof_gable(box((sx * WALL_LO, Y_TRANS_TOP, Z_CROSS0),
                         (sx * TRANS_X, Y_TRANS_RIDGE, Z_CROSS1)),
                     SLATE_S, axis="x")
        # 端墙山花
        for dz in range(Z_CROSS0, Z_CROSS1 + 1):
            d = min(dz - Z_CROSS0, Z_CROSS1 - dz)
            yy = Y_TRANS_TOP + int(round(d * (Y_TRANS_RIDGE - Y_TRANS_TOP) / 6))
            w.fill(box((sx * (TRANS_X - 1), Y_TRANS_TOP, dz),
                       (sx * TRANS_X, yy, dz)), STONE)
    w.mark("transept", (TRANS_X, YF + 2, 61))


def build_crossing_tower(w: World) -> None:
    """交叉塔：方形塔身 + 四面双联钟窗 + 角尖饰 + 八角塔尖。"""
    x0, x1 = -PIER_HI, PIER_HI
    z0, z1 = Z_CROSS0, Z_CROSS1
    # 从高侧墙顶起砌（不要从拱顶顶起，否则墙顶与塔基之间会豁一道缝）
    w.wall(box((x0, Y_VSPRING, z0), (x1, Y_CTOP, z1)), STONE, thickness=2)
    for sx in (-1, 1):
        for sz in (-1, 1):
            cx = 0 + sx * (PIER_HI - 1)
            cz = z0 + 1 if sz < 0 else z1 - 1
            w.pillar((cx, Y_VSPRING, cz), Y_CTOP - Y_VSPRING, STONE_T)
            w.pillar((cx, Y_CTOP, cz), 9, STONE_T)
            w.set((cx, Y_CTOP + 9, cz), GOLD)
    wy = (Y_VAULT + Y_CTOP) // 2
    for u, at, yaw in ((0, (0, 0, z0 + 1), 180), (0, (0, 0, z1 - 1), 0),
                       (0, (x0 + 1, 0, (z0 + z1) / 2), 90),
                       (0, (x1 - 1, 0, (z0 + z1) / 2), 270)):
        f = Frame(w, (int(at[0]), 0, int(at[2])), yaw)
        for cu in (-3, 3):
            gothic_window(f, cu, 3, wy - 14, wy + 2, k=1.0, vi=0, vo=1,
                          pattern=stained, mullions=(0,))
        f.fill(box((-7, wy - 16, 0), (7, wy - 15, 1)), STONE_T)
        f.fill(box((-7, wy + 5, 0), (7, wy + 6, 1)), STONE_T)
        f.fill(box((-7, wy + 7, 0), (7, wy + 8, 1)), SLATE_L)
    spire(w, -6, 6, Z_CROSS0, Z_CROSS1, Y_CTOP + 1, taper=4)
    w.mark("crossing_tip", (0, (Y_CTOP + 1) + 28 + 1, 61))


# ============================================================ ⑧ 半圆室 + 放射小室

def build_apse(w: World) -> None:
    """半圆室：弧形墙 + 环向尖券窗 + 锥顶。"""
    ax, az, R = 0, 92, OUT_X
    outer = [p for p in circle_xz((ax, 0, az), R) if p.z >= az]
    inner = [p for p in circle_xz((ax, 0, az), R - 1) if p.z >= az]
    centers = [30, 60, 90, 120, 150]

    def ang(p):
        return math.degrees(math.atan2(p.z - az, p.x - ax)) % 360

    for p in outer + inner:
        w.pillar((p.x, Y0, p.z), Y_APSE_TOP - Y0 + 1, STONE)
        w.pillar((p.x, GY + 1, p.z), Y0 - GY, STONE_M)
    for p in outer + inner:                      # 环向窗
        n = min(abs(ang(p) - c) for c in centers)
        if n > 12:
            continue
        top = 90 if n <= 5 else (88 if n <= 9 else 86)
        w.fill(box((p.x, 68, p.z), (p.x, top, p.z)), "air")
    for p in inner:                              # 玻璃退在内圈
        if min(abs(ang(p) - c) for c in centers) <= 12:
            w.fill(box((p.x, 68, p.z), (p.x, 86, p.z)), GLASS)
    for p in outer:                              # 中柱与窗台
        pass
    for i in range(Y_APSE_TIP - Y_APSE_TOP + 1):  # 锥顶
        rr = R * (1 - i / (Y_APSE_TIP - Y_APSE_TOP + 1))
        y = Y_APSE_TOP + i
        ring = {p for p in circle_xz((ax, 0, az), rr) if p.z >= az}
        ring2 = {p for p in circle_xz((ax, 0, az), max(0.0, rr - 2)) if p.z >= az}
        for p in ring - ring2:
            w.set((p.x, y, p.z), SLATE)
    w.set((ax, Y_APSE_TIP + 1, az), LEAD)
    w.set((ax, Y_APSE_TIP + 2, az), GOLD)
    w.mark("apse", (0, Y_APSE_TOP, Z_END - 2))


def _chapel(w: World, cx: int, cz: int, faces, r: int = 3) -> None:
    """放射小室：小方室（墙厚 2）+ 外墙面尖券窗 + 攒尖顶 + 室内小祭坛。"""
    w.fill(box((cx - r, Y0, cz - r), (cx + r, 80, cz + r)), STONE)
    w.fill(box((cx - r + 2, Y0, cz - r + 2), (cx + r - 2, 80, cz + r - 2)), "air")
    w.fill(box((cx - r, Y0, cz - r), (cx + r, Y0 + 2, cz + r)), STONE_M)
    w.fill(box((cx - r + 1, YF, cz - r + 1), (cx + r - 1, YF, cz + r - 1)), FLOOR)
    for (fx, fz), yaw in faces:                  # 窗开在外皮：vi=-1 内皮, vo=0 外皮
        gothic_window(Frame(w, (fx, 0, fz), yaw), 0, 2, 68, 76, k=1.0,
                      vi=-1, vo=0, glass=GLASS, pattern=stained)
    for i in range(r + 2):                       # 攒尖顶（每层四周收 1，逐层实心）
        r2 = r - i
        if r2 < 0:
            break
        w.fill(box((cx - r2, 80 + i, cz - r2), (cx + r2, 80 + i, cz + r2)), SLATE)
    cross_finial(w, cx, 87, cz, STONE_T, 2)
    w.fill(box((cx - 1, YF + 1, cz + 1), (cx + 1, YF + 2, cz + 1)), STONE_T)
    w.set((cx, YF + 3, cz + 1), "glowstone")


def build_chapels(w: World) -> None:
    """半圆体外三座放射小室（chevet 的放射礼拜堂）。"""
    _chapel(w, 0, 109, [((0, 112), 0)])
    _chapel(w, 12, 104, [((15, 104), 270), ((12, 107), 0)])
    _chapel(w, -12, 104, [((-15, 104), 90), ((-12, 107), 0)])
    w.mark("chevet", (0, YF, 112))


# ============================================================ ⑨ 西立面 + 双塔

def build_west_front(w: World) -> None:
    """西立面：大尖券门廊 + 玫瑰窗 + 山花。v=0 外皮(z=0)，v=-1 内皮(z=1)。"""
    f = Frame(w, (0, 0, 0), 180)
    w.fill(box((-NAVE_HALF, Y0, 0), (NAVE_HALF, Y_VSPRING, 1)), STONE)
    w.fill(box((-NAVE_HALF, Y0, 0), (NAVE_HALF, Y0 + 2, 1)), STONE_M)
    for x in range(-NAVE_HALF, NAVE_HALF + 1):           # 山花
        w.fill(box((x, Y_VSPRING + 1, 0), (x, gable_y(x, 8, Y_ROOF0, Y_ROOF1), 1)), STONE)
    # ---- 向外凸出 2 格的门廊，三层券套（archivolt）
    w.fill(box((-PIER_LO, Y0, -2), (PIER_LO, 78, 0)), STONE)
    w.fill(box((-PIER_LO, Y0, -2), (PIER_LO, Y0 + 2, 0)), STONE_M)
    w.fill(box((-PIER_LO, 77, -2), (PIER_LO, 78, 0)), STONE_T)     # 门廊檐口
    for zz in (-2, -1, 0, 1):                            # z=1 也要挖穿，否则门后是死墙
        prof = arch_profile(4, 1.0)
        ff = Frame(w, (0, 0, zz), 180)
        carve_arch(ff, 0, YF + 1, 70, prof, 0, 0)
        draw_arch(ff, 0, 70, prof, 0, 0, RIB if zz % 2 == 0 else STONE_T)
    for x in range(-PIER_LO, PIER_LO + 1):               # 门廊山花
        yy = 78 + int(round((PIER_LO - abs(x)) * 2 / PIER_LO))
        w.fill(box((x, 78, -2), (x, yy, -2)), STONE_T if abs(x) % 3 == 0 else STONE)
    for sx2 in (1, -1):                                  # 门廊角尖饰
        w.fill(box((sx2 * PIER_LO, 65, -2), (sx2 * PIER_LO, 79, -2)), STONE_T)
        w.pillar((sx2 * PIER_LO, 80, -2), 2, STONE_T)
        w.set((sx2 * PIER_LO, 82, -2), GOLD)
    # 大门：门是双格方块，库不自动补上半格，必须上下两半都显式写
    for x in (-3, -2, -1, 1, 2, 3):
        hinge = "left" if x < 0 else "right"
        f.set((x, YF, 0), DOOR, facing="+v", half="lower", hinge=hinge)
        f.set((x, YF + 1, 0), DOOR, facing="+v", half="upper", hinge=hinge)
    for y in (YF, YF + 1):
        f.set((0, y, 0), STONE_T)                        # 中柱
    rose_window(f, 0, 84, 5, vi=-1, vo=0)
    for u in (-5, 5):                                    # 门廊两侧壁龛
        f.fill(box((u, 66, 0), (u, 77, 0)), "air")
        f.set((u, 78, 0), STONE_T)
        f.set((u, 66, 0), STONE_T)
    w.mark("west_portal", (0, YF, 0))


def build_towers(w: World) -> None:
    """西立面双塔：9×9 塔身 + 四面高窗 + 檐口 + 角尖饰 + 尖顶。"""
    for sx in (1, -1):
        x0, x1 = (TWR_LO, TWR_HI) if sx > 0 else (-TWR_HI, -TWR_LO)
        z0, z1 = TWR_Z0, TWR_Z1
        w.fill(box((x0, Y0, z0), (x1, Y_TOWER_TOP, z1)), STONE)
        w.fill(box((x0 + 2, Y0, z0 + 2), (x1 - 2, Y_TOWER_TOP, z1 - 2)), "air")
        w.fill(box((x0, Y0, z0), (x1, Y0 + 2, z1)), STONE_M)
        xc, zc = (x0 + x1) // 2, (z0 + z1) // 2
        for cx in (x0, x1 - 1):                          # 四角 2×2 角柱
            for cz in (z0, z1 - 1):
                w.fill(box((cx, Y0, cz), (cx + 1, Y_TOWER_TOP, cz + 1)), STONE_T)
        # 四面高窗（原点取内皮，+v 指向室外）
        faces = [Frame(w, (xc, 0, z0 + 1), 180),         # 北面
                 Frame(w, (xc, 0, z1 - 1), 0),           # 南面
                 Frame(w, (x0 + 1, 0, zc), 90),          # 外侧
                 Frame(w, (x1 - 1, 0, zc), 270)]         # 内侧
        for ff in faces:
            # 塔基段：三联盲券（凹进外皮 1 格）
            for cu in (-3, 0, 3):
                prof = arch_profile(1, 1.0)
                carve_arch(ff, cu, 67, 75, prof, 1, 1)
                draw_arch(ff, cu, 75, prof, 1, 1, RIB)
            # 9 宽塔身：只放一扇 7 宽双联窗（两扇会互相压掉券线）
            gothic_window(ff, 0, 3, 80, 112, k=1.0, vi=0, vo=1,
                          pattern=stained, mullions=(0,))
            # 两道束腰线（四周外挑 1 格）
            for yy in (66, 79):
                w.fill(box((x0 - 1, yy, z0 - 1), (x1 + 1, yy, z1 + 1)), STONE_T)
        for yy in (Y_TOWER_TOP - 4, Y_TOWER_TOP - 3, Y_TOWER_TOP - 2):
            w.fill(box((x0 - 1, yy, z0 - 1), (x1 + 1, yy, z1 + 1)),
                   SLATE_L if yy < Y_TOWER_TOP - 2 else STONE_T)
        for cx in (x0, x1):
            for cz in (z0, z1):
                w.pillar((cx, Y_TOWER_TOP - 1, cz), 8, STONE_T)
                w.set((cx, Y_TOWER_TOP + 7, cz), GOLD)
        spire(w, x0, x1, z0, z1, Y_TOWER_TOP + 1, taper=5)
    w.mark("tower_e", (TWR_HI, Y_TOWER_TIP, 3))
    w.mark("tower_w", (-TWR_HI, Y_TOWER_TIP, 3))


# ============================================================ ⑩ 飞扶壁

def build_buttresses(w: World) -> None:
    for z in PIER_Z:
        if z >= Z_CROSS0 and z <= Z_CROSS1:
            continue
        w.place("flyer", at=(PIER_HI, Y0, z))
        w.place("flyer", at=(-PIER_HI, Y0, z), yaw=180)


# ============================================================ ⑫ 铺装 + 陈设

def build_paving(w: World) -> None:
    """地面铺装：中央走道 + 侧走道 + 横向石带 + 中殿地面的方形回纹。"""
    w.fill(box((-2, YF, 1), (2, YF, 92)), FLOOR2)                 # 中央走道
    for sx in (1, -1):                                            # 侧走道
        w.fill(box((sx * 10, YF, 1), (sx * 11, YF, 92)), FLOOR2)
    for z in range(8, 92, 8):                                     # 每开间一道横向石带
        w.fill(box((-AISLE_HI, YF, z), (AISLE_HI, YF, z)), STONE_T)
    for z in range(4, 92, 8):                                     # 走道两侧的压边
        for x in (-3, 3):
            w.fill(box((x, YF, z + 1), (x, YF, z + 3)), STONE_T)
    # 中央走道上的方形回纹
    for z in range(12, 52, 12):
        for d in range(2, 7):
            for x in (-d, d):
                w.set((x, YF, z - d), STONE_T)
                w.set((x, YF, z + d), STONE_T)
            for dz in (-d, d):
                w.set((-d, YF, z + dz), STONE_T)
                w.set((d, YF, z + dz), STONE_T)
    w.mark("paving", (0, YF, 20))


def build_furnishings(w: World) -> None:
    """中殿长椅 · 唱诗席 · 圣坛屏 · 侧廊小祭坛 · 祭坛 · 讲道坛 · 洗礼池 · 吊灯 · 苦路。"""
    # ---------------- 中殿长椅（两列，带靠背与端板）
    for z in range(16, 52, 3):
        for sx in (1, -1):
            w.fill(box((sx * 3, YF + 1, z - 1), (sx * 6, YF + 1, z)), WOOD)      # 座面
            w.fill(box((sx * 3, YF + 2, z - 1), (sx * 6, YF + 3, z - 1)), WOOD)  # 靠背
            w.fill(box((sx * 3, YF + 2, z), (sx * 3, YF + 3, z)), WOOD)          # 内侧端板
            w.fill(box((sx * 6, YF + 2, z), (sx * 6, YF + 3, z)), WOOD)          # 外侧端板
            w.fill(box((sx * 3, YF + 1, z + 1), (sx * 6, YF + 1, z + 1)), SLATE_L)  # 跪凳
    # ---------------- 唱诗席（后殿两侧，面向中央）
    for sx in (1, -1):
        for z in range(70, 88, 2):
            w.fill(box((sx * 6, YF + 1, z), (sx * 6, YF + 2, z)), WOOD)
            w.fill(box((sx * 6, YF + 3, z), (sx * 6, YF + 4, z)), SLATE_L, half="bottom")
        w.fill(box((sx * 6, YF + 1, 70), (sx * 6, YF + 5, 70)), WOOD)
        w.set((sx * 6, YF + 6, 70), GOLD)
    # ---------------- 圣坛屏（rood screen，横跨中殿，中央留门）
    zs = Z_CROSS0 - 1
    for x in range(-NAVE_HALF, NAVE_HALF + 1):
        if abs(x) <= 1:
            continue                                     # 中央门洞
        if x % 3 == 0:                                   # 立柱
            w.fill(box((x, YF + 1, zs), (x, YF + 4, zs)), "dark_oak_log")
            w.set((x, YF + 4, zs), STONE_T)
        else:                                            # 镂空木格
            w.fill(box((x, YF + 1, zs), (x, YF + 3, zs)), WOOD)
            w.set((x, YF + 2, zs), SLATE_L)
            w.fill(box((x, YF + 4, zs), (x, YF + 4, zs)), "dark_oak_fence")
    w.fill(box((-NAVE_HALF, YF + 4, zs), (NAVE_HALF, YF + 4, zs)), STONE_T)
    w.fill(box((-NAVE_HALF - 1, YF + 5, zs), (NAVE_HALF + 1, YF + 5, zs)), SLATE_L)
    cross_finial(w, 0, YF + 5, zs - 1, STONE_T, 3)
    w.mark("rood_screen", (0, YF + 2, zs))
    # ---------------- 侧廊小祭坛（每个开间一个，贴外侧墙）
    for zb, _ in NAVE_BAYS[:4]:
        for sx in (1, -1):
            w.fill(box((sx * 13, YF + 1, zb + 3), (sx * 13, YF + 2, zb + 5)), STONE_T)
            w.set((sx * 13, YF + 3, zb + 4), "glowstone")
            w.fill(box((sx * 12, YF + 1, zb + 3), (sx * 12, YF + 1, zb + 5)), "dark_oak_fence")
    # ---------------- 主祭坛（后殿）
    w.fill(box((-3, YF + 1, 86), (3, YF + 2, 88)), STONE_T)
    w.fill(box((-2, YF + 3, 87), (2, YF + 3, 87)), GOLD)
    w.set((0, YF + 4, 87), "glowstone")
    for du in (-4, 4):                                   # 祭坛两侧的烛台
        w.pillar((du, YF + 1, 86), 4, WOOD)
        w.set((du, YF + 5, 86), "glowstone")
    w.mark("altar", (0, YF + 3, 87))
    # ---------------- 讲道台 + 读经台（成对布置，保持东西对称）
    for sx in (1, -1):
        w.fill(box((sx * 4, YF + 1, 76), (sx * 5, YF + 4, 77)), WOOD)
        w.fill(box((sx * 4, YF + 5, 76), (sx * 5, YF + 5, 77)), SLATE_L)
        w.set((sx * 4, YF + 6, 76), "glowstone")
    # ---------------- 洗礼池（落在中轴上）
    w.fill(box((-1, YF + 1, 4), (1, YF + 2, 6)), STONE_T)
    w.set((0, YF + 2, 5), "water", waterlogged=True)
    w.set((0, YF + 3, 5), "dark_oak_fence")
    # ---------------- 吊灯：中殿三盏 + 交叉处一盏（自拱顶垂链）
    for cz in (20, 36, 52):
        for y in range(Y_VSPRING + 6, Y_VAULT):
            w.set((0, y, cz), "chain", axis="y")
        w.set((0, Y_VSPRING + 5, cz), LAMP)
        w.set((0, Y_VSPRING + 4, cz), "glowstone")
    for y in range(92, Y_VAULT):
        w.set((0, y, 61), "chain", axis="y")
    w.set((0, 91, 61), LAMP)
    w.set((0, 90, 61), "glowstone")
    # ---------------- 苦路十四处（嵌在中殿墙面上的小木龛）
    for z in range(14, 92, 6):
        for sx in (1, -1):
            w.set((sx * PIER_LO, 70, z), WOOD)
            w.set((sx * PIER_LO, 71, z), STONE_T)
            w.set((sx * PIER_LO, 72, z), RIB)


# ============================================================ 主流程

def define_templates(w: World) -> None:
    """★ 模板必须在 stage 函数之外定义（否则 rerun 会用旧模板覆盖新的）。"""
    w.define("pier", c_pier)
    w.define("flyer", c_flyer)


STAGES = [
    ("台基", build_foundation),
    ("地坪", build_floor),
    ("连拱廊", build_arcade),
    ("侧廊", build_aisles),
    ("拱顶", build_vaults),
    ("肋券", build_ribs),
    ("屋面", build_roof),
    ("线脚", build_mouldings),
    ("袖廊", build_transept),
    ("交叉塔", build_crossing_tower),
    ("半圆室", build_apse),
    ("放射小室", build_chapels),
    ("西立面", build_west_front),
    ("双塔", build_towers),
    ("飞扶壁", build_buttresses),
    ("铺装", build_paving),
    ("陈设", build_furnishings),
]


def build(w: World) -> None:
    define_templates(w)
    for name, fn in STAGES:
        w.stage(name, fn)


def main() -> None:
    w = World(seed=20260910)
    build(w)
    w.checkpoint()                       # 把"整体建成"设为 diff 基线

    bar = "=" * 74
    print(bar)
    print("阶段划分（stage）")
    print(bar)
    for s in w.stages:
        print(f"  {s.name:<6} {str(s.box):<34} {len(s.patch):>7} cells")

    print()
    print(bar)
    print("组件实例（component）")
    print(bar)
    for name in ("pier", "flyer"):
        lst = w.instances_of(name)
        print(f"  {name}: {len(lst)} 个 · 例 {lst[0] if lst else '-'}")
    print("  锚点:", {k: str(v) for k, v in w.marks.points.items()})

    print()
    print(bar)
    print("东西对称自查 compare.symmetry(axis='x')")
    print(bar)
    diffs = w.compare.symmetry(w.bounds(), axis="x")
    print(f"共 {len(diffs)} 处不一致")
    print(w.compare.report(diffs, limit=12))

    print()
    print(bar)
    print("平面 slice y=64 —— 台基与柱网（双塔 / 中殿 / 袖廊 / 半圆室）")
    print(bar)
    print(w.render.budget(7000).slice(64, step=1))

    print()
    print(bar)
    print("剖面 section x=0 —— 中轴纵剖（西立面 / 中殿拱顶 / 交叉塔 / 半圆室）")
    print(bar)
    print(w.render.budget(9000).section(axis="x", at=0))

    print()
    print(bar)
    print("剖面 section z=30 —— 横剖（侧廊 / 连拱 / 高侧窗 / 拱顶 / 飞扶壁）")
    print(bar)
    print(w.render.budget(9000).section(axis="z", at=30))

    print()
    print(bar)
    print("平面 slice y=66 —— 室内陈设（长椅 / 圣坛屏 / 侧廊小祭坛 / 唱诗席）")
    print(bar)
    print(w.render.budget(7000).slice(66, bx=box((-16, 66, -4), (16, 66, 114)), step=1))

    print()
    print(bar)
    print("剖面 section z=-1 —— 西立面内层（门廊券套 / 玫瑰窗 / 双塔高窗）")
    print(bar)
    print(w.render.budget(4000).section(axis="z", at=-1, bx=box((-17, 58, -3), (17, 150, 4))))

    print()
    print(bar)
    print("全景 overview y=64（step=4）")
    print(bar)
    print(w.render.budget(5000).overview(y=64, step=4, center=(0, 80, 46),
                                         size=(24, 20, 24)))

    print()
    print(bar)
    print("等距投影 iso（step=5）")
    print(bar)
    print(w.render.budget(9000).iso(step=5))

    print()
    print(bar)
    print("四段式反馈协议 w.report()（只画西立面一带）")
    print(bar)
    print(w.report("ok: 教堂建成", render_box=box((-8, 60, -2), (8, 74, 10))))

    print()
    print(bar)
    print("改一处、看 diff：把第 3 个束墩改成长老金（组件局部覆盖 patch）")
    print(bar)
    inst = w.instance("pier", 2)
    w.patch(inst, (0, 2, 0), GOLD)                    # 实例内局部坐标，不是世界坐标
    print(w.render.diff())
    print("patch 后该点:", w.get(inst.to_world((0, 2, 0))).short(),
          "· overrides:", {str(k): v.short() for k, v in inst.overrides.items()})
    w.unpatch(inst, (0, 2, 0))
    w.undo()                                          # 回到基线

    print()
    print(w.render.summary())
    print()
    print("材质 top10:", w.query.histogram(10))
    codes = {}
    for i in w.lint():
        codes[i.code] = codes.get(i.code, 0) + 1
    print("lint:", codes)
    print("总方块数:", len(w.cells), " 包围盒:", w.bounds())

    os.makedirs("out", exist_ok=True)
    w.export_schem("out/cathedral.schem")
    w.export_json("out/cathedral.json")
    print("已导出 out/cathedral.schem（Sponge v3）与 out/cathedral.json")


if __name__ == "__main__":
    main()
