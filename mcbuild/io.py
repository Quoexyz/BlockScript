"""导入导出。

.schem  = Sponge Schematic（v2 / v3），WorldEdit / Litematica 通用
.nbt    = 结构方块 NBT，游戏内直接加载
.json   = 自研格式，含体素 + 锚点 + op 历史，可回放
"""

from __future__ import annotations

import gzip
import json
import struct
from typing import Dict, List

from .block import AIR, Block
from .vec import V, box

# ------------------------------------------------------------------ NBT


class I(int):
    __slots__ = ()


class Sh(int):
    __slots__ = ()


class B(int):
    __slots__ = ()


class Lg(int):
    __slots__ = ()


class F(float):
    __slots__ = ()


class D(float):
    __slots__ = ()


class Str(str):
    __slots__ = ()


class BA(bytes):
    __slots__ = ()


class IA(list):
    __slots__ = ()


class LA(list):
    """``TAG_Long_Array``（12）。

    **区块格式离不开它**：`sections[].block_states.data`（位打包的调色板索引）
    和 `Heightmaps` 都是长整型数组。原先只有 ByteArray / IntArray 两种，
    所以写不出 .mca 区块 —— 补上之后 `dumps_nbt` 才能生成合法区块负载。

        LA([0x0000_0000_0000_0001])     # 一个 long
    """
    __slots__ = ()


class C(dict):
    __slots__ = ()


class Lst:
    __slots__ = ("items", "etype")

    def __init__(self, items, etype: int):
        self.items = list(items)
        self.etype = etype


TAG_BYTE, TAG_SHORT, TAG_INT, TAG_LONG = 1, 2, 3, 4
TAG_FLOAT, TAG_DOUBLE = 5, 6
TAG_BYTE_ARRAY, TAG_STRING = 7, 8
TAG_LIST, TAG_COMPOUND, TAG_INT_ARRAY = 9, 10, 11
TAG_LONG_ARRAY = 12

_TAGS = (B, Sh, I, Lg, F, D, Str, BA, IA, LA, C, Lst)


def nbt_value(v):
    """把 Python 值递归转成 NBT 标签。

    dict → Compound，list/tuple → List（元素类型必须一致），
    bool → Byte，int → Int，float → Double，str → String，bytes → ByteArray。
    已经是标签的值原样返回。

        nbt_value({"front_text": {"messages": ["hi"]}})
    """
    if isinstance(v, _TAGS):
        return v
    if isinstance(v, bool):
        return B(1 if v else 0)
    if isinstance(v, int):
        return I(v)
    if isinstance(v, float):
        return D(v)
    if isinstance(v, str):
        return Str(v)
    if isinstance(v, (bytes, bytearray)):
        return BA(bytes(v))
    if isinstance(v, (list, tuple)):
        items = [nbt_value(x) for x in v]
        if not items:
            return Lst([], TAG_COMPOUND)
        et = _tag_of(items[0])
        for it in items:
            if _tag_of(it) != et:
                raise ValueError(
                    f"NBT 列表元素类型必须一致：{_tag_of(items[0])} vs {_tag_of(it)}")
        return Lst(items, et)
    if isinstance(v, dict):
        return C({str(k): nbt_value(x) for k, x in v.items()})
    raise TypeError(f"无法转成 NBT 的值: {v!r}")


def _tag_of(x) -> int:
    if isinstance(x, Lst):
        return TAG_LIST
    if isinstance(x, LA):
        return TAG_LONG_ARRAY
    if isinstance(x, IA):
        return TAG_INT_ARRAY
    if isinstance(x, BA):
        return TAG_BYTE_ARRAY
    if isinstance(x, C) or type(x) is dict:
        return TAG_COMPOUND
    if isinstance(x, Str) or type(x) is str:
        return TAG_STRING
    if type(x) is bool:
        return TAG_BYTE
    if isinstance(x, Sh):
        return TAG_SHORT
    if isinstance(x, B):
        return TAG_BYTE
    if isinstance(x, Lg):
        return TAG_LONG
    if isinstance(x, I) or type(x) is int:
        return TAG_INT
    if isinstance(x, F):
        return TAG_FLOAT
    if isinstance(x, D) or type(x) is float:
        return TAG_DOUBLE
    raise TypeError(f"无法序列化的 NBT 类型: {type(x)}")


def _write_payload(out: bytearray, x) -> None:
    t = _tag_of(x)
    if t == TAG_COMPOUND:
        for k, v in x.items():
            _write_named(out, k, v)
        out.append(0)
    elif t == TAG_LIST:
        out.append(x.etype)
        out += struct.pack(">i", len(x.items))
        for it in x.items:
            _write_payload(out, it)
    elif t == TAG_STRING:
        s = str(x).encode("utf-8")
        out += struct.pack(">H", len(s)) + s
    elif t == TAG_BYTE_ARRAY:
        out += struct.pack(">i", len(x)) + bytes(x)
    elif t == TAG_INT_ARRAY:
        out += struct.pack(">i", len(x))
        for v in x:
            out += struct.pack(">i", int(v))
    elif t == TAG_LONG_ARRAY:
        out += struct.pack(">i", len(x))
        for v in x:
            out += struct.pack(">q", int(v))
    elif t == TAG_BYTE:
        out += struct.pack(">b", int(x))
    elif t == TAG_SHORT:
        out += struct.pack(">h", int(x))
    elif t == TAG_INT:
        out += struct.pack(">i", int(x))
    elif t == TAG_LONG:
        out += struct.pack(">q", int(x))
    elif t == TAG_FLOAT:
        out += struct.pack(">f", float(x))
    elif t == TAG_DOUBLE:
        out += struct.pack(">d", float(x))


def _write_named(out: bytearray, name: str, x) -> None:
    out.append(_tag_of(x))
    s = name.encode("utf-8")
    out += struct.pack(">H", len(s)) + s
    _write_payload(out, x)


def dumps_nbt(root_name: str, payload) -> bytes:
    out = bytearray()
    _write_named(out, root_name, payload)
    return bytes(out)


def dumps_nbt_gz(root_name: str, payload) -> bytes:
    return gzip.compress(dumps_nbt(root_name, payload), compresslevel=6)


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            break
    return bytes(out)


# ------------------------------------------------------------------ 导出

DATA_VERSION = 4325  # 1.21.x


def _prep(world, apply_conn: bool = True):
    """返回 (包围盒, 尺寸, 取方块函数)。

    连接属性（墙/栅栏/玻璃板）在 **副本** 上计算：导出绝不能污染原世界，
    否则导出之后 render / lint 读到的是被改写过的 state。
    """
    if apply_conn:
        from .lint import apply_connections
        from .world import World
        tmp = World()
        tmp.cells = dict(world.cells)
        apply_connections(tmp)
        get_block = tmp.get
    else:
        get_block = world.get
    b = world.bounds()
    if b is None:
        raise ValueError("空世界，无法导出")
    return b, b.size, get_block


def _block_entities(world, b, get_block) -> List[C]:
    """Sponge 格式的方块实体：``{Id, Pos:[x,y,z], ...nbt}``（坐标转为相对原点）。

    方块已经被清掉的位置自动跳过 —— 不做额外的失效清理，导出时过滤更省事。
    """
    out: List[C] = []
    for p in sorted(world.block_entities, key=lambda v: (v.y, v.z, v.x)):
        if p not in b:
            continue
        blk = get_block(p)
        if blk.is_air:
            continue
        d = {"Id": Str(blk.id),
             "Pos": IA([p.x - b.lo.x, p.y - b.lo.y, p.z - b.lo.z])}
        for k, v in nbt_value(world.block_entities[p]).items():
            d[k] = v
        out.append(C(d))
    return out


def _entities(world, b) -> List[C]:
    """Sponge 格式的实体：``{Id, Pos:[x,y,z], ...}``（Pos 是浮点）。"""
    out: List[C] = []
    for e in world.entities:
        raw = dict(e)
        eid = raw.pop("id", None)
        raw.pop("Id", None)
        d = {}
        if eid:
            d["Id"] = Str(str(eid))
        pos = raw.pop("Pos", None)
        if pos is not None and len(pos) == 3:
            d["Pos"] = Lst([D(float(pos[0]) - b.lo.x),
                            D(float(pos[1]) - b.lo.y),
                            D(float(pos[2]) - b.lo.z)], TAG_DOUBLE)
        for k, v in nbt_value(raw).items():
            d[k] = v
        out.append(C(d))
    return out


def export_schem(world, path, version: int = 3, data_version: int = DATA_VERSION,
                 apply_conn: bool = True, regions: bool = True) -> str:
    b, (W, H, L), get_block = _prep(world, apply_conn)
    palette: Dict[str, int] = {}
    data = bytearray()
    for y in range(H):
        for z in range(L):
            for x in range(W):
                blk = get_block(V(b.lo.x + x, b.lo.y + y, b.lo.z + z))
                key = blk.key()
                idx = palette.get(key)
                if idx is None:
                    idx = len(palette)
                    palette[key] = idx
                data += _varint(idx)

    blocks = C({
        "Palette": C({k: I(v) for k, v in palette.items()}),
        "Data": BA(bytes(data)),
        "BlockEntities": Lst(_block_entities(world, b, get_block), TAG_COMPOUND),
    })
    fields = C({
        "Version": I(version),
        "DataVersion": I(data_version),
        "Width": Sh(W), "Height": Sh(H), "Length": Sh(L),
        "Blocks": blocks,
        "Entities": Lst(_entities(world, b), TAG_COMPOUND),
    })
    if version >= 3:
        # Offset 记世界原点，否则导入时无法还原建筑在空间中的位置
        # （方块数据本身是相对包围盒的 0-based 坐标）
        fields["Offset"] = IA([b.lo.x, b.lo.y, b.lo.z])

    # 自定义字段：把命名分区一起带上，这样跨 agent / 跨文件搬运零件之后
    # 还能按区域独立操作（否则只剩一堆体素）
    if regions and world.regions:
        rel = _ser_regions_rel(world, b.lo)
        if rel:
            fields["MCBuild"] = C({"Regions": nbt_value(rel)})
    root = C({"Schematic": fields}) if version >= 3 else fields
    with open(path, "wb") as f:
        f.write(dumps_nbt_gz("Schematic", root))
    return path


def _pal_entry(key: str) -> C:
    if "[" in key:
        bid, rest = key.split("[", 1)
        props = rest.rstrip("]").split(",")
    else:
        bid, props = key, []
    d = {}
    for p in props:
        if "=" in p:
            k, v = p.split("=", 1)
            d[k] = Str(v)
    return C({"Name": Str(bid), "Properties": C(d)})


def export_nbt(world, path, data_version: int = DATA_VERSION,
               apply_conn: bool = True) -> str:
    b, (W, H, L), get_block = _prep(world, apply_conn)
    palette: Dict[str, int] = {}
    blocks: List[C] = []
    for p in sorted(world.cells, key=lambda v: (v.y, v.z, v.x)):
        blk = get_block(p)
        if blk.is_air:
            continue
        key = blk.key()
        if key not in palette:
            palette[key] = len(palette)
        item = C({
            "pos": Lst([I(p.x - b.lo.x), I(p.y - b.lo.y), I(p.z - b.lo.z)], TAG_INT),
            "state": I(palette[key]),
        })
        nbt = world.block_entities.get(p)
        if nbt:                       # 结构方块把方块实体嵌在对应 blocks 项里
            item["nbt"] = nbt_value(nbt)
        blocks.append(item)

    ents: List[C] = []
    for e in world.entities:
        raw = dict(e)
        pos = raw.pop("Pos", None)
        item = C({})
        if pos is not None and len(pos) == 3:
            item["pos"] = Lst([D(float(pos[0]) - b.lo.x),
                               D(float(pos[1]) - b.lo.y),
                               D(float(pos[2]) - b.lo.z)], TAG_DOUBLE)
        item["nbt"] = nbt_value(raw)
        ents.append(item)

    root = C({
        "size": Lst([I(W), I(H), I(L)], TAG_INT),
        "palette": Lst([_pal_entry(k) for k in palette], TAG_COMPOUND),
        "blocks": Lst(blocks, TAG_COMPOUND),
        "entities": Lst(ents, TAG_COMPOUND),
        "DataVersion": I(data_version),
    })
    with open(path, "wb") as f:
        f.write(dumps_nbt_gz("", root))
    return path


def _jsonable(d) -> dict:
    """只保留能 JSON 序列化的键（组件参数里可能有函数等不可存的东西）。"""
    out = {}
    for k, v in (d or {}).items():
        try:
            json.dumps(v)
            out[k] = v
        except (TypeError, ValueError):
            continue
    return out


def _ser_instances(world) -> list:
    """组件实例的**元数据**（函数与 patch 不存，展开时可重建）。

    跨对话后 `replay` 才能继续工作 —— 否则 `load` 回来实例表是空的，
    组件同步、区域划分、局部覆盖全都失效。
    """
    idx = {id(i): n for n, i in enumerate(world.instances)}
    out = []
    for inst in world.instances:
        out.append({
            "name": inst.name,
            "at": [inst.at.x, inst.at.y, inst.at.z],
            "yaw": inst.yaw,
            "params": _jsonable(inst.params),
            "overrides": {f"{p.x},{p.y},{p.z}": b.key()
                          for p, b in inst.overrides.items()},
            "linked": inst.linked,
            "parent": idx.get(id(inst.parent)) if inst.parent is not None else None,
        })
    return out


def _ser_regions(world) -> list:
    return [{"name": r.name,
             "cells": [[p.x, p.y, p.z] for p in sorted(r.cells)]}
            for r in world.regions.values()]


def _ser_regions_rel(world, base: V) -> list:
    """区域元数据（坐标转成相对于 ``base``），嵌进 .schem 用。

    只带**世界里真实存在**的格子 —— 被搬空的历史位置没必要传输。
    """
    out = []
    for r in world.regions.values():
        cells = [p for p in sorted(r.cells) if p in world.cells]
        if not cells:
            continue
        out.append({
            "Name": r.name,
            "Parent": r.parent.name if r.parent is not None else "",
            "Cells": [[p.x - base.x, p.y - base.y, p.z - base.z] for p in cells],
        })
    return out


def _unique_region_name(world, name: str, prefix: str = "") -> str:
    """重名时加 ``@2`` ``@3`` 后缀，不静默覆盖已有的区域。"""
    n = f"{prefix}{name}" if prefix else name
    if n not in world.regions:
        return n
    i = 2
    while f"{n}@{i}" in world.regions:
        i += 1
    return f"{n}@{i}"


def _des_regions_rel(world, entries, base: V, prefix: str = "") -> list:
    """把 .schem 里的区域元数据还原成 Region（坐标加回 ``base``）。

    有父的区域会改名成 ``父名/原名`` —— 与 ``copy_to`` 的命名规则一致。
    多岛合并时这点很关键，否则两个岛的子区域都叫 ``pav_1``，
    第二个只能委屈地叫 ``pav_1@2``，看不出属于谁。
    """
    from .region import Region, _bbox

    made = {}
    parents = {}
    for d in entries:
        try:
            name = str(d.get("Name") or d.get("name") or "")
            if not name:
                continue
            cells = {base + V(int(c[0]), int(c[1]), int(c[2]))
                     for c in (d.get("Cells") or d.get("cells") or [])}
            if not cells:
                continue
            n = _unique_region_name(world, name, prefix)
            r = Region(n, world)
            r.cells = cells
            r.box = _bbox(cells)
            world.regions[n] = r
            made[name] = r
            parents[name] = str(d.get("Parent") or d.get("parent") or "")
        except (TypeError, ValueError, IndexError):
            continue

    # 接父子（父可能后出现）
    for name, pname in parents.items():
        if pname and pname in made and made[name].parent is None:
            made[name].parent = made[pname]

    # 从根往下把子区域改名为 path 形式
    def _fix(parent: "Region") -> None:
        for c in [x for x in made.values() if x.parent is parent]:
            old = c.name
            new = f"{parent.name}/{old.split('/')[-1]}"
            if new != old:
                del world.regions[old]
                new = _unique_region_name(world, new)
                world.regions[new] = c
                c.name = new
            _fix(c)

    for r in [x for x in made.values() if x.parent is None]:
        _fix(r)
    return list(made.values())


def _ser_stages(world) -> list:
    out = []
    for s in world.stages:
        b = s.box
        out.append({"name": s.name,
                    "box": [[b.lo.x, b.lo.y, b.lo.z],
                            [b.hi.x, b.hi.y, b.hi.z]] if b else None})
    return out


def _des_instances(world, data) -> None:
    from .component import Instance

    for d in data:
        inst = Instance(name=d["name"], at=V(*d["at"]), yaw=int(d.get("yaw", 0)),
                        params=dict(d.get("params") or {}))
        inst.linked = bool(d.get("linked", True))
        for k, v in (d.get("overrides") or {}).items():
            inst.overrides[V(*(int(x) for x in k.split(",")))] = parse_block_key(v)
        world.instances.append(inst)
        pi = d.get("parent")
        if pi is not None and 0 <= pi < len(world.instances) - 1:
            inst.parent = world.instances[pi]
            inst.parent.children.append(inst)


def _des_regions(world, data) -> None:
    from .region import Region, _bbox

    for d in data:
        r = Region(d["name"], world)
        r.cells = {V(*p) for p in d.get("cells", [])}
        r.box = _bbox(r.cells)
        world.regions[r.name] = r


def _des_stages(world, data) -> None:
    from .stage import Stage

    for d in data:
        b = d.get("box")
        world.stages.append(Stage(
            name=d["name"], fn=None, patch=[],
            box=box(V(*b[0]), V(*b[1])) if b else None))


def export_json(world, path, indent: int = 1, meta: bool = True) -> str:
    """存盘。

    ``meta=True``（默认）会连**组件实例 / 命名区域 / 阶段**的元数据一起存 ——
    跨对话后 ``replay``、``region_of``、``stage_box`` 才能继续用。
    这些是数据（名字/位置/参数/局部覆盖），函数引用不存（下轮脚本里会重新注册）。
    """
    data = {
        "version": 1,
        "blocks": [{"pos": [p.x, p.y, p.z],
                    "id": b.id,
                    "state": {k: v for k, v in b.state}}
                   for p, b in sorted(world.cells.items())],
        "block_entities": [{"pos": [p.x, p.y, p.z], "nbt": nbt}
                           for p, nbt in sorted(world.block_entities.items())],
        "entities": list(world.entities),
        "marks": world.marks.as_dict(),
        "ops": world.ops_log,
    }
    if meta:
        data["instances"] = _ser_instances(world)
        data["regions"] = _ser_regions(world)
        data["stages"] = _ser_stages(world)
        data["components"] = sorted(world._components)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)
    return path


def import_json(path, world=None):
    if world is None:
        from .world import World
        world = World()
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    world.cells = {V(*d["pos"]): Block(d["id"], tuple(d.get("state", {}).items()))
                   for d in data["blocks"]}
    world.block_entities = {V(*d["pos"]): d["nbt"]
                            for d in data.get("block_entities", [])}
    world.entities = list(data.get("entities", []))
    world.marks.load(data.get("marks", {}))
    world.ops_log = list(data.get("ops", []))
    world.instances = []
    world.regions = {}
    world.stages = []
    _des_instances(world, data.get("instances", []))
    _des_regions(world, data.get("regions", []))
    _des_stages(world, data.get("stages", []))
    world.checkpoint()
    return world


# ------------------------------------------------------------------ NBT 读取

def loads_nbt(raw: bytes):
    """解析未压缩的 NBT 字节流，返回 ``(根名, 载荷)``。

    dict → Compound，list → List，其余按标签类型还原成 int/float/str/bytes。
    """
    pos = [0]

    def rd(fmt, n):
        v = struct.unpack_from(fmt, raw, pos[0])[0]
        pos[0] += n
        return v

    def read(t):
        if t == TAG_BYTE:
            return rd(">b", 1)
        if t == TAG_SHORT:
            return rd(">h", 2)
        if t == TAG_INT:
            return rd(">i", 4)
        if t == TAG_LONG:
            return rd(">q", 8)
        if t == TAG_FLOAT:
            return rd(">f", 4)
        if t == TAG_DOUBLE:
            return rd(">d", 8)
        if t == TAG_BYTE_ARRAY:
            n = rd(">i", 4)
            s = raw[pos[0]:pos[0] + n]
            pos[0] += n
            return s
        if t == TAG_STRING:
            n = rd(">H", 2)
            s = raw[pos[0]:pos[0] + n].decode("utf-8")
            pos[0] += n
            return s
        if t == TAG_LIST:
            et = raw[pos[0]]
            pos[0] += 1
            n = rd(">i", 4)
            return [read(et) for _ in range(n)]
        if t == TAG_COMPOUND:
            d = {}
            while True:
                tt = raw[pos[0]]
                pos[0] += 1
                if tt == 0:
                    break
                n = rd(">H", 2)
                key = raw[pos[0]:pos[0] + n].decode("utf-8")
                pos[0] += n
                d[key] = read(tt)
            return d
        if t == TAG_INT_ARRAY:
            n = rd(">i", 4)
            return [rd(">i", 4) for _ in range(n)]
        if t == TAG_LONG_ARRAY:
            n = rd(">i", 4)
            return LA(rd(">q", 8) for _ in range(n))
        raise ValueError(f"未知 NBT 标签类型: {t}")

    t = raw[pos[0]]
    pos[0] += 1
    if t != TAG_COMPOUND:
        raise ValueError("NBT 根必须是 Compound")
    n = rd(">H", 2)
    name = raw[pos[0]:pos[0] + n].decode("utf-8")
    pos[0] += n
    return name, read(TAG_COMPOUND)


def loads_nbt_gz(data: bytes):
    """解析 gzip 压缩的 NBT。"""
    return loads_nbt(gzip.decompress(data))


def _read_varint(data, i: int):
    n = 0
    shift = 0
    while True:
        b = data[i]
        i += 1
        n |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
    return n, i


def parse_block_key(key: str) -> Block:
    """``"minecraft:stone[facing=north]"`` → Block。"""
    if "[" in key:
        bid, rest = key.split("[", 1)
        props = [p.split("=", 1) for p in rest.rstrip("]").split(",") if "=" in p]
        return Block(bid, tuple((k, v) for k, v in props))
    return Block(key, ())


def export_tiled(world, out_dir, chunk: int = 48, prefix: str = "part",
                 ext: str = "nbt", apply_conn: bool = True,
                 data_version: int = DATA_VERSION,
                 stale_out: List[str] = None,
                 manifest_path: str = None) -> List[dict]:
    """分块导出：结构方块单块上限 48³，大建筑必须切开。

    返回清单 ``[{"file", "box", "blocks"}, ...]``，
    ``box`` 是该块在**世界坐标**里的范围 —— 按清单逐块摆回即可还原。

        parts = w.export_tiled("out/cathedral", chunk=48)
        for it in parts:
            print(it["file"], it["box"], it["blocks"])
    """
    import math
    import os

    b = world.bounds()
    if b is None:
        raise ValueError("空世界，无法导出")
    chunk = max(1, int(chunk))
    os.makedirs(out_dir, exist_ok=True)

    # **上一轮的残留瓦片：只报告，不删除** —— 见函数末尾的 `stale_out`。
    # 不在这里删，是因为批量删文件会撞上主机的 safe-delete 策略
    # （实测 303 个文件直接抛 SAFE_DELETE_BULK_CONFIRM_REQUIRED，把导出整个打断）。

    def tile_of(p: V):
        return ((p.x - b.lo.x) // chunk, (p.y - b.lo.y) // chunk,
                (p.z - b.lo.z) // chunk)

    groups: Dict[tuple, Dict[V, Block]] = {}
    for p, blk in world.cells.items():
        groups.setdefault(tile_of(p), {})[p] = blk
    be_groups: Dict[tuple, Dict[V, dict]] = {}
    for p, nbt in world.block_entities.items():
        be_groups.setdefault(tile_of(p), {})[p] = nbt
    ent_groups: Dict[tuple, List[dict]] = {}
    for e in world.entities:
        pos = e.get("Pos")
        if not pos or len(pos) != 3:
            continue
        fake = V(int(math.floor(float(pos[0]))), int(math.floor(float(pos[1]))),
                 int(math.floor(float(pos[2]))))
        ent_groups.setdefault(tile_of(fake), []).append(e)

    from .world import World

    #: 瓦片索引 -> 落在它里面的区域名。**必须先算一次，不能每个瓦片去扫全部区域。**
    #:
    #: 原先的写法是 `for r in world.regions.values(): {p for p in r.cells if p in sub.cells}`
    #: —— 即"每个瓦片 × 全部区域的全部格子"。998 个瓦片 × 1060 万格 ≈ 10¹⁰ 次判断，
    #: 实测这一项单独吃掉 **3961 秒**（整次导出 66 分钟，而建图只要 10 分钟）。
    #: 预先算一遍是 O(全部区域格子)，一次 10⁶ 量级，之后每块只查自己那几个区域。
    region_of_tile: Dict[tuple, List[str]] = {}
    if getattr(world, "regions", None):
        for r in world.regions.values():
            for p in r.cells:
                region_of_tile.setdefault(tile_of(p), []).append(r.name)
        region_of_tile = {k: sorted(set(v)) for k, v in region_of_tile.items()}
    if region_of_tile:
        from .region import Region, _bbox

    manifest: List[dict] = []
    for k in sorted(set(groups) | set(be_groups) | set(ent_groups)):
        ix, iy, iz = k
        lo = V(b.lo.x + ix * chunk, b.lo.y + iy * chunk, b.lo.z + iz * chunk)
        sub = World()
        sub.cells = {p - lo: blk for p, blk in groups.get(k, {}).items()}
        sub.block_entities = {p - lo: nbt for p, nbt in be_groups.get(k, {}).items()}
        for e in ent_groups.get(k, []):
            d = dict(e)
            if "Pos" in d:
                d["Pos"] = [d["Pos"][0] - lo.x, d["Pos"][1] - lo.y, d["Pos"][2] - lo.z]
            sub.entities.append(d)

        # 区域也裁到本块（导入回去后每块有自己的区域片段）
        for nm in region_of_tile.get(k, ()):
            r = world.regions[nm]
            # **遍历 `sub.cells` 而不是 `r.cells`**：一块只有几万格，
            # 一个区域可能有几百万格。顺带修了个静默 bug ——
            # 原写法拿**世界坐标**去查**块内局部坐标**的字典（`p in sub.cells`），
            # 只有 `lo == (0,0,0)` 时才成立，等于区域从来没被正确裁过。
            cells = {q for q in sub.cells if (q + lo) in r.cells}
            if not cells:
                continue
            nr = Region(nm, sub)
            nr.cells = cells
            nr.box = _bbox(cells)
            sub.regions[nm] = nr

        name = f"{prefix}_{ix}_{iy}_{iz}.{ext}"
        path = os.path.join(out_dir, name)
        if ext == "nbt":
            export_nbt(sub, path, data_version=data_version, apply_conn=apply_conn)
        else:
            export_schem(sub, path, apply_conn=apply_conn)
        sb = sub.bounds()
        manifest.append({
            "file": name,
            # 该块**实际**覆盖的世界范围（可能小于 chunk；导出文件是紧凑的 0-based）
            "box": box(lo + sb.lo, lo + sb.hi) if sb else box(lo, lo),
            "blocks": len(sub.cells),
        })
    # 残留瓦片：只报告，不删除。重建方（`import_tiled`）只认清单里列出的文件，
    # 所以残留文件天然被忽略；这里把数量报出来，让人知道该清目录了。
    if stale_out is not None and prefix:
        import glob as _glob
        wrote = {it["file"] for it in manifest}
        for p in sorted(_glob.glob(os.path.join(out_dir, f"{prefix}_*.{ext}"))):
            if os.path.basename(p) not in wrote:
                stale_out.append(p)

    # **把清单落盘。** 没有它，`import_tiled` 就只能靠"文件名索引 × chunk + 包围盒 lo"
    # 去**推断**每块的位置 —— 而那是错的：文件里的 `pos` 是相对**该块内容的紧包围盒**
    # （见 `export_nbt` 里那句 `p.x - b.lo.x`），中间那一项在文件里根本找不到
    # （`min(pos)` 恒为 0，导出时就丢了）。推断出来的位置**每块都偏**，
    # 而 zlib/NBT/扇区这些局部校验全都会通过，只有人眼看得见错位。
    if manifest_path:
        import json
        os.makedirs(os.path.dirname(os.path.abspath(manifest_path)),
                    exist_ok=True)
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump({"tool": "mcbuild.export_tiled", "version": 1,
                       "prefix": prefix, "chunk": chunk, "ext": ext,
                       "lo": [b.lo.x, b.lo.y, b.lo.z],
                       "count": len(manifest), "blocks": sum(
                           it["blocks"] for it in manifest),
                       "parts": [dict(file=it["file"],
                                      box=[list(it["box"].lo),
                                           list(it["box"].hi)],
                                      blocks=it["blocks"]) for it in manifest]},
                      f, ensure_ascii=False)
    return manifest


def _pal_key(entry) -> str:
    """调色板项 -> 方块状态字符串。**`_pal_entry` 的逆操作**，往返无损。

    属性按名字排序 —— 顺序不影响语义，但排一下能让两次导出的文件逐字节可比。
    """
    name = entry["Name"]
    props = entry.get("Properties") or {}
    if not props:
        return name
    return name + "[" + ",".join(f"{k}={props[k]}"
                                 for k in sorted(props)) + "]"


def import_tiled(out_dir, parts=None, manifest_path=None, world=None,
                 on_block=None):
    """`export_tiled` 的**逆操作** —— 把瓦片读回一个世界。返回 ``(World, dict)``。

    **必须给 `parts`（就是 `export_tiled` 的返回值）或 `manifest_path`
    （`export_tiled(..., manifest_path=...)` 落盘的清单）。不给就报错。**

    为什么禁止"从文件名推断"：瓦片文件里的 `pos` 是相对**该块内容的紧包围盒**
    的（`export_nbt` 内部又平移了一次），而"块原点 → 紧包围盒 lo"那一项
    在文件里**根本不存在** —— `min(pos)` 恒为 0，导出那一刻就丢了。
    于是任何基于"文件名索引 × chunk + 世界包围盒 lo"的推断都会**每块都偏**，
    而 zlib 能不能解、NBT 能不能解析、扇区表自不自洽**全部照样通过**。
    唯一的防线就是把每块的实际世界范围记在清单里。

        parts = w.export_tiled("out/t", chunk=48, manifest_path="out/t.json")
        w2, st = io.import_tiled("out/t", manifest_path="out/t.json")
        assert st["blocks"] == w.count()

    **两种用法**：

    * 默认返回一个 `World`（便利，但要装下全部方块）。
    * 传 `on_block=fn` 时**不建 World**，改为对每格调 `fn((x, y, z), key_str)` ——
      大世界逐区域流式处理时用这个，峰值内存从"整张图"降到"一个区域"。
      此时返回的 World 是 `None`。
    """
    from .world import World

    import os

    if parts is None:
        if not manifest_path:
            raise ValueError(
                "import_tiled 需要 parts=（export_tiled 的返回值）或 "
                "manifest_path=；**不能靠文件名推断位置**（见函数说明）")
        import json
        with open(manifest_path, encoding="utf-8") as f:
            parts = json.load(f)["parts"]

    w = None if on_block is not None else (world if world is not None else World())
    n, nent = 0, 0
    for it in parts:
        name = it["file"]
        if not name.endswith(".nbt"):
            raise ValueError(
                f"import_tiled 只认 ext='nbt' 的结构方块瓦片，收到 {name!r}。"
                f".schem 瓦片的调色板语义不同（Sponge 调色板含 data 版本），"
                f"要对齐得单独实现，不能复用这条路径。")
        with open(os.path.join(out_dir, name), "rb") as f:
            _root_name, root = loads_nbt_gz(f.read())
        pal = [_pal_key(pe) for pe in root["palette"]]
        lx, ly, lz = it["box"][0]
        for b in root.get("blocks", []):
            px, py, pz = b["pos"]
            pos = (lx + px, ly + py, lz + pz)
            if on_block is None:
                w.set(pos, parse_block_key(pal[b["state"]]))
            else:
                on_block(pos, pal[b["state"]])
            n += 1
        for e in root.get("entities", []):
            raw = dict(e.get("nbt") or {})
            p = e.get("pos")
            if p is not None and len(p) == 3:
                raw["Pos"] = [lx + float(p[0]), ly + float(p[1]),
                              lz + float(p[2])]
            if w is not None:
                w.entities.append(raw)
            nent += 1
    return w, {"tiles": len(parts), "blocks": n, "entities": nent,
               "cells": None if w is None else len(w.cells)}


def merge(world, other, on_conflict: str = "overwrite",
          regions: bool = True) -> dict:
    """把另一个世界（或 ``{位置: 方块}``）合并进来，**带回冲突报告**。

    协作场景下这是必需的一步：两个 agent 各自建完、合并时"谁压了谁"
    必须能查到，而不是静默覆盖。

    | ``on_conflict`` | 冲突位置（两边都有方块且不同）怎么办 |
    |---|---|
    | ``"overwrite"``（默认） | 用 ``other`` 的 |
    | ``"skip"`` | 保留自己的 |
    | ``"report"`` | **不写入**，只在报告里列出来，让你先看 |

    返回::

        {"added": 1200,        # 新增（原本是空气）
         "overwritten": 5,     # 被覆盖
         "skipped": 0,         # 主动跳过
         "conflict_count": 5,  # 冲突总数
         "conflicts": [(位置, 我的, 对方的), ...],   # 最多 50 条
         "regions": ["island_b", "island_b/pav"],   # 带过来的区域
         "entities": 2}

    "冲突"的判断用归一化比较 —— 一边写 `hinge` 一边缺省不算冲突。
    """
    from .block import normalize
    from .region import Region, _bbox

    if on_conflict not in ("overwrite", "skip", "report"):
        raise ValueError('on_conflict 只能是 overwrite / skip / report，'
                         f"收到 {on_conflict!r}")

    added = overwritten = skipped = 0
    conflicts = []
    oc = getattr(other, "cells", other)

    with world._tx("merge"):
        for p, b in oc.items():
            cur = world.get(p)
            if normalize(cur) == normalize(b):
                continue                       # 两边一致，不动
            if cur.is_air:
                world._write(p, b)
                added += 1
                continue
            conflicts.append((p, cur, b))
            if on_conflict == "overwrite":
                world._write(p, b)
                overwritten += 1
            elif on_conflict == "skip":
                skipped += 1
            # "report" 不写

        for p, nbt in getattr(other, "block_entities", {}).items():
            if p in world.cells and not world.get(p).is_air:
                world.block_entities[p] = nbt
        ents = list(getattr(other, "entities", []))
        world.entities.extend(ents)

        # 区域：带过来，重名的加 @2
        brought = []
        if regions and getattr(other, "regions", None):
            mapping = {}
            for r in other.regions.values():
                n = _unique_region_name(world, r.name)
                new = Region(n, world)
                new.cells = set(r.cells)
                new.box = _bbox(new.cells)
                world.regions[n] = new
                mapping[r.name] = new
                brought.append(n)
            for r in other.regions.values():
                if r.parent is not None and r.parent.name in mapping:
                    mapping[r.name].parent = mapping[r.parent.name]

    conflicts.sort(key=lambda c: (c[0].y, c[0].z, c[0].x))
    return {
        "added": added,
        "overwritten": overwritten,
        "skipped": skipped,
        "conflict_count": len(conflicts),
        "conflicts": conflicts[:50],
        "regions": brought,
        "entities": len(ents),
    }


def import_schem(path, world=None, at=None, regions: bool = True,
                 name: Optional[str] = None, prefix: str = "") -> "object":
    """读 Sponge ``.schem``（v2/v3）并合并进 world。

    ``at=None`` 时用文件里的 ``Offset``（也就是导出时的世界原点），
    这样"导出再导入"能还原到原来的位置；显式给 ``at`` 则落到指定坐标，
    用于把外部下载的零件摆到想要的地方::

        w = World()
        w.import_schem("castle_tower.schem", at=(10, 64, 10))

    **区域**（``regions=True``）：

    * 文件里带区域元数据（本库导出的 `.schem` 都有）→ 还原它们，父子关系一并恢复
    * 没带（外部下载的文件）→ 用 ``name``（默认取文件名）建一个区域，
      把整块圈进去。这样导入的东西仍然可以单独搬移 / 导出

    ``prefix`` 给所有导入的区域名加前缀；重名会自动加 ``@2`` 后缀，
    不会静默盖掉已有的区域。
    """
    import os

    from .region import Region, _bbox
    from .world import World

    with open(path, "rb") as f:
        data = f.read()
    _, root = loads_nbt_gz(data)
    s = root.get("Schematic", root)
    W, H, L = int(s["Width"]), int(s["Height"]), int(s["Length"])
    blocks = s.get("Blocks", {})
    inv = {int(v): k for k, v in blocks.get("Palette", {}).items()}
    if at is None:
        off = s.get("Offset")
        base = V(int(off[0]), int(off[1]), int(off[2])) if off else V(0, 0, 0)
    else:
        base = V(int(at[0]), int(at[1]), int(at[2]))
    w = world if world is not None else World()
    payload = blocks.get("Data", b"")
    i = 0
    written = set()
    with w._tx("import_schem", path=str(path)):
        for y in range(H):
            for z in range(L):
                for x in range(W):
                    idx, i = _read_varint(payload, i)
                    key = inv.get(idx)
                    if key is None or key == "minecraft:air":
                        continue
                    p = base + V(x, y, z)
                    w._write(p, parse_block_key(key))
                    written.add(p)
        for be in blocks.get("BlockEntities", []) or []:
            pos = be.get("Pos")
            if not pos:
                continue
            p = base + V(int(pos[0]), int(pos[1]), int(pos[2]))
            w.block_entities[p] = {k: v for k, v in be.items()
                                   if k not in ("Id", "Pos")}
        for e in s.get("Entities", []) or []:
            d = dict(e)
            eid = d.pop("Id", None) or d.pop("id", None)
            if eid:
                d["id"] = eid
            pos = d.pop("Pos", None)
            if pos is not None and len(pos) == 3:
                d["Pos"] = [float(base.x) + float(pos[0]),
                            float(base.y) + float(pos[1]),
                            float(base.z) + float(pos[2])]
            w.entities.append(d)

    if regions:
        meta = s.get("MCBuild")
        entries = meta.get("Regions") if meta else None
        if entries:
            _des_regions_rel(w, entries, base, prefix)
        elif written:
            rname = name or os.path.splitext(os.path.basename(str(path)))[0]
            n = _unique_region_name(w, rname, prefix)
            r = Region(n, w)
            r.cells = set(written)
            r.box = _bbox(r.cells)
            w.regions[n] = r
    return w
