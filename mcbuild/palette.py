"""配色：整栋建筑换一套材质。

迭代速度的瓶颈往往不是建模而是**换配色**——改一遍脚本里的材质常量太慢。
这里做两件事：

1. 内置材质家族表（``FAMILIES``），``w.repaint(family=("stone","quartz"))``
   按家族内的**色阶顺序**整体映射，连 ``_stairs`` / ``_slab`` 后缀一起带上。
2. 显式映射（dict 或 callable），用于精细控制。

    w.repaint(family=("stone", "quartz"))        # 石材整体换成石英
    w.repaint({"stone_bricks": "deepslate_tiles"})   # 只换一种
    w.repaint(lambda b: "gold_block" if b.name.endswith("_bricks") else None)

映射时**继承原方块的 blockstate**（朝向 / half / type），
所以楼梯换了材质仍然是楼梯，朝向不丢。
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

from .block import Block, make

# ---------------------------------------------------------------- 材质家族
# 每个家族内按「从暗到亮 / 从粗到精」的常见色阶排列，
# 换配色时按索引比例映射（家族长度不同也能对上）。

FAMILIES: Dict[str, List[str]] = {
    "stone": ["stone", "cobblestone", "mossy_cobblestone", "stone_bricks",
              "mossy_stone_bricks", "chiseled_stone_bricks", "smooth_stone"],
    "deepslate": ["deepslate", "cobbled_deepslate", "polished_deepslate",
                  "deepslate_bricks", "deepslate_tiles", "chiseled_deepslate"],
    "blackstone": ["blackstone", "polished_blackstone", "polished_blackstone_bricks",
                   "chiseled_polished_blackstone", "gilded_blackstone"],
    "quartz": ["quartz_block", "quartz_bricks", "chiseled_quartz_block",
               "smooth_quartz", "quartz_pillar"],
    "sandstone": ["sandstone", "cut_sandstone", "chiseled_sandstone",
                  "smooth_sandstone"],
    "red_sandstone": ["red_sandstone", "cut_red_sandstone",
                      "chiseled_red_sandstone", "smooth_red_sandstone"],
    "bricks": ["bricks", "nether_bricks", "red_nether_bricks"],
    "prismarine": ["prismarine", "prismarine_bricks", "dark_prismarine"],
    "copper": ["cut_copper", "exposed_cut_copper", "weathered_cut_copper",
               "oxidized_cut_copper"],
    "concrete": ["black_concrete", "gray_concrete", "light_gray_concrete",
                 "white_concrete", "brown_concrete", "red_concrete",
                 "orange_concrete", "yellow_concrete", "lime_concrete",
                 "green_concrete", "cyan_concrete", "light_blue_concrete",
                 "blue_concrete", "purple_concrete", "magenta_concrete",
                 "pink_concrete"],
    "wool": ["black_wool", "gray_wool", "light_gray_wool", "white_wool",
             "brown_wool", "red_wool", "orange_wool", "yellow_wool",
             "lime_wool", "green_wool", "cyan_wool", "light_blue_wool",
             "blue_wool", "purple_wool", "magenta_wool", "pink_wool"],
    "terracotta": ["black_terracotta", "gray_terracotta", "light_gray_terracotta",
                   "white_terracotta", "brown_terracotta", "red_terracotta",
                   "orange_terracotta", "yellow_terracotta", "lime_terracotta",
                   "green_terracotta", "cyan_terracotta", "light_blue_terracotta",
                   "blue_terracotta", "purple_terracotta", "magenta_terracotta",
                   "pink_terracotta"],
    "oak": ["oak_planks", "oak_log", "stripped_oak_log", "oak_wood"],
    "spruce": ["spruce_planks", "spruce_log", "stripped_spruce_log", "spruce_wood"],
    "birch": ["birch_planks", "birch_log", "stripped_birch_log", "birch_wood"],
    "dark_oak": ["dark_oak_planks", "dark_oak_log", "stripped_dark_oak_log",
                 "dark_oak_wood"],
}

# 换材质时要跟着一起换的后缀
_SUFFIXES = ("_stairs", "_slab", "_wall", "_fence", "_fence_gate", "_trapdoor", "_door")

# 家族内换配色的匹配关键词，**按特异性排序**（越靠前越先试）。
# 纯按索引比例对齐在家族长度不同时会错位：7 个成员的 stone 家族第 4 项
# （stone_bricks）会落到 5 个成员的 quartz 家族第 3 项（chiseled_quartz_block）。
# 先按关键词找同名变体，找不到再退回索引对齐。
_KEYWORDS = ("chiseled", "cracked", "mossy", "smooth", "polished", "tiles",
             "cut", "pillar", "bricks", "cobble", "planks", "log",
             "terracotta", "concrete", "wool")


def _match(name: str, dst: List[str], i: int, n: int) -> str:
    for kw in _KEYWORDS:
        if kw in name:
            cands = [d for d in dst if kw in d]
            if cands:
                return cands[0]
    if n <= 1:
        return dst[0]
    return dst[round(i * (len(dst) - 1) / (n - 1))]


def family_map(src: str, dst: str) -> Dict[str, str]:
    """生成两个家族之间的映射表。

    先按关键词找同名变体（``stone_bricks`` → ``quartz_bricks``、
    ``smooth_stone`` → ``smooth_quartz``），找不到才按色阶索引比例对齐。
    """
    if src not in FAMILIES:
        raise KeyError(f"未知材质家族 {src!r}（可用: {sorted(FAMILIES)}）")
    if dst not in FAMILIES:
        raise KeyError(f"未知材质家族 {dst!r}（可用: {sorted(FAMILIES)}）")
    a, b = FAMILIES[src], FAMILIES[dst]
    return {name: _match(name, b, i, len(a)) for i, name in enumerate(a)}


def lookup(block: Block, mapping: Dict[str, str]) -> Optional[str]:
    """在映射表里查一个方块的新 id（带后缀的方块会拆开再拼回去）。"""
    name = block.name
    if name in mapping:
        return mapping[name]
    if block.id in mapping:
        return mapping[block.id]
    for suf in _SUFFIXES:
        if name.endswith(suf):
            base = name[: -len(suf)]
            if base in mapping:
                return mapping[base] + suf
    return None


def retexture(block: Block, mapping: Dict[str, str]) -> Optional[Block]:
    """把方块换成映射后的新方块，尽量继承原 blockstate。"""
    new_id = lookup(block, mapping)
    if new_id is None:
        return None
    try:
        return make(new_id, **block.props())
    except Exception:
        return make(new_id)
