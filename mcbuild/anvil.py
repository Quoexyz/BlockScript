"""把体素世界写成 Minecraft Java 版**存档**（Anvil 区域文件）。

为什么要有这个模块
------------------
`.schem` / 结构方块 NBT / 自研 `.json` 三个出口全是"给工具的中间格式"，
都要在游戏里手工落地。真正常用的是"给一个能直接扔进 `saves/` 打开的世界"，
这个模块补的就是这一块：`write_save()` 一次写全 `level.dat` + `region/*.mca`。

    from mcbuild import World
    from mcbuild import anvil

    w = World()
    w.fill(...)
    anvil.write_save(w, "D:/mc/saves/MY_WORLD", name="MY_WORLD")

格式依据（`minecraft.wiki`，1.21.x）
----------------------------------
* 区块 NBT 自 1.18 起**不再是 `Level` 包裹**，字段直接挂根：`DataVersion` /
  `xPos` / `zPos` / `yPos` / `Status` / `sections` / `LastUpdate` …
* `sections[]` 三项：`Y`（**绝对** Y，byte）、`block_states`、`biome`（1.21.x 是单数）。
* `block_states = {palette, data}`：
  - **调色板只有 1 项时 `data` 必须省略** —— 这条对稀疏内容特别重要，
    大量 section 就是单一方块或纯空气。
  - 位宽：方块 `c≤16 → 4`，`c>16 → ⌈log2 c⌉`；生物群系 `⌈log2 c⌉`（**没有 4 的下限**）。
  - 每个 long 装 `u = ⌊64/bits⌋` 个条目，剩余高位补零 —— **条目绝不跨 long**。
  - 索引：方块 `i = 256·(y&15) + 16·(z&15) + (x&15)`；生物群系 `i = 16·(y&3) + 4·(z&3) + (x&3)`。
* 亮度（`BlockLight`/`SkyLight`）与 `Heightmaps` **整段省略**，游戏会自己重算；
  此时 `isLightOn` 必须为 0（不写时的默认值），免得游戏以为光照已经有了。
* 区域文件 `r.<cx>>5>.<cz>>5>.mca`；8 KiB 头部 = 1024 项位置表（前 3 字节起始扇区
  + 第 4 字节扇区数）+ 1024 个 4 字节时间戳；负载 = 4 字节大端长度（**含**压缩类型
  字节）+ 1 字节类型（2 = zlib）+ 数据；**每块补零到 4 KiB，文件末尾也必须补齐**。

两个几乎看不出来的坑（都是自检回读抓出来的）
--------------------------------------------
* **调色板 0 号必须是空气。** 索引数组是定长 4096，没写到的格子保持 0；
  调色板里若没有空气，那些格子就会变成 `pal[0]` 那个真实方块，整个子区块被它填满。
  文件照样能解析、格数却对不上 —— 见 `make_section()`。
* **负载长度字段要把压缩类型那 1 个字节算进去**（`len(compressed) + 1`），
  少 1 的话游戏侧解压报 incomplete stream，很难反向定位 —— 见 `write_region()`。

已知未证实项（写在这里免得下次又去查）
--------------------------------------
* **空 section 写不写**：`minecraft.wiki/Chunk_format` 说"所有高度的子区块都在
  列表里"，老页 `Anvil_file_format` 说"空 section 不保存"。本模块**默认省略**
  （1.18+ 读缺失 section 时会构造空 section），可用 `include_empty=True` 全写。
* `Heightmaps` 是 36 还是 37 个 long 两处说法冲突 —— 所以我们**根本不写**它。
* `level.dat` 各字段的"必选性"官方没有标注。

高度范围的坑（**用平移绕开了**）
--------------------------------
`minecraft:flat` 生成器的高度范围有两种说法：`−64..319`（继承 overworld 维度类型）
或 `0..384`。任何要写进原版主世界高度范围的内容，**同时满足两者的唯一窗口是
`[0, 319]`** —— 所以 `write_save()` 会**自动把内容平移到最低点 = 0**，并断言跨度 < 319。
这样无论哪种说法为真都能落地，不用去赌。
"""

from __future__ import annotations

import os
import zlib

from .io import (B, C, I, LA, Lg, Lst, Str,
                 TAG_COMPOUND, TAG_INT, TAG_LIST, TAG_STRING,
                 dumps_nbt, dumps_nbt_gz, loads_nbt, loads_nbt_gz)

#: 1.21.8 的 DataVersion（minecraft.wiki）。写错会触发 DataFixer 升级路径，
#: 甚至静默改写方块。**换目标版本时必须同步改这里。**
DATA_VERSION = 4440

#: 区块边长（Minecraft 恒定 16）。
CHUNK = 16
#: 区域文件一个边长 512 方块 = 32×32 个区块。
REGION = 512
#: 扇区大小，Anvil 恒定。
SECTOR = 4096

#: 写进去的群系。内容本身不依赖群系；配合全空气的平坦生成器时统一用 `the_void`。
BIOME = "minecraft:the_void"

#: 内容允许的最大纵向跨度。`[0,319]` 与 `[−64,384)` 两个候选范围的交集是 319 格。
MAX_SPAN = 319


# ---------------------------------------------------------------- 调色板

def pal_entry(key: str) -> C:
    """把 `minecraft:oak_stairs[facing=north,half=bottom]` 拆成区块调色板项。

    与 `mcbuild.io._pal_entry` 同构（那个是私有的，这里自己来一份，
    免得导出路径和存档路径耦合）。
    """
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


# ---------------------------------------------------------------- 位打包

def _signed64(v: int) -> int:
    """NBT 的 long 是**有符号**的：`struct.pack(">q")` 拒绝 ≥2⁶³ 的值。

    4 位宽 × 16 条目刚好用满 64 位，最高那个 long 很容易摸到 2⁶³ ——
    所以要显式折回负数，否则写盘时直接抛 struct.error。
    """
    v &= (1 << 64) - 1
    return v - (1 << 64) if v >= (1 << 63) else v


def pack(indices, bits: int, n: int) -> LA:
    """把 `n` 个调色板索引按 `bits` 位宽打包成 long 数组。

    **低位先填、填满一个 long 直接跳到下一个** —— 条目不跨 long 边界
    （1.16 起的"紧凑"布局，1.21 仍是这个）。读回公式：
    `(data[i//u] >> ((i%u)*bits)) & ((1<<bits)-1)`，`u = 64//bits`。
    """
    per = 64 // bits
    out = [0] * ((n + per - 1) // per)
    mask = (1 << bits) - 1
    for i in range(n):
        v = indices[i] & mask
        if v:
            out[i // per] |= v << ((i % per) * bits)
    return LA(_signed64(v) for v in out)


def bits_for(count: int, floor4: bool = True) -> int:
    """调色板 `count` 项需要几位。

    方块有 4 的下限（1.18 起 `c≤16` 都用 4 位）；**生物群系没有下限**。
    """
    b = 1 if count <= 1 else (count - 1).bit_length()
    return max(4, b) if floor4 else b


# ---------------------------------------------------------------- section

def make_section(sy: int, blocks: dict, biome: str = BIOME) -> C:
    """造一个子区块。`blocks` 的键是**子区块内局部坐标** `(x, y, z)` ∈ [0,16)³。

    `blocks` 为空时返回 `None` —— 调用方据此决定要不要写这个 section。
    """
    if not blocks:
        return None
    # **0 号必须是空气。** `idx` 是定长 4096 的数组，没被写到的格子保持 0 ——
    # 如果调色板里没有空气，那些格子就会变成 `pal[0]` 这个真实方块，
    # 整个子区块被它填满。这是个很难看出来的错：文件能解析、格数也对不上。
    pal = ["minecraft:air"]
    pos = {"minecraft:air": 0}
    idx = [0] * 4096
    for (x, y, z), key in blocks.items():
        j = pos.get(key)
        if j is None:
            j = len(pal)
            pal.append(key)
            pos[key] = j
        idx[256 * y + 16 * z + x] = j
    bs = C({"palette": Lst([pal_entry(k) for k in pal], TAG_COMPOUND)})
    if len(pal) > 1:                      # 只有一种方块状态 → `data` 必须省略
        bs["data"] = pack(idx, bits_for(len(pal)), 4096)
    return C({
        "Y": B(sy),
        "block_states": bs,
        "biome": C({"palette": Lst([Str(biome)], TAG_STRING)}),
    })


def make_chunk(cx: int, cz: int, sections: dict,
               data_version: int = DATA_VERSION, include_empty: bool = False,
               y_min: int = -4, y_max: int = 20) -> bytes:
    """造一个区块的 NBT 负载（未压缩）。

    `sections` 是 `{绝对 section Y: {局部坐标: 方块键}}`。
    `include_empty=True` 会把 `y_min..y_max` 之间的空 section 也写出来
    （官方两处文档对"空 section 要不要写"说法冲突，见文件头）。
    """
    ys = range(y_min, y_max + 1) if include_empty else sorted(sections)
    out = []
    for sy in ys:
        s = make_section(sy, sections.get(sy, {}))
        if s is not None:
            out.append(s)
    root = C({
        "DataVersion": I(data_version),
        "xPos": I(cx),
        "zPos": I(cz),
        "yPos": I(y_min),            # 最低子区块 Y；wiki 说它不参与加载
        "Status": Str("minecraft:full"),
        "LastUpdate": Lg(0),
        "InhabitedTime": Lg(0),
        "sections": Lst(out, TAG_COMPOUND),
        # BlockLight / SkyLight / Heightmaps / isLightOn **一律不写** →
        # 游戏自己重算光照与高度图（`isLightOn` 缺失时默认 false，正是我们要的）
        "block_entities": Lst([], TAG_COMPOUND),
        "block_ticks": Lst([], TAG_COMPOUND),
        "fluid_ticks": Lst([], TAG_COMPOUND),
        "PostProcessing": Lst([], TAG_LIST),
        "structures": C({"starts": C({}), "References": C({})}),
    })
    return dumps_nbt("", root)


# ---------------------------------------------------------------- region

def write_region(path: str, chunks: dict) -> dict:
    """写一个 `.mca`。`chunks` 是 `{(chunkX, chunkZ): 未压缩负载}`。返回统计。"""
    loc = [0] * 1024
    cnt = [0] * 1024
    blob = bytearray()
    for (cx, cz) in sorted(chunks):
        body = zlib.compress(chunks[(cx, cz)], 6)
        # **长度字段含压缩类型那 1 个字节** —— 写成 len(body) 会少 1，
        # 症状是"文件生成了、游戏侧解压报 incomplete stream"，很难反向定位。
        payload = (len(body) + 1).to_bytes(4, "big") + b"\x02" + body
        pad = (-len(payload)) % SECTOR
        i = (cx & 31) + (cz & 31) * 32
        loc[i] = 2 + len(blob) // SECTOR          # 前两个扇区是文件头
        cnt[i] = (len(payload) + pad) // SECTOR
        if cnt[i] > 255:
            raise ValueError(f"区块 ({cx},{cz}) 需要 {cnt[i]} 个扇区，超过 255 的上限")
        blob += payload + bytes(pad)
    if not blob:
        return dict(file=os.path.basename(path), chunks=0, bytes=0)
    head = bytearray(2 * SECTOR)
    for i in range(1024):
        head[4 * i:4 * i + 3] = loc[i].to_bytes(3, "big")
        head[4 * i + 3] = cnt[i]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(bytes(head))
        f.write(bytes(blob))
    n = 2 * SECTOR + len(blob)
    assert n % SECTOR == 0, "区域文件必须补齐到 4 KiB 边界"
    return dict(file=os.path.basename(path), chunks=len(chunks), bytes=n)


# ---------------------------------------------------------------- level.dat

def _flat_gen() -> C:
    """**全空气的平坦生成器** —— 这条决定了已写内容之外是不是空天。

    不写的话，游戏会按默认噪声地形生成已写区块之外的区域，
    于是内容外面长出一圈草地和山。`minecraft:flat` 固定使用单一生物群系
    （`settings.biome`）、海平面 -64、高度范围 0..384。
    """
    return C({
        "type": Str("minecraft:flat"),
        "settings": C({
            "layers": Lst([C({"block": Str("minecraft:air"), "height": I(1)})],
                          TAG_COMPOUND),
            "biome": Str(BIOME),
            "structure_overrides": Lst([], TAG_STRING),
        }),
    })


def write_level_dat(path: str, name: str = "WORLD", seed: int = 20260912,
                    spawn=(500, 300, 500), data_version: int = DATA_VERSION,
                    gamemode: int = 1) -> str:
    """写 `level.dat`（gzip 的 NBT）。`gamemode` 1 = 创造。"""
    sx, sy, sz = spawn
    flat = _flat_gen()
    dims = C({
        n: C({"type": Str(f"minecraft:{n.split(':')[1]}"), "generator": flat})
        for n in ("minecraft:overworld", "minecraft:the_nether", "minecraft:the_end")
    })
    data = C({
        "DataVersion": I(data_version),
        "version": I(19133),
        "LevelName": Str(name),
        "initialized": B(1),
        "allowCommands": B(1),
        "GameType": I(gamemode),
        "Time": Lg(6000),
        "DayTime": Lg(6000),
        "LastPlayed": Lg(0),
        "WasModded": B(0),
        "ServerBrands": Lst([Str("vanilla")], TAG_STRING),
        "spawn": C({"dimension": Str("minecraft:overworld"),
                    "pos": Lst([I(sx), I(sy), I(sz)], TAG_INT),
                    "pitch": I(0), "yaw": I(0)}),
        "DataPacks": C({"Enabled": Lst([Str("vanilla")], TAG_STRING),
                        "Disabled": Lst([], TAG_STRING)}),
        "difficulty_settings": C({"difficulty": Str("normal"), "hardcore": B(0),
                                  "locked": B(0)}),
        "GameRules": C({"doDaylightCycle": Str("false"),
                        "doWeatherCycle": Str("false"),
                        "doMobSpawning": Str("false"),
                        "keepInventory": Str("true")}),
        "WorldGenSettings": C({
            "seed": Lg(seed),
            "generate_features": B(0),
            "bonus_chest": B(0),
            "dimensions": dims,
        }),
    })
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(dumps_nbt_gz("", C({"Data": data})))
    return path


# ---------------------------------------------------------------- 总入口

def write_save(world, out_dir: str, name: str = "WORLD", seed: int = 20260912,
               data_version: int = DATA_VERSION, shift: int = None,
               include_empty: bool = False, verbose: bool = True) -> dict:
    """把 `world` 写成一个能直接扔进 `saves/` 的存档目录。

    目录结构（1.21.x）：`<out>/level.dat` + `<out>/region/r.*.mca`
    （`entities/`、`poi/` 可以为空，26.1 起才搬到 `dimensions/` 下面，别用错）。

    `shift` 为 `None` 时**自动把内容平移到最低点 = 0** —— 见文件头「高度范围的坑」。
    """
    b = world.bounds()
    if b is None:
        raise ValueError("空世界，无法写存档")
    span = b.hi.y - b.lo.y + 1
    if span > MAX_SPAN:
        raise ValueError(
            f"内容纵向跨度 {span} 格 > {MAX_SPAN}（[0,319] 与 [−64,384) 的交集）。"
            f"必须整体压缩或分带，不能硬塞。")
    if shift is None:
        shift = -b.lo.y                      # 最低点落到 y=0

    # 按区块聚合：{(cx,cz): {sectionY: {(x,y,z)局部: 键}}}
    buckets: dict = {}
    for p, blk in world.cells.items():
        if blk.is_air:
            continue
        wy = p.y + shift
        cx, cz = p.x >> 4, p.z >> 4
        sy = wy >> 4
        seg = buckets.setdefault((cx, cz), {}).setdefault(sy, {})
        seg[(p.x & 15, wy & 15, p.z & 15)] = blk.key()

    # 按区域分组写盘（一次只驻留一个区域的内容）
    regions: dict = {}
    for (cx, cz) in buckets:
        regions.setdefault((cx >> 5, cz >> 5), []).append((cx, cz))

    files, nblocks = [], 0
    for (rx, rz) in sorted(regions):
        pack_chunks = {}
        for (cx, cz) in regions[(rx, rz)]:
            secs = buckets[(cx, cz)]
            nblocks += sum(len(v) for v in secs.values())
            pack_chunks[(cx, cz)] = make_chunk(
                cx, cz, secs, data_version=data_version,
                include_empty=include_empty,
                y_min=min(secs), y_max=max(secs))
        p = os.path.join(out_dir, "region", f"r.{rx}.{rz}.mca")
        files.append(write_region(p, pack_chunks))
        if verbose:
            print(f"    region r.{rx}.{rz}.mca  "
                  f"{files[-1]['chunks']:>4d} 区块  "
                  f"{files[-1]['bytes']/1048576:.1f} MB")

    for d in ("entities", "poi"):
        os.makedirs(os.path.join(out_dir, d), exist_ok=True)
    top = min(b.hi.y + shift + 5, 318)
    write_level_dat(os.path.join(out_dir, "level.dat"), name=name, seed=seed,
                    spawn=(b.lo.x + (b.hi.x - b.lo.x) // 2, top,
                           b.lo.z + (b.hi.z - b.lo.z) // 2),
                    data_version=data_version)
    return dict(dir=out_dir, regions=files, blocks=nblocks, shift=shift,
                cells=world.count(), span=span,
                bytes=sum(f["bytes"] for f in files))


# ---------------------------------------------------------------- 离线校验

def verify_save(out_dir: str, expect_blocks: int = None) -> dict:
    """**不启动游戏**地反解回读，证明写出来的文件是合法的。

    做四件事：解析每个 region 的头部与负载 → 解 zlib → 解析 NBT →
    按 `bits` 位宽解包还原调色板索引 → 数方块。再断言：
    文件长度是 4 KiB 的整数倍、每个位置项的扇区数与偏移自洽、方块总数与预期一致。

    这不能替代"真的用游戏打开一次"，但能把**格式错误**和**丢方块**全挡在前面。
    """
    reg_dir = os.path.join(out_dir, "region")
    total, nchunk, problems = 0, 0, []
    for fn in sorted(os.listdir(reg_dir)):
        if not fn.endswith(".mca"):
            continue
        path = os.path.join(reg_dir, fn)
        raw = open(path, "rb").read()
        if len(raw) % SECTOR:
            problems.append(f"{fn}: 文件长度 {len(raw)} 不是 4 KiB 整数倍")
        for i in range(1024):
            off = int.from_bytes(raw[4 * i:4 * i + 3], "big")
            cnt = raw[4 * i + 3]
            if not cnt:
                continue
            if off < 2 or (off + cnt) * SECTOR > len(raw):
                problems.append(f"{fn}: 第 {i} 项越界 off={off} cnt={cnt}")
                continue
            seg = raw[off * SECTOR:(off + cnt) * SECTOR]
            ln = int.from_bytes(seg[:4], "big")
            if seg[4] != 2:
                problems.append(f"{fn}: 第 {i} 项压缩类型 {seg[4]} != 2")
                continue
            # 长度字段含类型字节：`1 + len(compressed)`
            if 4 + ln > cnt * SECTOR:
                problems.append(f"{fn}: 第 {i} 项长度 {ln} 超出分配的 {cnt} 扇区")
                continue
            try:
                # **region 负载是 `zlib` 压缩的裸 NBT**，不是 gzip 的 ——
                # 只有 `level.dat` 才用 gzip。这里套错一层会报 BadGzipFile。
                _nm, root = loads_nbt(zlib.decompress(seg[5:ln + 4]))
            except Exception as e:                              # noqa: BLE001
                problems.append(f"{fn}: 第 {i} 项解析失败 {type(e).__name__}: {e}")
                continue
            nchunk += 1
            total += _count_chunk_blocks(root, problems, fn, i)
    ok = not problems and (expect_blocks is None or total == expect_blocks)
    return dict(chunks=nchunk, blocks=total, problems=problems[:20], ok=ok)


def _count_chunk_blocks(root: dict, problems: list, fn: str, i: int) -> int:
    """按位宽解包数方块 —— 顺便验证打包方向没写反。"""
    n = 0
    for s in root.get("sections", []):
        bs = s.get("block_states") or {}
        pal = bs.get("palette") or []
        if not pal:
            continue
        if len(pal) == 1:
            # 单元素调色板：整段都是它，且**不该**再写 `data`。
            # 我们只在整段全空气时才会走到这里（空气恒在 0 号，见 `make_section`）。
            if "data" in bs:
                problems.append(f"{fn}/{i}: 调色板只有 1 项却写了 data")
            if _air_index(pal) != 0:
                n += 4096
            continue
        data = bs.get("data")
        if data is None:
            problems.append(f"{fn}/{i}: 调色板 {len(pal)} 项却缺 data")
            continue
        b = bits_for(len(pal))
        per = 64 // b
        mask = (1 << b) - 1
        if len(data) != (4096 + per - 1) // per:
            problems.append(f"{fn}/{i}: data 长度 {len(data)} 与位宽 {b} 不符")
        # 0 号一定是空气（`make_section` 按出现顺序建调色板，而空气不写进 blocks），
        # 所以只要数"索引非 0"的格子 —— 但安全起见直接按名字判
        air = _air_index(pal)
        for k in range(4096):
            v = (data[k // per] >> ((k % per) * b)) & mask
            if v != air:
                n += 1
    return n


def _air_index(pal) -> int:
    for j, e in enumerate(pal):
        if e.get("Name") in ("minecraft:air", "minecraft:cave_air", "minecraft:void_air"):
            return j
    return -1                                # 调色板里没有空气 → 整段都算方块


def probe_column(out_dir: str, x: int, z: int, y0: int = -8, y1: int = 80,
                 step: int = 1) -> list:
    """**从存档里直接读一列方块**，y 从高到低。用来复核某个特征到底建出来没有。

    `verify_save()` 只能证明"文件合法、格数守恒"，证明不了"某一个洞被挖出来了" ——
    空气不占方块，丢了也数不出来。这个函数就是补这一刀：

        anvil.probe_column("D:/mc/saves/MY_WORLD", 0, 0)     # 看世界原点那一列

    返回 `[(y, 方块名或 None), ...]`，`None` 表示空气。
    """
    path = os.path.join(out_dir, "region", f"r.{x >> 9}.{z >> 9}.mca")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"没有区域文件 {path}")
    raw = open(path, "rb").read()
    cx, cz = x >> 4, z >> 4
    i = (cx & 31) + (cz & 31) * 32
    off = int.from_bytes(raw[4 * i:4 * i + 3], "big")
    cnt = raw[4 * i + 3]
    if not cnt:
        raise ValueError(f"区块 ({cx},{cz}) 在存档里不存在")
    seg = raw[off * SECTOR:(off + cnt) * SECTOR]
    ln = int.from_bytes(seg[:4], "big")
    _nm, root = loads_nbt(zlib.decompress(seg[5:ln + 4]))
    secs = {s["Y"]: s for s in root.get("sections", [])}
    out = []
    for y in range(y1, y0 - 1, -step):
        s = secs.get(y >> 4)
        name = None
        if s is not None:
            bs = s["block_states"]
            pal = bs.get("palette") or []
            k = 256 * (y & 15) + 16 * (z & 15) + (x & 15)
            if len(pal) == 1:
                v = 0
            else:
                b = bits_for(len(pal))
                per = 64 // b
                v = ((bs["data"][k // per] >> ((k % per) * b))
                     & ((1 << b) - 1))
            nm = pal[v]["Name"]
            name = None if nm.endswith(("air",)) else nm
        out.append((y, name))
    return out


def main() -> None:
    import time
    import tempfile

    from .world import World

    # **自检写到临时目录。** 写到固定的输出目录会覆盖真存档的 region 文件，
    # 而且 `verify_save()` 是扫整个 `region/` 目录的 —— 混在一起读，
    # 方块数必然对不上，报出来的错还指向"自检失败"，方向全错。
    out = os.path.join(tempfile.gettempdir(), "_mcbuild_anvil_selftest")
    reg = os.path.join(out, "region")
    if os.path.isdir(reg):                      # 只清 1 类文件，不触发批量删保护
        for fn in os.listdir(reg):
            if fn.endswith(".mca"):
                os.remove(os.path.join(reg, fn))
    print("=" * 74)
    print("Anvil 存档写入器自检")
    print("=" * 74)

    # 一个小世界：两个 section、含 17 种以上方块（逼出 bits=5 的分支）
    w = World()
    keys = ["minecraft:stone", "minecraft:dirt", "minecraft:grass_block",
            "minecraft:oak_log", "minecraft:oak_planks", "minecraft:sand",
            "minecraft:glass", "minecraft:bricks", "minecraft:gravel",
            "minecraft:clay", "minecraft:stone_bricks", "minecraft:gold_block",
            "minecraft:iron_block", "minecraft:coal_block", "minecraft:obsidian",
            "minecraft:netherrack", "minecraft:end_stone"]
    for k in range(300):
        w.set((k % 40, k // 40, (k * 7) % 40), keys[k % len(keys)])
    got = write_save(w, out, name="SELFTEST")
    print(f"  写入 {got['blocks']} 方块 / {len(got['regions'])} 区域 / "
          f"{got['bytes']/1024:.1f} KB  shift={got['shift']}")
    v = verify_save(out, expect_blocks=w.count())
    print(f"  回读 {v['chunks']} 区块 / {v['blocks']} 方块  ok={v['ok']}")
    for p in v["problems"]:
        print("    ✗", p)
    print()
    print("✓ 往返守恒，格式自洽" if v["ok"] else "✗ 有问题")


if __name__ == "__main__":
    main()
