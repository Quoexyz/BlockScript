#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 务必先阅读同目录下README.txt!!!
"""浮空岛 —— mcbuild 程序化地形示例（只调用库 API，不改库代码）。

这是整套示例里**唯一一个"好不好看只能靠渲图验收"**的东西：它没有可断言的
正确性，只有"像不像一块被撕下来、底下还吊着几根短根的岩体"。所以跑它的正确
方式是**渲一张图，用眼睛看**。

    python examples/island.py               # 自检 + 对齐表 + 主图 out/island/island.png
    python examples/island.py --variants    # 并排渲 6 组参数变体（参数写进文件名）
    python examples/island.py --variants --r 36   # 变体换半径跑
    python -c "import examples.island as i; i.align_table()"   # 只打对齐表

格数量级（尺度基准，**实心块状**岛体，不是中空壳）
--------------------------------------------------
实测（seed=7，和主图/对齐表同一个 seed；`r` 是顶面半径，格数是**唯一格**，
`高/宽` = 总高 / 总宽 = 岛直径）：

    尺寸档   r      格数      高/宽   建造
    islet    16     13,366    1.20   0.1s
    islet    20     21,219    1.07   0.2s
    mid      24     51,746    1.26   0.4s   ← 主图（= 源头 place_proto("mid",24)）
    mid      36    122,114    0.99   1.0s
    mid      55    299,940    0.67   2.9s
    mid      88    872,543    0.43   9.1s   ← 反例：mid 档撑不住 88
    prime    55    398,210    0.90   3.7s
    prime    72    717,728    0.69   7.1s
    major    88  1,512,115    0.83  13.9s   ← 同样是 88，换档才立起来

    最后两行是这张表最该看的地方：**`r` 只管横截面，厚度归尺寸档。**
    同样是 r=88，`mid` 是 0.43（摊成饼），`major` 才有 0.83。

    对照：examples/cloud_pavilion.py 整场 52,196 格 —— 一座 r=24 的岛就和那
    整场同量级。"块状化"（实心）之后比早先的中空壳贵 5–6 倍，半径越大差得
    越多；所以**"够不够大"要和这张表比，不要靠目测**。

    （早先我判过"半径 ≲28 时岩块凸起太少（`min(6, r/12)` 坨）、读成圆底
    花盆"，所以主图躲到 36。**那个诊断是错的**：真因是厚度被按半径比例压扁
    了。数值一对齐，r=24 自己就立起来了 —— 见教训 9。）

机制：**一个函数覆盖四个尺寸档**
-------------------------------
   岛顶面       圆丘形地表（中心抬起、边缘落下）+ 低频起伏 + 2×2 分块的 ±1 抖动
   岛体         实心、连续收分；只有两个**缓慢连续**的变化量
                   （1）半径的低频起伏（周期约 28 层）+ 形状表相位的缓慢扭转
                   （2）整体朝一侧倾斜，越往下偏得越多（不能是抖动）
   岩块凸起     几坨 5–15 格的椭球从体表鼓出来、互相咬合 —— "块状"读感的关键
   根系         一根主根 + 若干细支根，从**倾斜后的**底端分出去，向下收细
   轮廓         圆周扰动（4 个低阶谐波）+ 椭圆拉长（除 sqrt(aspect) 保持面积）+ 旋转
   尺寸/厚度    厚度、根数、根长按 `size` 查 `SIZE_CLASSES`（照搬源头的
                `PROTO_PARAMS`）—— **与 `r` 无关**，这是"立不立得起来"的总闸

调用约定
--------
* 第一个参数是 `target`（`World` 或 `Frame`）—— 这样白拿局部坐标与朝向重映射。
* **局部坐标 `(0,0,0)` 就是岛顶面的中心**，岛体往 `-Y` 长。落位交给调用方::

      with w.frame(at=(cx, 64, cz)) as f:
          island(f, r=24, seed=1234, mat=dict(top="grass_block"))

* 全部伪随机走 `mcbuild.det`，**同 seed 永远同一座岛**；绝不用 `hash()`。
* 想打散复制粘贴感，在调用方套 `with w.material({...})` —— 库会自动混材质。

返工的教训（**这部分比代码值钱，每一条都是真的被否过一次**）
------------------------------------------------------------
1. **逐层随机 = 一摞错开的乱板。** 第三版给每层换一张形状表（彼此旋转差 90°），
   渲出来是"一层层还错开的"（用户原话，直接否掉）。岩体是连续的 ——
   层与层之间只能靠**相位的缓慢扭转**（`TWIST = 0.6` 表项/层）拉开差别。
2. **把侧面量化成台阶想做出地层感 = 烙饼塔。** 试过切 5 级台阶（`TERRACES`），
   比光滑锥面还假：真实岩体的层感来自轮廓的低频起伏，不是水平切面。
3. **顶面抖动必须按 2×2 分块。** 光滑高度场量化成整数后，等值线是一圈圈同心纹
   （俯瞰像等高线地图）；加散点抖动能打散它，但**逐格**的 ±1 会渲成针织地毯。
4. **用低阶正弦，不用噪声。** 在 1 格分辨率的体素里，高阶噪声只会碎成锯齿。
5. **只用一两个谐波，轮廓还是"压扁的圆"。** `wobble` 用了四个不同阶的谐波。
   （`--variants` 里的 `lobes2` 就是用来复现这一条的。）
6. **决定观感的是岛体厚度，不是轮廓调参。** 这条是试了 8 个变体才看出来的：
   太薄的话无论轮廓怎么调，都读成"薄盖 + 一条腿"。
   （`--variants` 的 `thin_d22` vs `thick_d56` 一眼能看出差别。）
7. **高宽比要落在 ~1。** 总高（体 + 根）和总宽（直径）得同一量级。改之前
   总高/总宽 ≈ 3.8 —— 又细又长，就是"倒过来的水滴顶着凸出的草皮"。
   两个把比例带偏的元凶：根长不封顶（1.9 倍半径 → 岛下面拖一根比身长还长的
   细绳）、深板岩比例给到 38%（下半身整体发黑,和同样发黑的根连成一把黑尖刺）。
8. **方法论：参数调不动时，先渲一排变体横向对比，再动代码。** 别走
   "改一版 → 渲一张 → 被否 → 再改" —— 那正是这个模块返工五版的过程。
   `--variants` 就是把这条固化成可复现的东西。
9. **提取机制时，"看着像"不算过关，数值必须逐座对齐源头。** 第一版提取我把
   `depth` 写成 `0.85–1.25 × r`、`root_r` 改成 `0.068 r`、根数给到 3–5 ——
   三条都偏离源头，于是 r=24 上**矮 38%**（高 42 vs 68）、格数只剩 58%、
   根分项只剩 1/3，渲出来是"桶"。而**同一张图里 r=36 只差 21%**，光看图
   完全看不出来"小半径塌得最狠"。现在 `ALIGN_REF` + `align_table()` 把
   格数/总高/高宽比/根分项四列钉死在表里，`selfcheck()` 每次都会查 ——
   观感问题绝大多数先是数值问题。

和 `sky/terrain.py` 的差别（**只剩两处，都是有理由的**）
--------------------------------------------------------
机制与默认值现在是**逐行对齐**的：`PROFILES` / `SIZE_CLASSES` / 形状表 /
`_disc_w` / `_blob` / `_cone_root` / 收分与倾斜的公式 / 深层深板岩 20% /
`root_r = 0.13r`（封顶 6）/ 根长 0.55r 上限，全都一样 —— 实测 r=16/24/36/55
的**岛体分项逐格相同**、总高与格数差 <0.1%（见 `align_table()`）。

只有两处**故意**不同，都是为了消掉悬空（W1）：

1. **表层的轮廓收进岛体首层**（`_top_skin(..., clip=rr0, clip_ph=dy0*TWIST)`，
   余量 0，与 `_disc_w` 同一条算式）。`_disc_w` 的包围盒 `d > R+0.5` 先执行、
   `d <= R*wt(θ)+0.5` 后执行，所以一层方块的轮廓其实是
   `d <= R*min(1, wt(θ)) + 0.5`，形状因子只在往里收；而源头的 `_disc_relief`
   只按 `R*wt(θ)` 取轮廓，于是在形状**往外鼓**的方向上会超出身下那一层 ——
   重力材质下就是一片 W1（实测 r=20/36/55 → 18/36/71 处）。
2. **地表起伏的下界钉在 `-sub_depth`**（源头是 `bottom = min(-sub_depth, h-1)`，
   h 越深挖得越低：h ≤ -2 的那几列会顺着地势写到 -4、-5，那里岛体已经逐层
   收分收掉，底下是空气）。

两条都改完，`red_sand` / `sand` / `gravel` 三种重力材质下 W1 才归零
（`selfcheck()` 每次都验）。
"""

from __future__ import annotations

import math
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcbuild import World                              # noqa: E402
from mcbuild.det import TAU, in_range, profile_at, unit, wobble   # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "out", "island")

# ---------------------------------------------------------------- 纵剖面

#: 岛体剖面：`t=0` 是顶面，`t=1` 是底部尖端，值是**半径系数**。
#: 三条曲线的差别就是"收分节奏" —— 加一条新剖面比加一个新函数便宜得多。
PROFILES = {
    # 常规浮岛：从顶面平滑收到尖
    "cone": [(0.00, 1.00), (0.30, 0.94), (0.52, 0.84), (0.70, 0.70),
             (0.84, 0.52), (0.94, 0.34), (1.00, 0.22)],
    # 垂根岛：顶面收窄，中段鼓出来再收到尖。顶面给到 0.52 太窄，成了"蛋"。
    "bulb": [(0.00, 0.62), (0.16, 0.88), (0.34, 1.00), (0.55, 0.85),
             (0.75, 0.55), (0.90, 0.26), (1.00, 0.00)],
    # 遗迹切片：一块平板，边缘几乎是垂直切下去的
    "plate": [(0.00, 1.00), (0.55, 0.97), (0.80, 0.80), (0.94, 0.42),
              (1.00, 0.00)],
}

MAT_DEFAULT = dict(top="grass_block", sub="dirt", body="stone", deep="deepslate")

#: 尺寸档 —— 照搬 `sky/terrain.py` 的 `PROTO_PARAMS`（`isle` 族那六个原型）。
#:
#: **这一张表是"厚度到底该给多少"的唯一出处，别再用半径的比例去推。**
#: 第一次提取时我把 `depth` 写成 `0.85–1.25 × r`，结果在 r=24 上比源头**矮 38%**
#: （高 42 vs 68）、格数只有 58%，渲出来就是"桶/花盆"。源头的 `mid` 档
#: `depth = 32–52` 是**跟半径无关**的绝对厚度：r=24 和 r=36 都取 45
#: （seed=7），所以小半径本来就该又高又窄（高宽比 1.26），大半径自然变扁
#: （0.67）—— 那是尺寸档的语义，不是 bug。半径只管横截面。
#:
#: `root_len` 那个上限 `min(root_len, r * 0.55)` 仍然生效（见 `island()`）。
SIZE_CLASSES = {
    "islet": dict(depth=(18, 30), roots=(0, 1), root_len=(10, 24)),
    "mid":   dict(depth=(32, 52), roots=(1, 2), root_len=(16, 34)),
    "prime": dict(depth=(48, 72), roots=(3, 4), root_len=(26, 46)),
    "major": dict(depth=(70, 105), roots=(3, 5), root_len=(48, 70)),
}

_WT = 256          # 形状查找表的分辨率（省掉逐格算三角函数）

#: 逐层**缓慢扭转**的速率（查找表相位/层）。层与层之间只能差一点点 ——
#: 见教训 1：逐层换表就是一摞错开的乱板。
TWIST = 0.6


# ---------------------------------------------------------------- 形状查找表

_TABLE_CACHE: dict = {}


def _build_table(seed: int, amp: float, k: int,
                 aspect: float = 1.0, rot: float = 0.0) -> list:
    """把**圆周扰动 + 椭圆拉长 + 旋转**一起烘进一张 256 项查找表。

    烘完表之后，逐格只剩查表，没有三角函数 —— 这是"零运行时开销"的那一半；
    另一半是 `_TABLE_CACHE`：同一组形状参数在多座岛之间复用同一张表。

    为什么要这么下功夫：模板库最容易被一眼看穿的破绽就是"全是正圆"。
    真实空岛没有一个是正圆 —— 给它 1.2–1.6 的长宽比再叠上扰动，立刻就不像
    程序生成的了。**除 `sqrt(aspect)` 是为了保持面积不变**，免得拉长之后把岛
    撑大、把落位时的净距规则挤爆。
    """
    a = math.radians(rot)
    ca, sa = math.cos(a), math.sin(a)
    norm = 1.0 / math.sqrt(max(1.0, aspect))
    out = []
    for i in range(_WT):
        th = TAU * i / _WT
        c, s = math.cos(th), math.sin(th)
        rc = c * ca + s * sa
        rs = -c * sa + s * ca
        ell = 1.0 / math.sqrt((rc / aspect) ** 2 + rs * rs)
        out.append(wobble(seed, th, amp, k) * ell * norm)
    return out


def shape_table(seed: int, amp: float, k: int,
                aspect: float = 1.0, rot: float = 0.0) -> list:
    """`_build_table` 的带缓存版本。缓存键是**参数元组**，所以确定性不受影响。"""
    key = (int(seed), round(float(amp), 6), int(k),
           round(float(aspect), 6), round(float(rot), 6))
    tab = _TABLE_CACHE.get(key)
    if tab is None:
        tab = _build_table(seed, amp, k, aspect, rot)
        _TABLE_CACHE[key] = tab
    return tab


def _wt(tab, th: float, ph: float = 0.0) -> float:
    """按角度查形状表。`ph` 是相位偏移（单位=表项），用来做逐层的缓慢扭转。"""
    return tab[int((th % TAU) / TAU * _WT + ph) % _WT]


# ---------------------------------------------------------------- 基本形体

def _disc_w(t, y: int, R: float, tab, mat,
            ox: int = 0, oz: int = 0, ph: float = 0.0) -> int:
    """带形状扰动的实心盘。

    `ox/oz` 把这一层整体挪开（岛体倾斜用）；`ph` 是形状表的相位（逐层扭转用）。
    **两个都必须是缓慢连续量** —— 逐层随机会让侧面变成一摞错开的板（教训 1）。
    """
    lim = int(math.ceil(R)) + 1
    n = 0
    for dx in range(-lim, lim + 1):
        for dz in range(-lim, lim + 1):
            d = math.hypot(dx, dz)
            if d > R + 0.5:
                continue
            if d <= R * _wt(tab, math.atan2(dz, dx), ph) + 0.5:
                t.set((dx + ox, y, dz + oz), mat)
                n += 1
    return n


def _top_skin(t, R: float, tab, top: str, sub: str, seed: int,
              hill: int = 3, sub_depth: int = 2, y0: int = 0,
              dome: float = 0.0, clip: float = None, clip_ph: float = 0.0,
              margin: float = 0.0) -> dict:
    """**圆丘形**的表层（不是一块平板）。返回 `{"top": n, "sub": n}`。

    平板顶 + 等值线圈，渲出来就是"搁在石头上的绿盘子"。加一个中心抬起、边缘
    落下的圆丘，再叠低频起伏，才像地表。

    `clip` / `clip_ph` —— 表层的轮廓**必须落在岛体首层的轮廓里**，而且要用
    和 `_disc_w` **完全相同**的判据（`margin = 0`，不要留余量）：

    * `_disc_w` 的包围盒 `d > R + 0.5` 先执行、`d <= R * wt(θ) + 0.5` 后执行，
      所以一层方块的轮廓其实是 `d <= R * min(1, wt(θ)) + 0.5`；
    * 表层原来只按 `R * wt(θ)` 取轮廓（源头的 `_disc_relief` 就是这样），
      于是在形状往外鼓的方向上会**超出**身下那一层 —— 挂空。

    两种情况都只在**重力材质**下暴露（`sky/terrain.py` 现状在 r=20/36/55 上
    分别漏 18/36/71 处 W1），所以本示例把 `clip` 传满。
    """
    lim = int(math.ceil(R)) + 1
    p1 = unit(seed, 71) * TAU
    p2 = unit(seed, 72) * TAU
    p3 = unit(seed, 73) * TAU
    p4 = unit(seed, 74) * TAU
    p5 = unit(seed, 75) * TAU
    F = max(3.0, R / 2.6)
    clip_r = R if clip is None else max(1.0, clip - margin)
    res = {"top": 0, "sub": 0}
    for dx in range(-lim, lim + 1):
        for dz in range(-lim, lim + 1):
            d = math.hypot(dx, dz)
            if d > R + 0.5:
                continue
            th = math.atan2(dz, dx)
            # **和 `_disc_w` 同式**：那一层的判据是 `d <= R + 0.5` 与
            # `d <= R*wt(θ) + 0.5` 的交集，即 `d <= R*min(1, wt(θ)) + 0.5`。
            # `margin=0` 时这里和它是同一个表达式（`rr0` 也是同一条算式算的），
            # 所以表层落进岛体首层是**精确**的、不多收一格。
            if d > min(clip_r, clip_r * _wt(tab, th, clip_ph)) + 0.5:
                continue
            bump = dome * (1.0 - (d / max(1.0, R)) ** 2)
            # 四个不同方向的低频项叠加。只用一组 x/y 轴向的正弦的话，
            # 等值线会变成一圈圈规整的同心纹（看着像等高线地图，很假）。
            h = int(round(bump + hill * (
                0.40 * math.sin(dx / F + p1) * math.cos(dz / F + p2)
                + 0.28 * math.sin((dx * 0.78 - dz * 0.62) / F + p3)
                + 0.20 * math.sin((dx * 0.30 + dz * 0.95) / (F * 1.7) + p4)
                + 0.14 * math.sin((dx + dz) / (F * 0.55) + p5))))
            # **2×2 一组的 ±1 抖动**（教训 3）。逐格的 ±1 会变成针织地毯。
            # 这里只能用逐格哈希 —— 正弦太规则。
            jt = unit(seed, (dx >> 1) + 512, (dz >> 1) + 512)
            h += 1 if jt > 0.78 else (-1 if jt < 0.22 else 0)
            # 下界**钉死在 `-sub_depth`**（正是岛体首层 `-sub_depth-1` 的上一格）。
            # 源头的写法是 `bottom = min(-sub_depth, h - 1)`：h 越深挖得越低，
            # 起伏下探到 h ≤ -2 的那几列会顺着地势写到 -4、-5 —— 那里岛体早已
            # 收分收掉（`R` 逐层变小），底下是空气，**重力材质直接报 W1**。
            # 钉住之后 `range` 永远非空（顺手躲开 `range(-2, -1)` 只产出 `[-2]`
            # 那个坑），而且每一格的正下方都是岛体首层，不可能悬空。
            bottom = -sub_depth
            for k in range(bottom, h + 1):
                t.set((dx, y0 + k, dz), top if k == h else sub)
                res["top" if k == h else "sub"] += 1
    return res


def _blob(t, cx: int, cy: int, cz: int, rx: float, mat,
          ry: float = None, rz: float = None) -> int:
    """一坨实心岩块（椭球）。岛体靠若干这种块互相咬合，轮廓才有"块状"读感 ——
    只靠圆周扰动调不出来，那还是回转体，只是边缘更皱。"""
    ry = rx * 0.72 if ry is None else ry
    rz = rx if rz is None else rz
    n = 0
    limy, limx, limz = int(ry) + 1, int(rx) + 1, int(rz) + 1
    for dy in range(-limy, limy + 1):
        fy = (dy / ry) ** 2
        if fy > 1.0:
            continue
        for dx in range(-limx, limx + 1):
            for dz in range(-limz, limz + 1):
                if (dx / rx) ** 2 + fy + (dz / rz) ** 2 > 1.0:
                    continue
                t.set((cx + dx, cy + dy, cz + dz), mat)
                n += 1
    return n


def _cone_root(t, x0: float, z0: float, y0: int, length: int, r0: float,
               drift_x: float, drift_z: float, mat) -> int:
    """一条向下收细的根。越往下越往中心收，读起来才像"吊着"。

    实心（早期做成中空管说是省方块，但既然岛体都实心了，根没必要搞特殊）。
    """
    n = 0
    for k in range(length):
        tt = k / max(1, length - 1)
        r = r0 * (1.0 - tt) ** 0.65
        if r < 0.5:
            break
        cx = int(round(x0 + drift_x * tt))
        cz = int(round(z0 + drift_z * tt))
        lim = int(math.ceil(r))
        for dx in range(-lim, lim + 1):
            for dz in range(-lim, lim + 1):
                if math.hypot(dx, dz) <= r + 0.4:
                    t.set((cx + dx, y0 - k, cz + dz), mat)
                    n += 1
    return n


# ---------------------------------------------------------------- 主函数

def island(t, r: int = 24, size: str = "mid", depth: int = None,
           roots: int = None, root_len: int = None, profile: str = "cone",
           seed: int = 0,
           amp: float = 0.40, aspect: float = None, rot: float = None,
           lean: float = None, sub_depth: int = 2, root_r: float = None,
           hill: int = None, dome: float = None, wave: float = None,
           lobes: int = 3, mat: dict = None, **_) -> dict:
    """**一座浮空岛。** `(0,0,0)` 是顶面中心，岛体往 `-Y` 长，根再往下。

    | 参数 | 作用 | 不传时的默认 |
    |---|---|---|
    | `r` | 顶面半径（岛半径）—— **只决定横截面** | 24 |
    | `size` | 尺寸档：`islet` / `mid` / `prime` / `major` | `mid`（见 `SIZE_CLASSES`） |
    | `depth` | 岛体厚度（**决定观感**，教训 6） | 按 `size` 查表，**与 `r` 无关** |
    | `roots` / `root_len` / `root_r` | 根系条数 / 长度 / 粗细 | 按 `size` 查表 / 0.13 × r（封顶 6，长度上限 0.55 × r） |
    | `profile` | 纵剖面：`cone` / `bulb` / `plate` | `cone` |
    | `amp` / `lobes` | 圆周扰动幅度 / 最低谐波阶数 | 0.40 / 3 |
    | `aspect` / `rot` / `lean` | 长宽比 / 长轴方向 / 下半段倾斜 | 1.15–1.60 / 0–180° / 0.18–0.40 |
    | `sub_depth` | 表层往下垫几层（垫到岛体首层为止） | 2 |
    | `mat` | 材质覆盖 `{top, sub, body, deep}` | grass / dirt / stone / deepslate |

    返回分项格数 `{"top", "sub", "body", "root"}`（和 `sky/terrain.py` 一致）。

    **`depth` 请走 `size` 档，不要按半径比例给。** 源头 `place_proto("mid", …)`
    的 `depth` 与 `r` 无关（seed=7 时 r=24 和 r=36 都是 45），"按比例给"
    会让小半径整体压扁 38%（这正是返工那一版的问题）。

    三个"不像程序生成"的形状参数（`aspect` / `rot` / `lean`）不传就按 seed 自动
    取：正圆 + 垂直锥体是模板库最容易被一眼看穿的破绽。`aspect` 管顶面轮廓，
    `lean` 管侧面剪影 —— 后者让岛像"被撕下来的一块"，而不是"插在架子上的陀螺"。
    """
    m = dict(MAT_DEFAULT)
    m.update(mat or {})
    top, sub, body, deep = m["top"], m["sub"], m["body"], m["deep"]
    cls = SIZE_CLASSES[size]

    if depth is None:
        depth = in_range(seed, cls["depth"][0], cls["depth"][1], 11)
    depth = max(sub_depth + 2, int(depth))      # 首层必须存在，否则表层没着落
    if roots is None:
        roots = in_range(seed, cls["roots"][0], cls["roots"][1], 12)
    if root_len is None:
        root_len = in_range(seed, cls["root_len"][0], cls["root_len"][1], 13)
    if aspect is None:
        aspect = 1.15 + 0.45 * unit(seed, 51)
    if rot is None:
        rot = unit(seed, 52) * 180.0
    if lean is None:
        lean = 0.18 + 0.22 * unit(seed, 62)
    if root_r is None:
        # **封顶 6**：不封的话大陆级的根会到 22 格粗，一个根吃掉 16 万方块。
        # 系数 0.13 是源头的取值。第一次提取时我按渲图把它改到 0.068，结果
        # 根的分项只剩源头的 1/3（r=24：340 vs 1283 格），渲出来是"悬在
        # 下面的细尖刺" —— 细长悬空的根会读成"断开的东西"，比什么都伤观感。
        root_r = min(6.0, max(2.0, r * 0.13))
    # 根长跟着半径封顶，**而且必须短**（教训 7）。1.9 倍时岛下面拖出一根比身长
    # 还长的细绳，整座岛读成"倒过来的水滴"；1.1 倍时根仍占全高一半，渲出来是
    # "绿盘子 + 一把黑尖刺"。**0.55 倍**才是"块状空岛底下几个短根桩"。
    # 注意这里**不要 `int()` 截断**：源头的上限是个浮点（r=24 → 13.2），
    # 截成 13 会让主根少一格（`int(13.2*1.15*1.2)=18` vs `int(13*1.15*1.2)=17`），
    # 根分项从 1283 掉到 1182、总高从 68 掉到 67。整数化留给 `_cone_root`。
    root_len = min(root_len, r * 0.55)

    prof = PROFILES[profile]
    n = {"top": 0, "sub": 0, "body": 0, "root": 0}

    # **一张**形状表通到底。层与层之间只靠"相位缓慢扭转"和"半径低频起伏"区分。
    tab = shape_table(seed, amp, lobes, aspect=aspect, rot=rot)

    # ---- 岛体首层（`dy = dy0`）的半径：表层必须**精确**落在它里面。
    #
    # 这一条算式和下面岛体循环里那一句**逐字相同**（`dy0 * 0.22`，不是
    # `tt0 * depth * 0.22` —— 后者会差 1e-16，边界格可能被判反）。
    dy0 = sub_depth + 1
    tt0 = dy0 / depth
    wave_p = unit(seed, 210) * TAU
    amp_w = 0.11 if wave is None else wave
    rr0 = r * profile_at(prof, tt0) * (1.0 + amp_w * math.sin(dy0 * 0.22 + wave_p))

    # ---- 顶面：有起伏的表层。用**同一张表**（否则草皮轮廓会和岛体对不上，
    # 宽出来的一圈就成了"盖在岛上的盘子"），而且轮廓要**收在岛体首层里面**。
    hill = max(2, min(3, int(r / 14))) if hill is None else hill
    dome = max(2.0, r * 0.16) if dome is None else dome
    skin = _top_skin(t, r, tab, top, sub, seed, hill=hill,
                     sub_depth=sub_depth, dome=dome,
                     clip=rr0, clip_ph=dy0 * TWIST)
    n["top"] += skin["top"]
    n["sub"] += skin["sub"]

    # ---- 岛体：实心、连续收分，只有**缓慢连续**的两个变化
    lean_a = unit(seed, 61) * TAU
    lx, lz = math.cos(lean_a), math.sin(lean_a)
    lean_mag = r * lean
    for dy in range(dy0, depth + 1):
        tt = dy / depth
        # (1) 半径的低频起伏（周期约 28 层）—— 侧面唯一的"不规则"来源。
        # 幅度别太大，否则侧面会出现一圈圈规整的横向环带。
        rr = r * profile_at(prof, tt) * (1.0 + amp_w * math.sin(dy * 0.22 + wave_p))
        if rr < 1.0:
            break
        # (2) 整体朝一侧倾斜，越往下越偏（平滑，不是抖动）
        d = lean_mag * tt * tt
        # 深板岩只占最底下 20%。给到 38% 时下半身整体发黑，加上同样发黑的根，
        # 整座岛读成"绿盘子 + 一把黑尖刺"（教训 7 的第二个元凶）。
        n["body"] += _disc_w(t, -dy, rr, tab, body if tt < 0.80 else deep,
                             int(round(d * lx)), int(round(d * lz)), dy * TWIST)

    # ---- 岩块凸起：贴着体表再粘几坨小岩体。
    #
    # **这才是"块状"读感的关键。** 只调圆周扰动的话，轮廓仍然是回转体 ——
    # 顶多边缘更皱一点，整体还是"水滴 / 蘑菇"。真正让它像岩体的是几坨尺寸
    # 5–15 格的岩块从体表鼓出来、互相咬合。
    n_out = max(2, min(6, int(r / 12)))
    for i in range(n_out):
        tt = 0.28 + 0.58 * unit(seed, 500 + i)
        y = int(-depth * tt)
        rr = r * profile_at(prof, tt)
        a = unit(seed, 600 + i) * TAU
        d = lean_mag * tt * tt
        n["body"] += _blob(
            t, int(round(rr * math.cos(a) + d * lx)), y,
            int(round(rr * math.sin(a) + d * lz)),
            r * (0.16 + 0.20 * unit(seed, 700 + i)),
            mat=body if tt < 0.72 else deep)

    # ---- 根系：**一根主根 + 若干细支根**，从**倾斜后的**底端分出去。
    # 粗细一致的话，从侧面看是"四条桌腿"而不是根系 —— 第一版就是这个毛病。
    if roots > 0 and root_len > 0:
        tip = -depth - 2
        tox, toz = int(round(lean_mag * lx)), int(round(lean_mag * lz))
        base_r = max(2.0, r * 0.42)
        phase = unit(seed, 21) * TAU
        for i in range(int(roots)):
            a = phase + TAU * i / roots
            x0 = base_r * math.cos(a) + tox
            z0 = base_r * math.sin(a) + toz
            main = (i == 0)
            rr = root_r * (2.0 if main else 0.95) * (0.8 + 0.45 * unit(seed, 40 + i))
            ln = root_len * (1.15 if main else 0.8)
            n["root"] += _cone_root(
                t, x0, z0, tip,
                in_range(seed, int(ln * 0.75), int(ln * 1.2), 30 + i),
                rr, -(x0 - tox) * 0.28, -(z0 - toz) * 0.28, deep)
    return n


def count_in(w, bx) -> int:
    """数一个包围盒里有多少格 —— 多个变体建在**同一个 `World`** 里时要用它，
    `w.count()` 会把邻居也算进来。"""
    return sum(1 for p in w.cells
               if bx.lo.x <= p.x <= bx.hi.x
               and bx.lo.y <= p.y <= bx.hi.y
               and bx.lo.z <= p.z <= bx.hi.z)


# ---------------------------------------------------------------- 自检

#: 自检半径：小到几秒跑完，又大到足够暴露"表层悬空 / 确定性失效"。
CHECK_R = 20


def selfcheck(r: int = CHECK_R, seed: int = 7) -> list:
    """轻量自检：**建得出来 / 同 seed 逐格一致 / E0-W1 0-W2 0**。返回问题列表。

    `tests/doc_examples.py` 直接调这个（空列表 = 通过）。

    两条值得单独说的：

    * 确定性**必须比 `{pos: block.key()}`** —— `Block` 没有 `__eq__`，直接比
      字典里的 `Block` 对象比的是身份，**恒不相等**，会报一条假的"确定性失效"。
    * 第二次建之前把第一个 `World` 丢掉（先抠出签名再 del）：`World._undo`
      只增不减，两个世界同时活着会把这个进程直接吃掉，而且**一条 traceback
      都没有**（症状是"静默死亡、退出码 1"）。
    """
    bad = []
    sig = None
    for i in range(2):
        w = World(seed=seed)
        with w.frame(at=(0, 64, 0)) as f:
            island(f, r=r, seed=seed)
        cur = {p: b.key() for p, b in w.cells.items()}
        if not cur:
            return [f"r={r}: 一格没建出来"]
        if i == 0:
            sig = cur
            iss = w.lint()
            errs = [x for x in iss if x.level == "Error"]
            if errs:
                bad.append(f"lint Error {len(errs)} 条，例：{errs[0]}")
            for code in ("W1", "W2"):
                hit = [x for x in iss if x.code == code]
                if hit:
                    bad.append(f"{code} 共 {len(hit)} 条，例：{hit[0]}")
        elif cur != sig:
            bad.append("同 seed 两次建造结果不一致 —— 确定性失效")
        del w, cur

    # 重力材质：表层只要有一列下探不到岛体首层，就会报一片 W1。
    for mat in (dict(top="red_sand", sub="red_sand"),
                dict(top="sand", sub="sand"),
                dict(top="gravel", sub="gravel")):
        w = World(seed=seed)
        with w.frame(at=(0, 64, 0)) as f:
            island(f, r=r, seed=seed, mat=mat)
        hit = [x for x in w.lint() if x.code == "W1"]
        if hit:
            bad.append(f"{mat['top']} 材质 {len(hit)} 处悬空，例：{hit[0]}")
        del w

    # 对齐源头：只查 r=24 / 36 两档（r=55 一座 30 万格、4 秒，太重，
    # 留给 `main()` 打全表）。这一条是**防"又把它压扁了"**的闸。
    for msg in align_table(r_list=(24, 36), verbose=False):
        bad.append(msg)
    return bad


# ---------------------------------------------------------------- 对齐源头

#: `sky/terrain.py` 的 `place_proto(f, "mid", radius=r, seed=7)` 实测值。
#:
#: **为什么是写死的常数**：示例不许碰 sky 那套模块（硬门槛：一个 sky 的
#: import 都不许有），所以没法现场重算。这四条
#: 是提取时逐座量出来的基准，`align_table()` 拿它当回归闸 —— 一旦有人又把
#: `depth` 改成跟半径挂钩（第一次提取就是这么压扁的），这几条会立刻报出来。
#: `root` 只对 r=24/36 记（源头把 top/sub 合计算进 `top`，只有 root 能对）。
ALIGN_REF = {
    16: dict(cells=22_716, h=61, w=36, ratio=1.69, root=390),
    24: dict(cells=51_714, h=68, w=54, ratio=1.26, root=1283),
    36: dict(cells=122_059, h=78, w=79, ratio=0.99, root=3931),
    55: dict(cells=299_807, h=81, w=121, ratio=0.67, root=6344),
}

#: 对齐容差（源头 vs 示例）。示例有两处**故意的**修正（表层收进岛体首层、
#: 地表下界钉在 `-sub_depth`），实测影响在 0.1% 量级，所以这套容差留得很宽。
ALIGN_TOL = dict(cells=0.10, h=0.05, ratio=0.08, root=0.10)


def measure(r: int, seed: int = 7, **kw) -> dict:
    """建一座岛，量出**对齐用的五个数**（格数 / 总高 / 总宽 / 高宽比 / 根分项）。"""
    w = World(seed=seed)
    with w.frame(at=(0, 200, 0)) as f:
        res = island(f, r=r, seed=seed, **kw)
    b = w.bounds()
    h = b.hi.y - b.lo.y + 1
    width = max(b.hi.x - b.lo.x, b.hi.z - b.lo.z) + 1
    out = dict(cells=w.count(), h=h, w=width, ratio=h / width, root=res["root"])
    del w                                   # `World._undo` 只增不减，见 selfcheck
    return out


def align_table(r_list=(16, 24, 36, 55), seed: int = 7, verbose: bool = True) -> list:
    """逐档量出 `island()` 与源头 `ALIGN_REF` 的差，返回**超差**的说明（空 = 通过）。

    `--variants` 和 `selfcheck()` 都会打这张表 —— 观感的根因是数值，
    数值一漂，图就会跟着塌，而图塌了要人眼才看得出来。
    """
    bad = []
    if verbose:
        print(f"  对齐源头：sky/terrain.py 的 place_proto('mid', radius=r, seed={seed})")
        print(f"  （容差：格数 ±10% / 总高 ±5% / 高宽比 ±0.08 / 根分项 ±10%；"
              f"`示例/源头`）")
    for r in r_list:
        ref = ALIGN_REF[r]
        got = measure(r, seed)
        dh = (got["h"] - ref["h"]) / ref["h"]
        dc = (got["cells"] - ref["cells"]) / ref["cells"]
        dr = got["ratio"] - ref["ratio"]
        dk = abs(got["root"] - ref["root"]) / max(1, ref["root"])
        if verbose:
            print(f"    r={r:<3d} 格数 {got['cells']:>8,d}/{ref['cells']:<8,d}"
                  f"({dc:+.1%})  高 {got['h']:>3d}/{ref['h']:<3d}"
                  f"({dh:+.1%})  高宽比 {got['ratio']:.2f}/{ref['ratio']:.2f}"
                  f"  根 {got['root']:>5d}/{ref['root']:<5d}")
        if abs(dc) > ALIGN_TOL["cells"]:
            bad.append(f"r={r}: 格数 {got['cells']:,} vs 源头 {ref['cells']:,}"
                       f"（{dc:+.1%}，超 ±10%）")
        if abs(dh) > ALIGN_TOL["h"]:
            bad.append(f"r={r}: 总高 {got['h']} vs 源头 {ref['h']}"
                       f"（{dh:+.1%}，超 ±5%）")
        if abs(dr) > ALIGN_TOL["ratio"]:
            bad.append(f"r={r}: 高宽比 {got['ratio']:.2f} vs 源头 {ref['ratio']:.2f}"
                       f"（{dr:+.2f}，超 ±0.08）")
        if dk > ALIGN_TOL["root"]:
            bad.append(f"r={r}: 根分项 {got['root']} vs 源头 {ref['root']}"
                       f"（{dk:+.1%}，超 ±10%）")
    return bad


# ---------------------------------------------------------------- 参数变体

#: 主图 / 变体的默认参数 = `island()` 的默认半径 24 + 对齐表用的 seed 7。
#: 于是 `python examples/island.py` 渲出来的就是**源头的基准那一座**
#: （`place_proto("mid", radius=24, seed=7)`），可以直接和基准图对照。
DEMO_R = 24
DEMO_SEED = 7

#: 一次渲一排的变体表 —— 把"先横向对比再动代码"固化成可复现的东西（教训 8）。
#: 每组只改一个量，标签直接写进文件名。
#:
#: 薄/厚两档用**绝对 `depth`**（`mid` 档在 seed=7 下默认 45），不用
#: "× r" —— 厚度本来就与半径无关（见 `SIZE_CLASSES`），写成比例会把
#: "厚度"和"横截面"两件事搅在一起。25 / 63 就是 45 的 0.55× / 1.40×。
VARIANTS = [
    ("1_base", dict(), "基线：amp 0.40 / 档位默认 depth / lobes 3"),
    ("2_amp0.70", dict(amp=0.70), "扰动太大：边缘开始碎成锯齿"),
    ("3_amp0.18", dict(amp=0.18), "扰动太小：读成'压扁的圆'（教训 5）"),
    ("4_thin_d25", dict(depth=25), "薄（0.55×档位厚度）：'薄盖 + 一条腿'（教训 6）"),
    ("5_thick_d63", dict(depth=63), "厚（1.40×档位厚度）：才像被撕下来的岩块"),
    ("6_lobes2", dict(lobes=2), "谐波只有两个：轮廓又变回圆"),
]


def default_depth(size: str = "mid", seed: int = 0) -> int:
    """该尺寸档在 `seed` 下推出的厚度 —— 变体表用它来标注"实际用了多厚"。"""
    lo, hi = SIZE_CLASSES[size]["depth"]
    return in_range(seed, lo, hi, 11)


def render_variants(r: int = 24, seed: int = DEMO_SEED):
    """把 `VARIANTS` 一次建在**同一张图**里（一排），再各自裁一张单图。

    一排六座共用一次建造：每座套 `w.region(...)`，`region_of().box` 就是它
    自己的取景框 —— 所以 N 张单图 + 1 张对比图只花一次建模的钱。
    返回 `(对比图路径, [(标签, 参数, 说明, 厚度, 格数, 单图路径), ...])`。
    """
    os.makedirs(OUT_DIR, exist_ok=True)
    gap = int(r * 4.0)
    top = 80
    w = World(seed=seed)
    boxes, rows = {}, []
    for i, (label, kw, note) in enumerate(VARIANTS):
        kw = dict(kw)
        with w.region(f"variant_{i}"):
            with w.frame(at=(i * gap, top, 0)) as f:
                island(f, r=r, seed=seed, **kw)
        bx = w.region_of(f"variant_{i}").box
        boxes[label] = bx
        rows.append((label, kw, note, int(kw.get("depth", default_depth("mid", seed))),
                     count_in(w, bx)))

    tw = max(1.5, 60.0 / r)
    row = w.image.save(os.path.join(OUT_DIR, "variants_row.png"), tw=tw, bh=tw)
    shots = []
    for label, kw, note, depth, cells in rows:
        p = w.image.save(os.path.join(OUT_DIR, f"variant_{label}.png"),
                         bx=boxes[label], tw=max(5.0, 160.0 / r),
                         bh=max(5.0, 160.0 / r))
        shots.append((label, kw, note, depth, cells, p))
    return row, shots


def variants_table(r: int = 24, seed: int = DEMO_SEED) -> list:
    """只算格数、不渲图 —— 给自检/报告用。返回 `(标签, 厚度, 格数, 说明)`。"""
    base = default_depth("mid", seed)
    out = []
    for label, kw, note in VARIANTS:
        w = World(seed=seed)
        with w.frame(at=(0, 80, 0)) as f:
            island(f, r=r, seed=seed, **dict(kw))
        out.append((label, int(kw.get("depth", base)), w.count(), note))
        del w
    return out


# ---------------------------------------------------------------- 入口


def main() -> int:
    argv = sys.argv[1:]
    variants = "--variants" in argv
    r = DEMO_R
    if "--r" in argv:
        r = int(argv[argv.index("--r") + 1])
    os.makedirs(OUT_DIR, exist_ok=True)

    print("=" * 74)
    print("浮空岛 —— 程序化地形示例（机制来自 sky/terrain.py，本文件不依赖 sky）")
    print("=" * 74)

    bad = selfcheck()
    print(f"自检 r={CHECK_R}: "
          + ("✓ 建得出来 / 同 seed 逐格一致 / E0 W1 0 W2 0 / 重力材质无悬空"
             if not bad else f"✗ {len(bad)} 条"))
    for m in bad:
        print("   -", m)
    print()

    if variants:
        print(f"参数变体（r={r}，seed={DEMO_SEED}）—— 渲一排横向对比：")
        print(f"  {'变体':16s} {'厚度':>6s} {'格数':>8s}  说明")
        for label, body_h, cells, note in variants_table(r=r):
            print(f"  {label:16s} {body_h:>6,d} {cells:>8,d}  {note}")
        print()
        row, shots = render_variants(r=r)
        print(f"  对比图 {row}  ({os.path.getsize(row):,} 字节)")
        for label, kw, note, body_h, cells, p in shots:
            print(f"  单图 {os.path.basename(p):32s} {cells:>8,d} 格  {note}")
        print()
        print("  看图顺序：先看 variants_row.png 找'最像岩体'的那一列，")
        print("  再点开对应单图看细节。**别跳过这一步去改代码。**")
        print()
        print("  再跑一次对齐表： python -c \"import examples.island as i; "
              "i.align_table()\"")
        return 1 if bad else 0

    # ---- 主图：`island()` 的默认参数（= 源头 place_proto("mid", radius=24)）
    align_table()
    print()
    w = World(seed=DEMO_SEED)
    with w.frame(at=(0, 240, 0)) as f:
        res = island(f, r=r, seed=DEMO_SEED)
    iss = w.lint()
    counts = Counter(x.code for x in iss)
    tw = max(3.0, 300.0 / r)
    p = w.image.save(os.path.join(OUT_DIR, "island.png"), tw=tw, bh=tw)
    b = w.bounds()
    print(f"主图 r={r} seed={DEMO_SEED}  {w.count():,} 格（唯一格）  分项 {res}")
    print(f"  （分项之和略大于唯一格：表层与岛体首层有几十格重叠，见 align_table）")
    print(f"  包围盒 {b}   高/宽={(b.hi.y - b.lo.y + 1) / (b.hi.x - b.lo.x + 1):.2f}")
    print(f"  lint {dict(counts)}   E="
          f"{sum(1 for x in iss if x.level == 'Error')}")
    print(f"  图 -> {p}  ({os.path.getsize(p):,} 字节)")
    print()
    print("想看「好不好看」的横向对比： python examples/island.py --variants")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
