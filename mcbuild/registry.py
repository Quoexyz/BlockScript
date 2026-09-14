"""方块注册表：存在性校验、属性定义、拼写建议、按名搜索。

数据来自 **prismarinejs/minecraft-data**（MIT），经 `schem-at/Nucleation` 的
blockpedia 提取，覆盖 Minecraft 1.21.x 的 **1196 个方块**（其中 797 个带属性定义）。
压缩后 16 KB，随库分发，仍是零第三方依赖。

**为什么要有它**：模型的世界知识里本来就有大量方块名，不该被手写的别名表限制。
但写错时必须能立刻发现 —— 以前 `w.set(pos, "oak_stairz")` 会静默通过，
按实心方块处理，错误留到游戏里才暴露。

    from mcbuild import registry

    registry.exists("oak_stairs")        # True
    registry.exists("oak_stairz")        # False
    registry.check("oak_stairz")
    #   "未知方块 'oak_stairz'；是否想写: oak_stairs / oak_stairs ..."

    registry.search("banner")            # 所有旗帜类方块名
    registry.states("oak_stairs")        # {'facing': [...], 'half': [...], ...}
    registry.defaults("oak_stairs")      # {'facing': 'north', 'half': 'bottom', ...}

非 `minecraft:` 命名空间（mod 方块）一律**放过**，不当错误。
"""

from __future__ import annotations

import gzip
import json
import os
from difflib import get_close_matches
from typing import Dict, List, Optional

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "data", "blocks.json.gz")
_DATA: Optional[dict] = None


def _data() -> dict:
    global _DATA
    if _DATA is None:
        with gzip.open(_PATH, "rt", encoding="utf-8") as f:
            _DATA = json.load(f)
    return _DATA


def blocks() -> Dict[str, dict]:
    """全部方块的原始条目（``name -> {states, defaults, label, hardness}``）。"""
    return _data()["blocks"]


def info() -> dict:
    """数据集来源与覆盖范围。"""
    d = _data()
    return {"source": d["source"], "minecraft": d["minecraft"],
            "count": d["count"]}


def norm(name) -> str:
    """规整成裸方块名（去命名空间、转小写、空格转下划线）。"""
    return str(name).strip().lower().replace(" ", "_").split(":")[-1]


def namespace(name) -> str:
    """取命名空间，没写前缀就当 minecraft。"""
    s = str(name).strip().lower()
    return s.split(":")[0] if ":" in s else "minecraft"


def exists(name) -> bool:
    """这个方块存在吗。非 minecraft 命名空间（mod）一律返回 True。"""
    if namespace(name) != "minecraft":
        return True
    return norm(name) in blocks()


def suggest(name, n: int = 5) -> List[str]:
    """按编辑距离给出拼写候选。"""
    base = norm(name)
    known = list(blocks())
    out = get_close_matches(base, known, n=n, cutoff=0.55)
    if not out and "_" in base:
        head = base.split("_")[0]
        out = [k for k in known if k.startswith(head)][:n]
    return out


def check(name) -> Optional[str]:
    """``None`` 表示没问题，否则返回一句诊断（含拼写候选）。

    可以直接喂给模型 —— 它看到候选就知道自己拼错了哪个词。
    """
    if namespace(name) != "minecraft":
        return None
    base = norm(name)
    if base in blocks():
        return None
    cands = suggest(base)
    if cands:
        return f"未知方块 {name!r}；是否想写: " + " / ".join(cands)
    return f"未知方块 {name!r}（表里没有相近的）"


def search(pattern) -> List[str]:
    """按子串搜索方块名。模型想找某一类方块时很方便::

        registry.search("banner")     # ['black_banner', ..., 'yellow_wall_banner']
        registry.search("_stairs")    # 所有楼梯
    """
    p = norm(pattern)
    return sorted(k for k in blocks() if p in k)


def states(name) -> Dict[str, Optional[List[str]]]:
    """属性定义：属性名 -> 合法取值列表（``None`` 表示布尔属性）。"""
    return (blocks().get(norm(name)) or {}).get("states", {})


def defaults(name) -> Dict[str, str]:
    """该方块的默认属性。"""
    return (blocks().get(norm(name)) or {}).get("defaults", {})


def label(name) -> Optional[str]:
    """英文显示名（``oak_stairs`` → ``oak stairs``）。"""
    return (blocks().get(norm(name)) or {}).get("label")


def unknowns(names) -> List[str]:
    """从一串方块名里挑出拼错的（去重、保序）。"""
    seen = set()
    out = []
    for n in names:
        if n in seen:
            continue
        seen.add(n)
        if check(n) is not None:
            out.append(n)
    return out
