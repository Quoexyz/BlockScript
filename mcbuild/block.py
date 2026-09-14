"""BlockState、材质别名、blockstate 归一化与校验。

模型侧只写 `facing="+v"` / `axis="y"` / `rotation=112.5`，
由本模块翻译成 Minecraft 真实的 blockstate 属性。
非法组合直接抛 BlockStateError，绝不静默兜底。
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Iterable

from .vec import mirror_cardinal, rotate_axis, rotate_cardinal

AIR_ID = "minecraft:air"

FACING_H = ("north", "south", "east", "west")
FACING_HV = FACING_H + ("up", "down")
AXES = ("x", "y", "z")

# 楼梯 facing 语义：默认「facing 指向高侧（上坡方向）」。
# 若你的目标实现相反，改这一个常量即可全局翻转。
STAIRS_UPHILL = True


class BlockStateError(ValueError):
    """blockstate 非法。"""


class UnknownBlock(Warning):
    """方块不在内置表中，按可旋转实体处理。"""


class Fam:
    SOLID = "solid"
    FACING_H = "facing_h"
    FACING_HV = "facing_hv"
    AXIS = "axis"
    ROT16 = "rot16"
    SLAB = "slab"
    STAIRS = "stairs"
    DOOR = "door"
    TRAPDOOR = "trapdoor"
    GATE = "gate"
    WALL = "wall"
    FENCE = "fence"
    PANE = "pane"
    TORCH = "torch"
    LADDER = "ladder"
    BED = "bed"
    SIGN = "sign"


BOOL = ("true", "false")

_FAMILY_PROPS: dict[str, dict[str, tuple]] = {
    Fam.SOLID: {},
    Fam.FACING_H: {"facing": FACING_H},
    Fam.FACING_HV: {"facing": FACING_HV},
    Fam.AXIS: {"axis": AXES},
    Fam.ROT16: {"rotation": tuple(str(i) for i in range(16))},
    Fam.SLAB: {"type": ("top", "bottom", "double")},
    Fam.STAIRS: {"facing": FACING_H, "half": ("top", "bottom"),
                 "shape": ("straight", "inner_left", "inner_right",
                           "outer_left", "outer_right")},
    Fam.DOOR: {"facing": FACING_H, "half": ("upper", "lower"),
               "hinge": ("left", "right"), "open": BOOL, "powered": BOOL},
    Fam.TRAPDOOR: {"facing": FACING_H, "half": ("top", "bottom"),
                   "open": BOOL, "powered": BOOL},
    Fam.GATE: {"facing": FACING_H, "in_wall": BOOL, "open": BOOL, "powered": BOOL},
    Fam.WALL: {"north": BOOL, "east": BOOL, "south": BOOL, "west": BOOL, "up": BOOL},
    Fam.FENCE: {"north": BOOL, "east": BOOL, "south": BOOL, "west": BOOL},
    Fam.PANE: {"north": BOOL, "east": BOOL, "south": BOOL, "west": BOOL},
    Fam.TORCH: {"facing": FACING_H, "lit": BOOL},
    Fam.LADDER: {"facing": FACING_H},
    Fam.BED: {"facing": FACING_H, "part": ("head", "foot"), "occupied": BOOL},
    Fam.SIGN: {"rotation": tuple(str(i) for i in range(16)), "waterlogged": BOOL},
}


def _facing_family_props() -> dict[str, tuple]:
    return dict(_FAMILY_PROPS[Fam.WALL])


_OVERRIDE: dict[str, str] = {
    "torch": Fam.TORCH, "soul_torch": Fam.TORCH, "redstone_torch": Fam.TORCH,
    "wall_torch": Fam.TORCH, "soul_wall_torch": Fam.TORCH, "redstone_wall_torch": Fam.TORCH,
    "wall_sign": Fam.FACING_H, "wall_banner": Fam.FACING_H, "wall_fan": Fam.FACING_H,
    "ladder": Fam.LADDER,
    "end_rod": Fam.FACING_HV, "hopper": Fam.FACING_HV, "observer": Fam.FACING_HV,
    "piston": Fam.FACING_HV, "sticky_piston": Fam.FACING_HV,
    "dispenser": Fam.FACING_HV, "dropper": Fam.FACING_HV,
    "furnace": Fam.FACING_H, "blast_furnace": Fam.FACING_H, "smoker": Fam.FACING_H,
    "chest": Fam.FACING_H, "trapped_chest": Fam.FACING_H, "ender_chest": Fam.FACING_H,
    "barrel": Fam.FACING_H, "lectern": Fam.FACING_H, "campfire": Fam.FACING_H,
    "anvil": Fam.FACING_H, "grindstone": Fam.FACING_H, "loom": Fam.FACING_H,
    "chain": Fam.AXIS, "hay_block": Fam.AXIS, "bone_block": Fam.AXIS,
    "purpur_pillar": Fam.AXIS, "quartz_pillar": Fam.AXIS,
    "basalt": Fam.AXIS, "polished_basalt": Fam.AXIS,
}

_AXIS_SUFFIX = ("_log", "_wood", "_stem", "_hyphae")


@lru_cache(maxsize=None)
def classify(block_id: str) -> str:
    """判定方块族。未知方块按 SOLID 处理（并在 lint 里报 W0）。

    **带缓存**：这个函数逐条 `endswith` 试到十几次，而渲染/查询会在热路径上
    按格调用它（实测 15.8 万方块 → 237 万次 `endswith`）。方块 id 的取值空间
    只有一千多个，缓存代价可以忽略。
    """
    name = block_id.split(":")[-1]
    if name in _OVERRIDE:
        return _OVERRIDE[name]
    if name.endswith("_stairs"):
        return Fam.STAIRS
    if name.endswith("_slab"):
        return Fam.SLAB
    if name.endswith("_door"):
        return Fam.DOOR
    if name.endswith("_trapdoor"):
        return Fam.TRAPDOOR
    if name.endswith("_fence_gate"):
        return Fam.GATE
    if name.endswith("_fence"):
        return Fam.FENCE
    if name.endswith("_pane"):
        return Fam.PANE
    if name.endswith("_bed"):
        return Fam.BED
    if "torch" in name:
        return Fam.TORCH
    if name.endswith("_wall"):
        return Fam.WALL
    if name.endswith("_sign") or name.endswith("_hanging_sign"):
        return Fam.SIGN
    if name.endswith("_skull") or name.endswith("_head"):
        return Fam.ROT16
    if name.endswith(_AXIS_SUFFIX):
        return Fam.AXIS
    return Fam.SOLID


def family_props(block_id: str) -> dict[str, tuple]:
    return _FAMILY_PROPS.get(classify(block_id), {})


# ---------------------------------------------------------------- 数据驱动的属性定义

def allowed_props(block_id: str, fam: str | None = None) -> dict[str, tuple]:
    """某方块允许的属性与取值。

    **优先用 registry 的数据**（prismarinejs/minecraft-data，覆盖 1196 个方块的
    真实属性定义），registry 里没有的（mod 方块、新版本方块）才回退到手写的
    `_FAMILY_PROPS` 族规则。

    比手写表准的地方：`redstone_wire` 的 `power` 是 0..15、`banner` 的
    `rotation` 是 16 分度、不同方块的 `facing` 集合并不都一样。
    """
    from .registry import states
    st = states(block_id)
    if st:
        return {k: (tuple(v) if v else BOOL) for k, v in st.items()}
    return _FAMILY_PROPS.get(fam if fam is not None else classify(block_id), {})


_NORM_CACHE: dict["Block", "Block"] = {}


def normalize(b: "Block") -> "Block":
    """补全默认属性后的方块，**用于比较与去重**（不改变存储与导出）。

    Minecraft 的 blockstate 有默认值，所以 ``oak_door[half=lower]`` 与
    ``oak_door[half=lower,hinge=left]`` 是同一个东西。以前的比较是逐字节比
    state 元组，一边显式写、一边缺省就会误判不一致（compare 会误报）。

    导出与 `key()` 仍走原始 state —— 补全会让每个方块都拖一长串默认属性，
    导出的 palette 会变得又长又难读。
    """
    if b.is_air:
        return b
    hit = _NORM_CACHE.get(b)
    if hit is not None:
        return hit
    from .registry import defaults
    d = defaults(b.id)
    if not d:
        out = b
    else:
        merged = dict(d)
        merged.update(b.props())
        out = Block(b.id, tuple(merged.items()))
    _NORM_CACHE[b] = out
    return out


# ---------------------------------------------------------------- 别名表

# 只保留**英文简写**。中文别名已移除 —— 模型本来就知道方块名，
# 而中文译名各家不一（"石砖"既可能是 stone_bricks 也可能是 brick），
# 维护一份随时过时的映射表不如直接用真名（写错了 registry 会告诉你）。
_ALIAS: dict[str, str] = {
    "planks": "oak_planks", "log": "oak_log", "stairs": "oak_stairs",
    "slab": "oak_slab", "wall": "cobblestone_wall", "fence": "oak_fence",
    "door": "oak_door", "wool": "white_wool", "concrete": "white_concrete",
}


def resolve_alias(name: str) -> str:
    """把别名 / 短 id 解析成 ``minecraft:xxx``。

    带命名空间的（``minecraft:stone`` / ``create:cogwheel``）原样返回。
    """
    key = str(name).strip().lower().replace(" ", "_")
    if ":" in key:
        return key
    key = _ALIAS.get(key, key)
    return key if key.startswith("minecraft:") else "minecraft:" + key


# ---------------------------------------------------------------- Block


@dataclass(frozen=True)
class Block:
    """不可变方块状态。state 用有序 tuple 存储以便哈希。"""

    id: str
    state: tuple = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", tuple(sorted((k, str(v)) for k, v in self.state)))

    @property
    def name(self) -> str:
        return self.id.split(":")[-1]

    @property
    def is_air(self) -> bool:
        return self.id == AIR_ID

    def props(self) -> dict:
        return dict(self.state)

    def get(self, key: str, default: str | None = None):
        return self.props().get(key, default)

    def with_state(self, **kw) -> "Block":
        """返回替换属性后的新方块（不做校验，用于内部变换）。"""
        d = self.props()
        for k, v in kw.items():
            if v is None:
                d.pop(k, None)
            else:
                d[k] = _str_val(v)
        return Block(self.id, tuple(d.items()))

    def key(self) -> str:
        if not self.state:
            return self.id
        inner = ",".join(f"{k}={v}" for k, v in self.state)
        return f"{self.id}[{inner}]"

    def short(self) -> str:
        n = self.name
        if not self.state:
            return n
        return f"{n}[{','.join(f'{k}={v}' for k, v in self.state)}]"

    def __str__(self) -> str:  # noqa: D105
        return self.short()


AIR = Block(AIR_ID, ())


def _str_val(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


# ---------------------------------------------------------------- 归一化

_SYMBOL_FACING = {
    "+v": "south", "-v": "north", "+u": "east", "-u": "west",
    "+w": "up", "-w": "down",
    "front": "south", "back": "north", "right": "east", "left": "west",
    "up": "up", "down": "down",
    "n": "north", "s": "south", "e": "east", "w": "west",
}


def _resolve_facing(value: str) -> str:
    v = str(value).strip().lower()
    return _SYMBOL_FACING.get(v, v)


def make(block: "str | Block", yaw: int = 0, **state) -> Block:
    """构造方块：解析别名 -> 归一化属性 -> yaw 旋转 -> 校验。"""
    if isinstance(block, Block):
        return rotate_block(block, yaw)
    bid = resolve_alias(block)
    if bid == AIR_ID:
        return AIR
    fam = classify(bid)
    allowed = allowed_props(bid, fam)
    out: dict[str, str] = {}

    for k, v in state.items():
        if v is None:
            continue
        key = k.lower()
        val = _str_val(v)

        if key == "facing":
            card = _resolve_facing(val)
            if card not in FACING_HV:
                raise BlockStateError(
                    f"facing 取值非法: {val!r}（可用 {FACING_HV} 或 "
                    f"+u/-u/+v/-v/+w/-w/front/back/left/right/up/down）")
            card = rotate_cardinal(card, yaw)
            out["facing"] = card

        elif key == "axis":
            ax = val.lower()
            if ax not in AXES:
                raise BlockStateError(f"axis 取值非法: {val!r}（可用 {AXES}）")
            out["axis"] = rotate_axis(ax, yaw)

        elif key == "rotation":
            # 接受角度或 0..15 的档位
            try:
                f = float(val)
            except ValueError as e:
                raise BlockStateError(f"rotation 取值非法: {val!r}") from e
            step = int(round(f / 22.5)) % 16 if f > 15 else int(round(f)) % 16
            step = (step + int(yaw // 22.5)) % 16
            out["rotation"] = str(step)

        elif key in ("half",) and fam == Fam.SLAB:
            hv = val.lower()
            if hv not in ("top", "bottom", "double"):
                raise BlockStateError(f"半砖 half 取值非法: {val!r}（可用 top/bottom/double）")
            out["type"] = hv

        elif key == "waterlogged":
            out["waterlogged"] = "true" if str(val).lower() in ("true", "1", "yes") else "false"

        else:
            out[key] = val

    # 校验
    for k, v in out.items():
        if k == "waterlogged" and k not in allowed:
            # 表里没有定义的方块（mod 等）对 waterlogged 宽容处理
            if v not in BOOL:
                raise BlockStateError(f"{bid}: waterlogged 取值非法: {v!r}")
            continue
        if k not in allowed:
            raise BlockStateError(
                f"{bid}({fam}) 不支持属性 {k!r}，可用: {sorted(allowed)}")
        if v not in allowed[k]:
            raise BlockStateError(
                f"{bid}: {k}={v!r} 非法，可用: {list(allowed[k])}")

    return Block(bid, tuple(out.items()))


def rotate_block(b: Block, yaw: int) -> Block:
    """旋转已有方块的 state。"""
    if b.is_air or not b.state:
        return b
    d = b.props()
    if "facing" in d and d["facing"] in FACING_H:
        d["facing"] = rotate_cardinal(d["facing"], yaw)
    if "axis" in d:
        d["axis"] = rotate_axis(d["axis"], yaw)
    if "rotation" in d:
        d["rotation"] = str((int(d["rotation"]) + int(yaw // 22.5)) % 16)
    return Block(b.id, tuple(d.items()))


def mirror_block(b: Block, axis: str) -> Block:
    """镜像已有方块的 state。"""
    if b.is_air or not b.state:
        return b
    d = b.props()
    if "facing" in d and d["facing"] in FACING_H:
        d["facing"] = mirror_cardinal(d["facing"], axis)
    if "rotation" in d:
        r = int(d["rotation"])
        d["rotation"] = str(((16 - r) % 16) if axis == "x" else ((8 - r) % 16))
    if "hinge" in d:
        d["hinge"] = "right" if d["hinge"] == "left" else "left"
    return Block(b.id, tuple(d.items()))


def is_solid(b: Block) -> bool:
    """粗略判断是否实心（用于支撑/连接判定）。"""
    if b.is_air:
        return False
    fam = classify(b.id)
    if fam in (Fam.TORCH, Fam.LADDER, Fam.WALL, Fam.FENCE, Fam.PANE):
        return False
    if b.get("waterlogged") == "true":
        return False
    return True
