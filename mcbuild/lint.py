"""校验规则。

用规则查比让模型自查可靠得多——模型自查会脑补自己写对。
E1（非法 blockstate）在写入时由 block.make 抛 BlockStateError，不在这里。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Set

from .block import AIR, Block, Fam, classify, is_solid
from .vec import CARDINAL_VEC, Box, V, box

SIDE_ATTACH = {
    "wall_torch", "soul_wall_torch", "redstone_wall_torch",
    "ladder", "vine", "glow_lichen",
    "wall_sign", "oak_wall_sign", "spruce_wall_sign", "birch_wall_sign",
    "wall_hanging_sign", "wall_banner",
}
HANG = {"lantern", "soul_lantern", "chain"}

# 重力方块：下方为空就会掉落
GRAVITY = {
    "sand", "red_sand", "gravel", "suspicious_sand", "dragon_egg",
    "anvil", "chipped_anvil", "damaged_anvil", "pointed_dripstone",
    "scaffolding", "white_concrete_powder", "black_concrete_powder",
}
# 需要下方支撑，否则会自己破坏掉落（可扩展）
NEEDS_SUPPORT = {
    "torch", "soul_torch", "redstone_torch",
    "rail", "powered_rail", "detector_rail", "activator_rail",
    "dandelion", "poppy", "blue_orchid", "allium", "azure_bluet",
    "red_tulip", "orange_tulip", "white_tulip", "pink_tulip",
    "oxeye_daisy", "cornflower", "lily_of_the_valley", "wither_rose",
    "brown_mushroom", "red_mushroom", "crimson_fungus", "warped_fungus",
    "sugar_cane", "cactus", "bamboo", "chorus_flower", "nether_sprouts",
    "dead_bush", "fern", "large_fern", "short_grass", "sea_pickle",
}
_NEEDS_SUPPORT_SUFFIX = ("_carpet", "_sapling", "_concrete_powder", "_bed")
LIGHTS = {
    "torch", "wall_torch", "soul_torch", "soul_wall_torch",
    "lantern", "soul_lantern", "glowstone", "sea_lantern", "shroomlight",
    "campfire", "soul_campfire", "jack_o_lantern", "beacon", "end_rod",
    "redstone_lamp", "candle", "lantern",
}
CONNECT_FAMILIES = (Fam.WALL, Fam.FENCE, Fam.PANE)


@dataclass(frozen=True)
class Issue:
    code: str
    level: str          # Error（必须修）/ Warn（建议修）/ Info（提示）
    pos: V
    block: Block
    msg: str

    def __str__(self) -> str:  # noqa: D105
        return f"{self.code} {self.level} {self.pos} {self.block.short()}  {self.msg}"


# 严重度顺序：Error 必须修 → Warn 建议修 → Info 只是提示
LEVEL_ORDER = {"Error": 0, "Warn": 1, "Info": 2}

# 位置落在**空气**上的告警码：W4 封闭空间 / W6 无光源。
# 它们的 pos 是封闭空间里的一个样本（空气格），而 region.cells 只记非空气格，
# 所以按坐标过滤时不能被 `pos in region.cells` 卡掉。
AIR_LOCATED_CODES = frozenset({"W4", "W6"})


def compute_connections(world, p: V, b: Block) -> Dict[str, str]:
    """按邻居计算连接类属性（wall / fence / pane）。"""
    out = {}
    for name, d in (("north", V(0, 0, -1)), ("south", V(0, 0, 1)),
                    ("east", V(1, 0, 0)), ("west", V(-1, 0, 0))):
        nb = world.get(p + d)
        conn = (not nb.is_air) and (
            classify(nb.id) == classify(b.id) or is_solid(nb))
        out[name] = "true" if conn else "false"
    if classify(b.id) == Fam.WALL:
        out["up"] = "true" if not world.get(p + V(0, 1, 0)).is_air else "false"
    return out


def lint(world, ignore_bottom: bool = True, region=None, level=None,
         codes=None, bbox=None) -> List[Issue]:
    """物理校验。结果按**严重度 → 码 → 坐标**排序（严重的不埋在末尾）。

    | 参数 | 作用 |
    |---|---|
    | `ignore_bottom` | 忽略最底层（假定落在地形上） |
    | `region` | 只查某个命名区域（区域名或 `Region` 对象） |
    | `level` | `"error"` / `"warn"` / `"info"`，只看该级别 |
    | `codes` | 只查这些码，如 `("W1", "W2")` |
    | `bbox` | **扫描范围**。给定时只扫盒内，并把盒当成"世界边界" |

    大建筑上告警会有成千条，用 `region` / `level` 收窄，或者直接看
    `w.lint_summary()` 的汇总。

    **稀疏大世界必须收窄**：`W4/W6` 的封闭空间检测要在包围盒上做洪泛，
    盒越大越慢。实测同一座 8,807 格的岛 —— 单独成一个世界 0.075 s，
    与另一座岛相距 900 格（包围盒被撑到 974 万格）时 **65 s**。
    全图 1000×1000 直接卡死。所以：

    * 传 `region=` 会自动取 `region.box` 当扫描范围，**不用手动传 `bbox`**
    * 手里只有坐标时用 `bbox=box((…), (…))`，**盒子要贴紧** ——
      它同时是洪泛的边界：盒内不与盒外连通的空气才算封闭空间，
      所以贴紧的盒给出的结果与"把这块单独拎出来查"一致
    """
    r = None
    if region is not None:
        r = world.region_of(region) if isinstance(region, str) else region
        if bbox is None:
            bbox = r.box
    issues = _lint_all(world, ignore_bottom, bbox)

    if r is not None:
        # W4/W6 的位置是空气格，不在 region.cells 里 —— 但扫描范围已经被
        # `bbox = r.box` 限死，它们本就属于这个区域，直接放行。
        issues = [i for i in issues
                  if i.pos in r.cells or i.code in AIR_LOCATED_CODES]
    if level is not None:
        want = str(level).capitalize()
        issues = [i for i in issues if i.level == want]
    if codes:
        keep = {c.upper() for c in codes}
        issues = [i for i in issues if i.code in keep]

    issues.sort(key=lambda i: (LEVEL_ORDER.get(i.level, 9), i.code,
                               i.pos.y, i.pos.z, i.pos.x))
    return issues


def lint_summary(world, region=None, ignore_bottom: bool = True, bbox=None) -> dict:
    """按码汇总，并按区域分解 —— 大建筑里"哪个建筑有问题"比"哪几格有问题"有用。

        {'W1': {'count': 1240, 'level': 'Warn', 'msg': '下方悬空，会被破坏掉落',
                'regions': {'nave': 900, 'tower': 340}, 'sample': (0,64,0)},
         'W4': {'count': 3, 'level': 'Info', ...}}

    按 count 降序返回。`bbox` 与 `lint()` 同义（见那边的说明）。
    """
    issues = lint(world, ignore_bottom=ignore_bottom, region=region, bbox=bbox)
    out: Dict[str, dict] = {}
    for i in issues:
        d = out.get(i.code)
        if d is None:
            d = out[i.code] = {"count": 0, "level": i.level, "msg": i.msg,
                               "regions": {}, "sample": i.pos}
        d["count"] += 1
        r = world.region_at(i.pos)
        key = r.name if r is not None else "(未分区)"
        d["regions"][key] = d["regions"].get(key, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]["count"]))


def _as_box(b) -> Box:
    """把 ``bbox`` 参数规范成 ``Box``。

    三种写法都收：``box(...)`` 的结果、``((x,y,z),(x,y,z))`` 两角、
    ``Box`` 本身。传别的（比如 6 个整数）直接报错，不猜。
    """
    if isinstance(b, Box):
        return b
    seq = list(b)
    if len(seq) != 2:
        raise ValueError(f"bbox 需要 Box 或两角坐标 ((x,y,z),(x,y,z))，收到 {b!r}")
    return box(seq[0], seq[1])


def _lint_all(world, ignore_bottom: bool = True, bbox=None) -> List[Issue]:
    """默认忽略最底层（假定它落在地形上）。

    ``bbox`` 给定时只遍历盒内方块，并把该盒当作"世界边界"。
    盒外的方块仍能被 ``world.get()`` 读到，所以靠邻居判断的
    W1 / W3 / W5 结论与扫全世界时**一致** —— 变的只是遍历范围。
    """
    issues: List[Issue] = []
    cells = world.cells
    if not cells:
        return issues
    if bbox is None:
        items = cells.items()
        b = world.bounds()
    else:
        b = _as_box(bbox)
        items = [(p, blk) for p, blk in cells.items() if p in b]
        if not items:
            return issues
    lo_y = b.lo.y

    # W1 悬空 / 无附着
    # 普通建筑方块在 MC 里可以合法悬空（屋顶必然横跨），
    # 所以只对「会掉落 / 会自己破坏 / 需要附着面」的方块报警。
    for p, blk in items:
        name = blk.name
        if name in HANG:
            # 灯笼 / 铁链的挂法由 `hanging` 决定，**不能一概而论**：
            # `hanging=false`（地板灯）靠**下方**支撑，查上方会 100% 误报。
            hanging = blk.get("hanging")
            if hanging == "true":
                if world.get(p + V(0, 1, 0)).is_air:
                    issues.append(Issue("W1", "Warn", p, blk, "上方无支撑（悬挂类方块）"))
            elif hanging == "false":
                if world.get(p + V(0, -1, 0)).is_air:
                    issues.append(Issue("W1", "Warn", p, blk, "下方无支撑（坐地类方块）"))
            elif (world.get(p + V(0, 1, 0)).is_air
                  and world.get(p + V(0, -1, 0)).is_air):
                issues.append(Issue("W1", "Warn", p, blk,
                                    "上下都无支撑，挂法未声明"))
            continue
        if name in SIDE_ATTACH:
            if not any(is_solid(world.get(p + d)) for d in
                       (V(0, 0, -1), V(0, 0, 1), V(1, 0, 0), V(-1, 0, 0))):
                issues.append(Issue("W1", "Warn", p, blk, "侧面无附着面"))
            continue
        if ignore_bottom and p.y == lo_y:
            continue
        if not world.get(p + V(0, -1, 0)).is_air:
            continue
        if name in GRAVITY:
            issues.append(Issue("W1", "Warn", p, blk, "重力方块下方悬空，会掉落"))
        elif name in NEEDS_SUPPORT or name.endswith(_NEEDS_SUPPORT_SUFFIX):
            issues.append(Issue("W1", "Warn", p, blk, "下方悬空，会被破坏掉落"))

    # W2 双格方块缺失 / W3 门顶被堵
    for p, blk in items:
        fam = classify(blk.id)
        if fam == Fam.DOOR and blk.get("half") == "lower":
            up = world.get(p + V(0, 1, 0))
            if up.is_air or up.id != blk.id or up.get("half") != "upper":
                issues.append(Issue("W2", "Warn", p, blk, "门缺少 upper 半格"))
            else:
                d = CARDINAL_VEC.get(blk.get("facing", "north"), V(0, 0, -1))
                if is_solid(world.get(p + d)) or is_solid(world.get(p + d + V(0, 1, 0))):
                    issues.append(Issue("W3", "Warn", p, blk, "门外被实体方块堵住"))
        if fam == Fam.BED and blk.get("part") == "foot":
            d = CARDINAL_VEC.get(blk.get("facing", "north"), V(0, 0, -1))
            head = world.get(p + d)
            if head.is_air or head.id != blk.id or head.get("part") != "head":
                issues.append(Issue("W2", "Warn", p, blk, "床缺少 head 半格"))

    # W4 封闭空间 / W6 无光源
    enclosed = _enclosed_air(world, b)
    if enclosed is None:
        # 盒子太大，洪泛会拖死进程 —— 明确报出来，不假装查过
        issues.append(Issue("W4", "Info", b.lo, AIR,
                            f"封闭空间检测已跳过：扫描盒 {b.volume():,} 格过大"
                            f"（上限 {ENCLOSED_MAX_BOX:,} 格 / {ENCLOSED_LIMIT:,} 空气格）。"
                            f"用更小的 bbox= 或 region= 分段查"))
    elif enclosed:
        sample = min(enclosed)
        issues.append(Issue("W4", "Info", sample, AIR,
                            f"存在 {len(enclosed)} 格与外部不连通的封闭空间"))
        lit = False
        for p in enclosed:
            for d in (V(0, 0, -1), V(0, 0, 1), V(1, 0, 0), V(-1, 0, 0),
                      V(0, 1, 0), V(0, -1, 0)):
                nb = world.cells.get(p + d)
                if nb is not None and nb.name in LIGHTS:
                    lit = True
                    break
            if lit:
                break
        if not lit:
            issues.append(Issue("W6", "Info", sample, AIR, "封闭空间内无光源"))

    # W5 连接属性与邻居不一致
    for p, blk in items:
        if classify(blk.id) not in CONNECT_FAMILIES:
            continue
        want = compute_connections(world, p, blk)
        props = blk.props()
        for k, v in want.items():
            if k in props and props[k] != v:
                issues.append(Issue("W5", "Warn", p, blk, f"{k} 应为 {v}，现为 {props[k]}"))
                break

    return issues


#: W4/W6 的洪泛最多访问这么多空气格，超了就放弃检测。
#:
#: 为什么需要这个上限：封闭空间检测是**在包围盒上做洪泛**，代价是 O(盒体积)。
#: `bbox=` 只能解决"稀疏世界里几个簇相距很远"，解决不了"**单个区域本身就是一条
#: 长对角线**" —— 比如一条 650 格长的斜向桥，它的包围盒是 655×655 的整块方形，
#: 空气上亿格，洪泛会把进程拖死。这种情况下宁可**明确跳过**也不要假装查过了。
ENCLOSED_LIMIT = 2_000_000

#: 包围盒体积超过这个值就**直接放弃** W4/W6，连盒表面都不枚举。
#: 因为 `Box.__iter__` 本身是 O(体积)：1.3 亿格的盒子，光是走一遍表面就够呛。
#: 12M ≈ 229³ —— 比这个还大的盒子基本都是稀疏结构，收窄 bbox 才是正解。
ENCLOSED_MAX_BOX = 12_000_000


def _enclosed_air(world, b, limit: int = ENCLOSED_LIMIT,
                  max_box: int = ENCLOSED_MAX_BOX):
    """在世界包围盒内、但与外部空气不连通的空气格。

    超出 `limit` / `max_box` 时返回 ``None``（表示"放弃检测"），由调用方报出来 ——
    不静默当作"没有封闭空间"。
    """
    if b.volume() > max_box:
        return None
    lo = b.lo - V(1, 1, 1)
    hi = b.hi + V(1, 1, 1)
    shell: List[V] = []
    for p in box(lo, hi):
        if (p.x in (lo.x, hi.x) or p.y in (lo.y, hi.y) or p.z in (lo.z, hi.z)):
            shell.append(p)
    seen: Set[V] = set()
    stack: List[V] = []
    for p in shell:
        if world.get(p).is_air and p not in seen:
            seen.add(p)
            stack.append(p)
    dirs = (V(0, 0, -1), V(0, 0, 1), V(1, 0, 0), V(-1, 0, 0), V(0, 1, 0), V(0, -1, 0))
    while stack:
        p = stack.pop()
        for d in dirs:
            q = p + d
            if q in seen:
                continue
            if not (lo.x <= q.x <= hi.x and lo.y <= q.y <= hi.y and lo.z <= q.z <= hi.z):
                continue
            if world.get(q).is_air:
                seen.add(q)
                stack.append(q)
        if len(seen) > limit:
            return None
    interior = set()
    for p in b:
        if world.get(p).is_air and p not in seen:
            interior.add(p)
    return interior


def apply_connections(world) -> int:
    """导出前自动修正连接类属性，返回修改格数。"""
    n = 0
    for p, blk in list(world.cells.items()):
        if classify(blk.id) not in CONNECT_FAMILIES:
            continue
        want = compute_connections(world, p, blk)
        props = blk.props()
        props.update(want)
        world.set(p, Block(blk.id, tuple(sorted(props.items()))))
        n += 1
    return n


def format_report(issues: List[Issue], limit: int = 20, world=None) -> str:
    """按码分组、按数量降序的简报。给了 world 就附带区域分布。"""
    if not issues:
        return "  （无问题）"

    by_code: Dict[str, List[Issue]] = {}
    for i in issues:
        by_code.setdefault(i.code, []).append(i)

    lines = []
    for code in sorted(by_code, key=lambda c: (-len(by_code[c]), c)):
        group = by_code[code]
        lv = group[0].level
        head = f"{code}({lv}) x{len(group)}  {group[0].msg}"
        if world is not None:
            regs: Dict[str, int] = {}
            for i in group:
                r = world.region_at(i.pos)
                key = r.name if r is not None else "(未分区)"
                regs[key] = regs.get(key, 0) + 1
            parts = sorted(regs.items(), key=lambda kv: -kv[1])[:4]
            head += "   区域: " + " ".join(f"{n} {v}" for n, v in parts)
        lines.append(head)
        for i in group[:2]:
            lines.append(f"     {i.pos}  {i.block.short()}")
        if len(group) > 2:
            lines.append(f"     ... 另有 {len(group) - 2} 处")
        if len(lines) > limit:
            lines.append("  ...（告警过多，用 w.lint(region=...) 或 w.lint_summary() 收窄）")
            break
    return "\n".join(lines)
