"""等距投影 PNG 渲染（纯标准库，不依赖第三方）。

ASCII 渲染（`render.py`）擅长回答"几何对不对"，但回答不了"好不好看"——
配色是否协调、层次有没有被压死、云海像不像云。本模块把 `World` 渲成 PNG，
让**多模态预览**成为反馈闭环里的一环。

设计要点：
  * 相机在 +x/+y/+z 方向俯视，可见面为 顶面 / +z 面（南）/ +x 面（东）
  * 2:1 等距投影：``px = (x-z)*tw/2``、``py = (x+z)*tw/4 - y*bh``
  * 画家算法：按 ``(x+z, y)`` 升序绘制，远的先画
  * 面剔除：整格方块的邻居非空则剔除该面
  * 子格形状：按**方块族**作画，栏杆细柱 / 薄板窗 / 灯笼小盒 / 半砖……
  * 分面明暗：顶面 1.0 / 南面 0.78 / 东面 0.60，云近似漫反射，再叠一层高度天光
  * PNG 手写：``zlib`` + ``struct`` + ``crc32``，零第三方依赖

用法::

    w.image.save("out/hero.png")                       # 整场
    w.image.save("out/pav.png", bx=w.stage_box("pavilion"))
    w.image.save("out/pav.png", bx=w.stage_box("pavilion"), tw=12, bh=12)
    w.image.preview("out/hero.png")                    # 存完尝试调用系统查看器

颜色默认走**真实贴图色表**（``data/colors.json.gz``，1177 个方块，由
``tools/build_colors.py`` 从游戏贴图算出来），手写调色板只作兜底。
想改某个材质用 ``w.image.color("oak_planks", (162, 130, 78))``；
数据文件缺失时会自动退回手写表，不会报错。
"""

from __future__ import annotations

import gzip
import json
import math
import os
import struct
import subprocess
import sys
import zlib
from operator import itemgetter
from typing import Dict, List, Optional, Tuple

from .block import Fam, classify, is_solid
from .vec import Box, V, box

RGB = Tuple[int, int, int]

# ============================================================ 调色板

#: 默认调色板：方块名（不含 `minecraft:` 前缀）-> 近似 RGB。
#: 这是**手工取样的近似值**，只求读图时能分辨材质，不追求与游戏内完全一致。
DEFAULT_PALETTE: Dict[str, RGB] = {
    # 石质
    "stone": (126, 126, 126), "stone_bricks": (122, 122, 118),
    "chiseled_stone_bricks": (116, 116, 110), "cracked_stone_bricks": (112, 112, 106),
    "mossy_stone_bricks": (110, 124, 96), "smooth_stone": (158, 158, 158),
    "mossy_cobblestone": (106, 122, 90), "cobblestone": (122, 122, 122),
    "andesite": (139, 139, 139), "diorite": (204, 204, 204),
    "granite": (154, 110, 92), "tuff": (108, 108, 100),
    "deepslate": (80, 80, 83), "deepslate_bricks": (74, 74, 78),
    "blackstone": (42, 36, 40), "polished_blackstone": (52, 46, 50),
    "end_stone": (219, 222, 158),
    # 土石
    "dirt": (134, 107, 74), "grass_block": (107, 160, 82),
    "moss_block": (89, 125, 58), "moss_carpet": (93, 130, 62),
    "gravel": (131, 127, 123), "sand": (219, 207, 163),
    "sandstone": (216, 203, 155), "snow_block": (240, 245, 247),
    # 深色橡木（中式木构主力）
    "dark_oak_planks": (66, 44, 24), "dark_oak_log": (59, 39, 22),
    "dark_oak_stairs": (66, 44, 24), "dark_oak_slab": (70, 47, 26),
    "dark_oak_fence": (64, 42, 23), "dark_oak_door": (74, 50, 28),
    "dark_oak_trapdoor": (70, 47, 26),
    # 其它木
    "oak_planks": (162, 130, 78), "oak_log": (109, 85, 50),
    "oak_stairs": (162, 130, 78), "oak_slab": (162, 130, 78),
    "oak_fence": (160, 128, 76), "oak_door": (150, 118, 70),
    "spruce_planks": (114, 84, 48), "spruce_log": (60, 43, 22),
    "birch_planks": (192, 175, 121), "jungle_planks": (160, 115, 80),
    "acacia_planks": (168, 90, 50),
    "crimson_planks": (143, 58, 74), "crimson_fence": (122, 51, 64),
    "crimson_slab": (143, 58, 74),
    # 白色 / 玻璃
    "white_concrete": (207, 209, 208), "white_wool": (233, 236, 236),
    "light_gray_concrete": (158, 160, 159), "gray_concrete": (125, 125, 125),
    "black_concrete": (8, 10, 15), "red_concrete": (142, 33, 33),
    "glass_pane": (196, 226, 234), "glass": (198, 228, 236),
    "white_stained_glass": (222, 228, 230),
    "white_stained_glass_pane": (222, 228, 230),
    # 海晶（青绿琉璃瓦）
    "prismarine": (99, 171, 164), "prismarine_stairs": (99, 171, 164),
    "prismarine_slab": (99, 171, 164), "dark_prismarine": (53, 92, 85),
    "dark_prismarine_stairs": (53, 92, 85), "dark_prismarine_slab": (53, 92, 85),
    "sea_lantern": (201, 227, 214),
    # 金属 / 光源
    "gold_block": (247, 208, 60), "lantern": (240, 168, 80),
    "soul_lantern": (110, 200, 200), "glowstone": (206, 174, 106),
    "torch": (240, 200, 90), "wall_torch": (240, 200, 90),
    "chain": (58, 63, 69),
    # 植被
    "spruce_leaves": (47, 79, 44), "oak_leaves": (58, 95, 40),
    "dark_oak_leaves": (56, 82, 38), "azalea_leaves": (86, 122, 53),
    "cherry_leaves": (240, 184, 204), "cherry_log": (55, 37, 36),
    "pink_petals": (240, 168, 192), "allium": (196, 156, 216),
    "white_tulip": (238, 238, 238), "dandelion": (240, 224, 80),
    "poppy": (216, 60, 55), "azure_bluet": (232, 238, 228),
    "lily_of_the_valley": (240, 244, 240), "short_grass": (110, 160, 70),
    "fern": (96, 140, 62),
    "bricks": (150, 97, 83), "nether_bricks": (44, 21, 26),
    "quartz_block": (235, 229, 222), "obsidian": (20, 18, 29),
    "bookshelf": (117, 92, 55), "crafting_table": (124, 85, 52),
    "red_bed": (160, 40, 40), "oak_sign": (160, 128, 76),
}

#: 未登记方块的回退色（中性灰褐）。
DEFAULT_COLOR: RGB = (150, 140, 130)

#: 视作"云"的材质：明暗近似漫反射，侧面不压太暗。
CLOUD_KINDS = frozenset({
    "white_wool", "white_concrete", "snow_block",
    "light_gray_concrete", "white_stained_glass", "white_stained_glass_pane",
})

#: 视作"植被/花卉"的材质（小丛形状）。
_PLANT_KINDS = frozenset({
    "pink_petals", "allium", "white_tulip", "dandelion",
    "azure_bluet", "poppy", "lily_of_the_valley",
})
_GRASS_KINDS = frozenset({"short_grass", "fern"})

#: 整格形状 (x0, z0, x1, z1, y0, y1)，单位 = 格。
FULL = (0.0, 0.0, 1.0, 1.0, 0.0, 1.0)

# 默认背景：天空蓝渐变（上 -> 地平线）。纯白背景会让白云读作雪原。
SKY_TOP: RGB = (108, 158, 219)
SKY_HORIZON: RGB = (196, 220, 243)


# ============================================================ 取色 / 形状

# ------------------------------------------------------------ 真实贴图颜色
#
# `tools/build_colors.py` 从 Nucleation 的 blockpedia 提取：下载客户端 jar、
# 取方块贴图、算 alpha 加权平均色，再乘上生物群系色调。约 1000 个方块。
# 手写调色板没有的材质（绝大多数）就靠它 —— 之前一律落到 DEFAULT_COLOR。

_COLOR_CACHE: Optional[Dict[str, RGB]] = None
_COLOR_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "data", "colors.json.gz")


def texture_colors() -> Dict[str, RGB]:
    """真实贴图颜色表。数据文件缺失时返回空表（不影响其它功能）。"""
    global _COLOR_CACHE
    if _COLOR_CACHE is None:
        try:
            with gzip.open(_COLOR_FILE, "rt", encoding="utf-8") as f:
                raw = json.load(f)["colors"]
            _COLOR_CACHE = {
                k: (int(v[0]), int(v[1]), int(v[2]))
                for k, v in raw.items()
                if not k.startswith("@") and len(v) >= 3
            }
        except (OSError, ValueError, KeyError, TypeError):
            _COLOR_CACHE = {}
    return _COLOR_CACHE


#: 衍生方块去后缀后仍对不上的特例（Minecraft 命名不规则：`stone_brick_wall`
#: 的基础是 `stone_bricks` 而不是 `stone_brick`）
_INHERIT_FIX = {
    "stone_brick": "stone_bricks", "mossy_stone_brick": "mossy_stone_bricks",
    "cracked_stone_brick": "cracked_stone_bricks",
    "chiseled_stone_brick": "chiseled_stone_bricks",
    "deepslate_brick": "deepslate_bricks", "deepslate_tile": "deepslate_tiles",
    "brick": "bricks", "mud_brick": "mud_bricks",
    "nether_brick": "nether_bricks", "red_nether_brick": "red_nether_bricks",
    "polished_blackstone_brick": "polished_blackstone_bricks",
    "end_stone_brick": "end_stone_bricks", "tuff_brick": "tuff_bricks",
    "quartz_brick": "quartz_bricks", "prismarine_brick": "prismarine_bricks",
    "cut_copper": "copper_block", "waxed_cut_copper": "copper_block",
    "exposed_cut_copper": "exposed_copper",
    "waxed_exposed_cut_copper": "exposed_copper",
    "weathered_cut_copper": "weathered_copper",
    "waxed_weathered_cut_copper": "weathered_copper",
    "oxidized_cut_copper": "oxidized_copper",
    "waxed_oxidized_cut_copper": "oxidized_copper",
    "cut_sandstone": "sandstone", "cut_red_sandstone": "red_sandstone",
    "smooth_stone": "stone", "petrified_oak": "oak_planks",
    "bamboo_mosaic": "bamboo_planks", "iron": "iron_block",
    "copper": "copper_block",
}

#: 衍生方块后缀（长的排前面：`_fence_gate` 要先于 `_fence` 匹配）
_INHERIT_SUFFIX = ("_pressure_plate", "_fence_gate", "_trapdoor", "_stairs",
                   "_slab", "_wall", "_fence", "_button", "_door")


def inherit_candidates(name: str) -> List[str]:
    """衍生方块 -> 可能的基础材质名，按优先级。"""
    for suf in _INHERIT_SUFFIX:
        if name.endswith(suf) and len(name) > len(suf):
            base = _INHERIT_FIX.get(name[:-len(suf)], name[:-len(suf)])
            return [base, f"{base}_planks", f"{base}s", f"{base}_block"]
    return []


def _lum(c: RGB) -> float:
    """感知亮度（Rec.601）。"""
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


_IMPRESSION_CACHE: Optional[set] = None
#: 手写值比贴图平均色亮多少倍才算"印象色"
_IMPRESSION_RATIO = 1.35


def impression_colors() -> set:
    """手写表里那些**明显比贴图平均色亮**的材质名。

    贴图的 alpha 加权平均色对两类方块会失真：

    * **小物件 / 多彩贴图** —— 白郁金香被绿花蕊拉暗（238 → 133）、
      灯笼被暗部拉暗（179 → 96），平均下来都不像它本来的样子
    * **顶面与侧面用的是不同贴图** —— 草方块被侧面的土色拉暗
      （草绿 135 → 94），而我们渲染时看到的主要是顶面

    这些材质沿用手写表里的"印象色"更符合视觉。判据是亮度比，
    自动算出来，不用手工维护白名单。
    """
    global _IMPRESSION_CACHE
    if _IMPRESSION_CACHE is None:
        tc = texture_colors()
        out = set()
        for name, manual in DEFAULT_PALETTE.items():
            tex = tc.get(name)
            if tex is not None and _lum(manual) > _lum(tex) * _IMPRESSION_RATIO:
                out.add(name)
        _IMPRESSION_CACHE = out
    return _IMPRESSION_CACHE


def color_of(block, palette: Optional[Dict[str, RGB]] = None) -> RGB:
    """取方块颜色。查找顺序：

    1. ``palette`` 里**你显式设过**的（``w.image.color(name, rgb)``）—— 最高优先
    2. 真实表里会失真的那批（见 `impression_colors`）→ 用手写**印象色**
    3. **真实贴图颜色表**（1177 个方块，游戏贴图的 alpha 加权平均色）
    4. 手写 ``DEFAULT_PALETTE``（真实表没有的少数特例）
    5. 衍生方块**继承**基础材质（``oak_button`` → ``oak_planks``）
    6. ``DEFAULT_COLOR``

    第 3 步优先是有意的：真实色覆盖 1177 个方块，且对石材/木材/混凝土
    这些大面积材质与手写值基本一致（实测 stone、oak_planks 完全相同）。
    """
    if block.is_air:
        return DEFAULT_COLOR
    name = block.name

    if palette is not None:
        hit = palette.get(name)
        if hit is not None:
            return hit

    if name in impression_colors():
        return DEFAULT_PALETTE[name]

    tc = texture_colors()
    hit = tc.get(name)
    if hit is not None:
        return hit

    hit = DEFAULT_PALETTE.get(name)
    if hit is not None:
        return hit

    for cand in inherit_candidates(name):
        hit = (palette.get(cand) if palette is not None else None) \
            or tc.get(cand) or DEFAULT_PALETTE.get(cand)
        if hit is not None:
            return hit
    return DEFAULT_COLOR


def shade_of(block) -> Tuple[float, float, float]:
    """(顶面, 南面, 东面) 明暗系数。云是漫反射的，侧面不该压太暗。"""
    if block.name in CLOUD_KINDS:
        return 1.0, 0.90, 0.80
    return 1.0, 0.78, 0.60


def shape_of(block, world=None, pos=None) -> tuple:
    """按方块族给子格形状 ``(x0, z0, x1, z1, y0, y1)``，单位 = 格。

    无法判断的族按整格。`world` / `pos` 只有薄板类（门 / 玻璃板）需要，
    用来判断板面朝向；不传时按沿 z 薄处理。
    """
    n = block.name
    st = block.props()
    fam = classify(block.id)

    if fam == Fam.FENCE or n == "chain":
        return (0.375, 0.375, 0.625, 0.625, 0.0, 1.0)

    if fam in (Fam.PANE, Fam.DOOR, Fam.TRAPDOOR):
        # 板面朝向：±x 有实心邻居 -> 板面朝 x（沿 z 薄）
        t = 0.4375
        if world is not None and pos is not None:
            if any(_solid_at(world, pos, d) for d in ((1, 0, 0), (-1, 0, 0))):
                return (0.0, t, 1.0, 1.0 - t, 0.0, 1.0)
        return (t, 0.0, 1.0 - t, 1.0, 0.0, 1.0)

    if fam == Fam.SLAB:
        return ((0.0, 0.0, 1.0, 1.0, 0.5, 1.0) if st.get("type") == "top"
                else (0.0, 0.0, 1.0, 1.0, 0.0, 0.5))

    if fam == Fam.STAIRS and st.get("half") == "top":
        return (0.0, 0.0, 1.0, 1.0, 0.5, 1.0)

    if n in ("lantern", "soul_lantern"):
        if st.get("hanging") == "true":
            return (0.3125, 0.3125, 0.6875, 0.6875, 0.15, 0.8)
        return (0.3125, 0.3125, 0.6875, 0.6875, 0.0, 0.65)

    if n.endswith("_carpet"):
        return (0.0, 0.0, 1.0, 1.0, 0.0, 0.0625)

    if n in _PLANT_KINDS:
        return (0.25, 0.25, 0.75, 0.75, 0.0, 0.6)
    if n in _GRASS_KINDS:
        return (0.2, 0.2, 0.8, 0.8, 0.0, 0.7)

    return FULL


def _solid_at(world, pos, d) -> bool:
    return not world.get((pos[0] + d[0], pos[1] + d[1], pos[2] + d[2])).is_air


# ============================================================ 光栅

class Canvas:
    """RGB 光栅 + 手写 PNG 编码。"""

    def __init__(self, w: int, h: int, bg: RGB = SKY_TOP,
                 horizon: RGB = SKY_HORIZON) -> None:
        self.w, self.h = int(w), int(h)
        self.buf = bytearray(self.w * self.h * 3)
        top, bot = bg, horizon
        for y in range(self.h):
            t = (y / max(1, self.h - 1)) ** 0.75
            r = int(top[0] + (bot[0] - top[0]) * t)
            g = int(top[1] + (bot[1] - top[1]) * t)
            b = int(top[2] + (bot[2] - top[2]) * t)
            self.buf[y * self.w * 3:(y + 1) * self.w * 3] = bytes((r, g, b)) * self.w

    def hspan(self, y: int, x0: float, x1: float, color: RGB) -> None:
        """填充一行里的水平区间（含端点，半像素对齐）。"""
        if y < 0 or y >= self.h:
            return
        a = max(0, int(math.floor(x0 + 0.5)))
        b = min(self.w - 1, int(math.ceil(x1 - 0.5)))
        if b < a:
            return
        i0 = (y * self.w + a) * 3
        i1 = (y * self.w + b + 1) * 3
        self.buf[i0:i1] = bytes(color) * (b - a + 1)

    def quad(self, pts, color: RGB) -> None:
        """扫描线填充任意凸/凹多边形（取每行的 min..max 跨度）。"""
        ys = [p[1] for p in pts]
        y0 = max(0, int(math.floor(min(ys) + 0.5)))
        y1 = min(self.h - 1, int(math.ceil(max(ys) - 0.5)))
        n = len(pts)
        for y in range(y0, y1 + 1):
            xs = []
            for i in range(n):
                ax, ay = pts[i]
                bx, by = pts[(i + 1) % n]
                if ay == by:
                    continue
                if (ay <= y <= by) or (by <= y <= ay):
                    xs.append(ax + (y - ay) / (by - ay) * (bx - ax))
            if len(xs) >= 2:
                self.hspan(y, min(xs), max(xs), color)

    def png_bytes(self) -> bytes:
        raw = bytearray()
        stride = self.w * 3
        for y in range(self.h):
            raw.append(0)                      # 每行滤波器 = None
            raw += self.buf[y * stride:(y + 1) * stride]

        def chunk(tag: bytes, data: bytes) -> bytes:
            return (struct.pack(">I", len(data)) + tag + data
                    + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

        return (b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", self.w, self.h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
                + chunk(b"IEND", b""))

    def save(self, path: str) -> str:
        d = os.path.dirname(os.path.abspath(path))
        if d:
            os.makedirs(d, exist_ok=True)
        with open(path, "wb") as f:
            f.write(self.png_bytes())
        return path


# ============================================================ 渲染器


class Image:
    """`w.image` —— 等距投影 PNG 渲染器。

    挂在 `World` 上（惰性构造），与 `w.render` 平级。
    """

    def __init__(self, world) -> None:
        self.w = world
        # **只存你显式设过的覆盖**（`w.image.color(...)`）。
        # 基础色由 color_of 按「真实贴图色 → 手写表 → 继承」解析，
        # 所以这里初始化成空表而不是 DEFAULT_PALETTE 的副本 —— 否则
        # 手写表会因为"在 palette 里"而永远压过真实贴图色。
        self.palette: Dict[str, RGB] = {}

    # ---------------------------------------------------------- 配置
    def color(self, name: str, rgb) -> "Image":
        """覆盖某个材质的颜色（链式）。**和 `w.camera` 共用**，设一次两边都生效。"""
        self.palette[name] = tuple(int(x) for x in rgb)   # type: ignore[assignment]
        return self

    def colors(self, mapping: Dict[str, tuple]) -> "Image":
        """批量登记颜色（链式）。"""
        for k, v in mapping.items():
            self.color(k, v)
        return self

    # ---------------------------------------------------------- 渲染
    def render(self, out: str, bx=None, tw: float = 8.0, bh: float = 8.0,
               bg: RGB = SKY_TOP, horizon: RGB = SKY_HORIZON,
               sky_gain: float = 0.10) -> str:
        """把世界（或 `bx` 区域）渲成 PNG，返回写出路径。

        ``bx`` 是**世界坐标闭区间**；只做范围过滤，不会切开跨界方块，
        取景时留一格余量。``tw`` 是每格的水平像素宽，``bh`` 是每格高度像素。
        """
        b = self._resolve_box(bx)
        if b is None:
            raise ValueError("空世界，无法渲染")
        return self._render_box(b, out, tw, bh, bg, horizon, sky_gain)

    def save(self, path: str, bx=None, **kw) -> str:
        """`render` 的别名。"""
        return self.render(path, bx=bx, **kw)

    def preview(self, path: str) -> str:
        """尽力用系统默认查看器打开图片（失败不抛，返回路径）。"""
        p = os.path.abspath(path)
        try:
            if sys.platform.startswith("win"):
                os.startfile(p)                       # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", p])
            else:
                subprocess.Popen(["xdg-open", p])
        except Exception:
            pass
        return p

    # ---------------------------------------------------------- 内部
    def _resolve_box(self, bx) -> Optional[Box]:
        if bx is None:
            return self.w.bounds()
        if isinstance(bx, str):                       # 锚点区域名
            return self.w.marks.boxes[bx]
        if isinstance(bx, Box):
            return bx
        return box(bx)

    def _render_box(self, b: Box, out: str, tw: float, bh: float,
                    bg: RGB, horizon: RGB, sky_gain: float) -> str:
        w = self.w
        tw2 = tw / 2.0
        th2 = tw2 / 2.0                           # 2:1 等距

        # 只遍历**有方块的格子**，不要遍历整个包围盒。
        #
        # 稀疏场景里两者能差几百倍：16 座岛合并后包围盒 2.3 亿格、实际方块只有 60 万。
        # 原写法 `for pos in b` 会对包围盒里每一格调一次 `w.get()`（实测 15.8 万方块
        # 触发 420 万次 get），而真正的光栅化只占总时间的 1.3% —— 瓶颈一直在这儿。
        # 只有当世界本身比盒子还稠密时才回退成扫盒，免得反过来更慢。
        cells = []
        if len(w.cells) <= b.volume() // 2:
            src = ((p, blk) for p, blk in w.cells.items() if p in b)
        else:
            src = ((p, w.get(p)) for p in b)
        for pos, blk in src:
            if blk.is_air:
                continue
            sh = shape_of(blk, w, pos)
            t_vis, s_vis, e_vis = self._visible_faces(w, pos, sh)
            if not (t_vis or s_vis or e_vis):
                continue
            # 排序键预先算进元组 —— 原写法 `sort(key=lambda ...)` 会为每格建一个 lambda
            cells.append(((pos.x + pos.z, pos.y), pos.x, pos.y, pos.z,
                          blk, sh, t_vis, s_vis, e_vis))

        if not cells:
            raise ValueError("区域内没有可见方块")
        # 画家算法：远的先画
        cells.sort(key=itemgetter(0))

        ymin = min(c[2] for c in cells)
        ymax = max(c[2] for c in cells)

        def px(x, z):
            return (x - z) * tw2

        def py(x, y, z):
            return (x + z) * th2 - y * bh

        xs = [px(c[1], c[3]) for c in cells]
        ys_lo = [py(c[1], c[2] + c[5][4], c[3]) for c in cells]
        ys_hi = [py(c[1], c[2] + c[5][5], c[3]) for c in cells]
        minx, maxx = min(xs) - tw, max(xs) + tw
        miny, maxy = min(ys_lo), max(ys_hi)
        # +2*tw 给取整留余量：只画一格时 maxy-miny 可能为负
        W = max(1, int(maxx - minx) + 2 * int(tw) + 3)
        H = max(1, int(maxy - miny) + 2 * int(bh) + 3)
        cv = Canvas(W, H, bg, horizon)

        def X(x, z):
            return px(x, z) - minx + 1

        def Y(x, y, z):
            return py(x, y, z) - miny + 1

        span = max(1, ymax - ymin)
        for (_key, x, y, z, blk, sh, t_vis, s_vis, e_vis) in cells:
            cr, cg, cb = color_of(blk, self.palette)
            kt, ks, ke = shade_of(blk)
            x0, z0, x1, z1, y0, y1 = sh
            gain = 1.0 + sky_gain * ((y - ymin) / span - 0.5) * 2

            # 三种色直接算出来。原写法在循环里 `def tint(k)` —— 每格建一个函数对象，
            # 每个面再调一次（实测 800 万次调用），纯属白烧。
            if t_vis:
                f = kt * gain
                cv.quad([(X(x + x0, z + z0), Y(x, y + y1, z + z0)),
                         (X(x + x1, z + z0), Y(x + x1, y + y1, z + z0)),
                         (X(x + x1, z + z1), Y(x + x1, y + y1, z + z1)),
                         (X(x + x0, z + z1), Y(x + x0, y + y1, z + z1))],
                        (min(255, int(cr * f)), min(255, int(cg * f)),
                         min(255, int(cb * f))))
            if s_vis:
                f = ks * gain
                cv.quad([(X(x + x0, z + z1), Y(x + x0, y + y0, z + z1)),
                         (X(x + x1, z + z1), Y(x + x1, y + y0, z + z1)),
                         (X(x + x1, z + z1), Y(x + x1, y + y1, z + z1)),
                         (X(x + x0, z + z1), Y(x + x0, y + y1, z + z1))],
                        (min(255, int(cr * f)), min(255, int(cg * f)),
                         min(255, int(cb * f))))
            if e_vis:
                f = ke * gain
                cv.quad([(X(x + x1, z + z0), Y(x + x1, y + y0, z + z0)),
                         (X(x + x1, z + z1), Y(x + x1, y + y0, z + z1)),
                         (X(x + x1, z + z1), Y(x + x1, y + y1, z + z1)),
                         (X(x + x1, z + z0), Y(x + x1, y + y1, z + z0))],
                        (min(255, int(cr * f)), min(255, int(cg * f)),
                         min(255, int(cb * f))))

        return cv.save(out)

    @staticmethod
    def _visible_faces(world, pos, sh) -> Tuple[bool, bool, bool]:
        """面剔除：只有整格满高的方块才可能被邻居遮住。"""
        x, y, z = pos
        x0, z0, x1, z1, y0, y1 = sh
        full_fp = (x1 - x0 > 0.99) and (z1 - z0 > 0.99)
        full_h = (y1 - y0) > 0.99
        full = full_fp and full_h

        t_vis = not (full and y1 > 0.99 and not world.get((x, y + 1, z)).is_air)
        s_vis = not (full and not world.get((x, y, z + 1)).is_air)
        e_vis = not (full and not world.get((x + 1, y, z)).is_air)
        return t_vis, s_vis, e_vis


__all__ = [
    "Image", "Canvas", "DEFAULT_PALETTE", "DEFAULT_COLOR",
    "CLOUD_KINDS", "SKY_TOP", "SKY_HORIZON",
    "color_of", "shade_of", "shape_of",
]
