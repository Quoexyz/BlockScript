# mcbuild 模型 API 手册

> **目标读者：LLM。代码量较大，非必要不读用不上的源码，这份文档就是全部接口。**
> 版本 0.3.1 · 2026-09-11 · 22 个模块 / `World` 上 82 个公开方法 / 零第三方依赖

---

## 1. 十二条铁律

违反这些的代码大概率跑不通或产出废建筑。**先读完这节再动手。**

| # | 铁律 | 原因 |
|---|---|---|
| 1 | **不写绝对坐标**。用 `frame` / `grid` / `anchor` 定位 | 大建筑里绝对坐标是模型最大的出错源 |
| 2 | **Frame 内朝向只写 `"+v"`**（我的前方），不写 `north/south` | 写死了 N/S 之后一旋转，你脑内那张图就废了 |
| 3 | **组件函数的第一个参数是 `target`**（World 或 Frame），内部一律用 `t.xxx()` | 这样才白拿局部坐标与朝向重映射，也才能用 `t.place()` 嵌套子组件 |
| 4 | **模板 `define` 必须写在 `stage` 函数外面** | 写在里面的话 `rerun` 会用旧模板把新模板覆盖回去 |
| 5 | **大建筑按 `stage` 分步 + `save`/`load`** | 一个阶段一个阶段做，上下文才不会越堆越长 |
| 6 | **对称结构用 `compare.symmetry` 自查** | 实测它在真实建筑上抓出过 42 处肉眼看不见的错误 |
| 7 | **`iso()` 必须带 `step`** | 25×25 的平面默认输出近百列 × 60 行，token 直接爆掉 |
| 8 | **写完用 `w.unknown_blocks()` / `registry.check()` 查一遍拼错的方块名** | 逐格写错名不会抛异常，会静默按实心方块处理 |
| 9 | **写完就渲染检查**；大范围或破坏性操作先 `w.preview(...)` 看报价 | 反馈闭环是这个框架的全部价值；大范围误操作很难精确回滚 |
| 10 | **重复单元用 `w.material(...)` 加材质差异** | 20 个开间像素级相同 = 一眼假 |
| 11 | **非法 blockstate 会抛异常**，不会静默兜底 | 这是故意的，早暴露早修 |
| 12 | **有多个独立单元时用 `w.region(...)` 分区**（建筑群 / 空岛群 / 以后想单独搬动的部件） | 单体建筑别分——分区是为了**操作**，不是为了整齐。判断见 §10.5 |

> ASCII 能验"几何对不对"，验不了"好不好看"。**美术验收用 `w.image` 渲一张 PNG
> 自己看**（§12.1）：配色、层次、云海形态这类问题只有看图才发现得了。
> 纯 ASCII 环境下可跳过，不影响构建流程。

---

## 2. 全部方法速查表

### 2.1 World（`world.py`）

| 方法 | 签名 | 说明 |
|---|---|---|
| `set` | `set(pos, block, nbt=None, **state) -> Block` | 写一个方块（`nbt` 给告示牌文字/箱子内容） |
| `get` | `get(pos) -> Block` | 读一个方块（空气返回 `AIR`） |
| `entity` | `entity(pos, id, **nbt) -> dict` | 放置实体（盔甲架 / 画 / 物品展示框） |
| `fill` | `fill(box, block, **state) -> int` | 填满闭区间盒，返回格数 |
| `clear` | `clear(box) -> int` | 清空区域 |
| `paint` | `paint(shape, brush, bx=None) -> int` | **用 Shape 定义几何、Brush 定义材质** |
| `erase` | `erase(shape, bx=None) -> int` | 按 Shape 挖空 |
| `repaint` | `repaint(mapping=None, *, family=None) -> int` | **整体换配色** |
| `replace` | `replace(box, src=None, dst="air") -> int` | 区域内 `src` 换 `dst`；`src=None` 表示空气 |
| `frame` | `frame(at=(0,0,0), yaw=0) -> Frame` | 建局部坐标系 |
| `mark` | `mark(name, pos) -> V` | 记点锚点 |
| `mark_box` | `mark_box(name, box) -> Box` | 记区域锚点 |
| `anchor` | `anchor(name) -> V` | 取点锚点（未定义抛 `KeyError`） |
| `bounds` | `bounds() -> Box \| None` | 全世界的包围盒 |
| `count` | `count() -> int` | 已占格数 |
| `dirty_box` | `dirty_box() -> Box \| None` | 相对基线（`checkpoint`）的改动范围 |
| `checkpoint` | `checkpoint()` | 把当前状态设为 diff 基线 |
| `undo` / `redo` | `-> bool` | 撤销 / 重做一层事务 |
| `material` | `material(mapping, seed=None)` | 材质混合上下文（位置哈希，确定性） |
| `preview` | `preview(fn, *args, **kwargs) -> Preview` | 干跑：先看后果再决定提交 |
| `region` | `region(name)` | 定义命名区域（可 `with`，可累积） |
| `region_of` | `region_of(name) -> Region` | 取已有区域 |
| `region_at` | `region_at(pos, solid_only=True) -> Region \| None` | 反查某坐标属于哪个区域（取最深） |
| `region_table` | `region_table(sort_by="name") -> List[dict]` | 区域一览（含层级与大小） |
| `unknown_blocks` | `unknown_blocks() -> List[(V, id, msg)]` | 列出拼错的方块 |
| `lint` | `lint() -> List[Issue]` | 物理校验 |
| `report` | `report(exec_line="", render_box=None) -> str` | 四段式反馈文本 |
| `save` / `load` | `save(path)` / `World.load(path)` | JSON 存档 / 读档 |
| `import_schem` | `import_schem(path, at=None)` | 读 `.schem` 合并进来（当零件用） |
| `export_tiled` | `export_tiled(dir, chunk=48, prefix)` | **分块导出**（结构方块 48³ 上限） |

属性：`w.query` · `w.render` · `w.image` · `w.compare` · `w.marks` · `w.cells` · `w.instances` · `w.stages` · `w.grids`

### 2.2 轴网（`grid.py`，挂在 World 上）

| 方法 | 签名 | 说明 |
|---|---|---|
| `grid` | `grid(name, origin, axis="z", spacing=1, n=1, axes=None) -> Grid` | 定义轴网 |
| `grid_at` | `grid_at(name, *idx) -> V` | 第 i 个格点 |
| `grid_cell` | `grid_cell(name, *idx, size=0) -> Box` | 第 i 格占的范围 |
| `grid_span` | `grid_span(name, *idx) -> Box` | 格点到格点 |
| `grid_cover` | `grid_cover(name, *idx) -> Box` | 第 i0..i1 格全部范围 |

### 2.3 组件（`component.py`，挂在 World 上）

| 方法 | 签名 | 说明 |
|---|---|---|
| `define` | `define(name, fn, replay=False)` | 注册/替换模板 |
| `template` | `template(name) -> callable` | 取模板 |
| `place` | `place(name, at=(0,0,0), yaw=0, **params) -> Instance` | 展开一个实例 |
| `instances_of` | `instances_of(name) -> List[Instance]` | 该模板的全部实例 |
| `instance` | `instance(name, index=0) -> Instance` | 按序号取实例（支持负数） |
| `replay` | `replay(name=None) -> int` | 按当前模板重放，返回重放个数 |
| `unlink` | `unlink(inst) -> Instance` | 断开同步（固化成独立体素） |
| `relink` | `relink(inst) -> Instance` | 恢复同步 |
| `patch` | `patch(inst, local, block, **state) -> Block` | 局部覆盖（**实例内局部坐标**） |
| `unpatch` | `unpatch(inst, local) -> bool` | 移除覆盖 |

### 2.4 比较器（`compare.py`，挂在 World 上）

| 方法 | 签名 | 说明 |
|---|---|---|
| `symmetry` | `symmetry(bx=None, axis="x", pivot=None) -> List[Diff]` | 镜像对称校验 |
| `rotational` | `rotational(bx=None, yaw=90, center=None) -> List[Diff]` | 旋转对称（区域须 x/z 等长） |
| `regions` | `regions(a, b, yaw=0) -> List[Diff]` | 两区域比对 |
| `instances` | `instances(name, i=0, j=1, orientation_blind=False) -> List[Diff]` | 两实例比对 |
| `diff` | `diff(after, before=None, mode="exact") -> DiffReport` | **结构化差异**（分类 + 按区域汇总） |
| `since_checkpoint` | `since_checkpoint(mode="exact") -> DiffReport` | 相对最近 `checkpoint()` 的变化 |
| `duplicates` | `duplicates(boxes, mode="shape") -> List` | 在一组区域里找重复的 |
| `fingerprint` | `fingerprint(bx=None, mode="exact")` | 平移不变的指纹 |
| `report` | `report(diffs, limit=20) -> str` | 格式化差异 |
| `is_symmetric` | `is_symmetric(bx=None, axis="x") -> bool` | 快捷判断 |

### 2.5 分步（`stage.py`，挂在 World 上）

| 方法 | 签名 | 说明 |
|---|---|---|
| `stage` | `stage(name, fn=None)` | 记一个阶段（传 fn 可 rerun；不传则当 `with` 用） |
| `stage_box` | `stage_box(name) -> Box \| None` | 该阶段的范围 |
| `revert_to` | `revert_to(name) -> List[str]` | 撤销该阶段及之后 |
| `rerun` | `rerun(name) -> List[str]` | 重跑该阶段及之后 |

### 2.6 形状原语（`ops.py`，World 与 Frame 都有）

**基础**
`line(a, b, block)` · `floor(box, block)` · `ceiling(box, block)` ·
`wall(box, block, thickness=1, skip=())` · `hollow_box(box, block)` · `pillar(pos, height, block)`

**圆 / 球 / 顶**
`cylinder(center, r, height, block, hollow=False)` · `dome(center, r, block, hollow=True)` ·
`sphere(center, r, block, hollow=True)` · 模块级：`disc_xz(center, r)` / `circle_xz(center, r)` 返回格子列表

**楼梯 / 屋顶**
`stairs_run(start, direction, n, block)` · `roof_gable(box, block, axis="x")` ·
`roof_pyramid(box, block)` · `spiral_stairs(center, r, turns, block)` · `arch(box, block, axis="z")`

**中式**
`hip_roof(box, block, axis="x", inset=None)` · `eave_ring(box, block, depth=1, y=None)` ·
`railing(box, block, rail_block=None, spacing=3, height=2)`

**区域变换**
`mirror(box, axis="x", pivot=None)` · `rotate_area(box, yaw=90, pivot=None)` ·
`translate_area(box, delta)` · `repeat(box, step, n)` · `stack(box, dy, n)`

### 2.7 查询（`w.query`）

| 方法 | 签名 | 说明 |
|---|---|---|
| `at` | `at(pos) -> Block` | 读方块 |
| `empty` | `empty(pos) -> bool` | 是否空气 |
| `count` | `count(pred=None) -> int` | 不传参 = 总数；传谓词 = 命中数 |
| `where` | `where(pred) -> List[V]` | 所有匹配格（已排序） |
| `nearest` | `nearest(origin, pred=None) -> V \| None` | 最近的匹配格；`origin` 可传锚点名 |
| `neighbors` | `neighbors(pos) -> Dict[str, Block]` | 六向邻居 |
| `raycast` | `raycast(origin, direction, max_dist=64) -> (V, Block, dist) \| None` | 射线检测 |
| `histogram` | `histogram(top=8) -> List[(key, n)]` | 材质统计 |
| `bounds` / `volume` / `density` | | 包围盒 / 体积 / 填充率 |
| `support_report` | `-> List[(V, Block, msg)]` | 会掉落的方块 |

`pred` 可以是：`None`（非空气）· `"door"`（子串匹配）· `Block` 对象 · `lambda b: ...`

### 2.8 渲染（`w.render`）

| 方法 | 签名 | 说明 |
|---|---|---|
| `slice` | `slice(y, bx=None, overlay=None, step=1) -> str` | 水平切片 |
| `section` | `section(axis="z", at=0, bx=None, step=1) -> str` | 垂直剖面 |
| `view` | `view(center, size=(16,12,16), step=1, overlay=None) -> str` | **视口三视图** |
| `overview` | `overview(y=None, step=8, center=None, size=None) -> str` | **全景 + 视口框** |
| `column` | `column(x, z) -> str` | 一列方块自上而下 |
| `diff` | `diff(step=1) -> str` | 只画本轮改动 |
| `summary` | `summary() -> str` | 范围 / 格数 / 材质 top / 锚点 |
| `legend` | `legend() -> str` | 材质图例 |
| `iso` | `iso(bx=None, step=1) -> str` | 等距投影 |
| `budget` | `budget(n) -> Render` | 设字符预算，超出自动降采样 |

`overlay="facing"` 单独渲染朝向层：`^`=-z(N) `v`=+z(S) `>`=+x(E) `<`=-x(W)

### 2.9 图像（`image.py`，挂在 World 上，`w.image`）

| 方法 | 签名 | 说明 |
|---|---|---|
| `render` | `render(out, bx=None, tw=8, bh=8, bg=…, horizon=…, sky_gain=0.10) -> str` | 渲成 PNG，返回路径 |
| `save` | `save(out, bx=None, **kw) -> str` | `render` 的别名 |
| `color` | `color(name, rgb) -> Image` | 登记/覆盖一个材质颜色（链式） |
| `colors` | `colors(mapping) -> Image` | 批量登记颜色（链式） |
| `palette` | `palette: Dict[str, RGB]` | 当前调色板，可直接 `update` |
| `preview` | `preview(path) -> str` | 尽力调用系统看图器（失败不抛） |

模块级：`DEFAULT_PALETTE` · `DEFAULT_COLOR` · `CLOUD_KINDS` · `canvas` 类 `Canvas`

### 2.10 方块（`block.py`）

`make(block, yaw=0, **state) -> Block` · `classify(id) -> 族名` ·
`rotate_block(b, yaw)` · `mirror_block(b, axis)` · `is_solid(b) -> bool`

模块级常量：`AIR` · `STAIRS_UPHILL`（楼梯 facing 语义，改它可全局翻转）

### 2.11 导入导出（`io.py`）

`export_schem` · `export_nbt` · `export_json` · `export_tiled` ·
`import_json` · `import_schem` · `merge`（带冲突报告）·
`loads_nbt` / `loads_nbt_gz`（NBT 解析）· `parse_block_key`

---

### 2.12 方块注册表（`mcbuild.registry`）

| 函数 | 说明 |
|---|---|
| `exists(name) -> bool` | 这个方块存在吗（非 `minecraft:` 命名空间一律放过） |
| `check(name) -> str \| None` | `None` 表示没问题，否则是带拼写候选的诊断 |
| `suggest(name, n=5) -> List[str]` | 按编辑距离给候选 |
| `search(pattern) -> List[str]` | 按子串搜索方块名 |
| `states(name) -> dict` | 属性定义：属性名 → 合法取值列表 |
| `defaults(name) -> dict` | 该方块的默认属性 |
| `label(name) -> str \| None` | 英文显示名 |
| `info() -> dict` | 数据来源与覆盖范围 |

数据来自 **prismarinejs/minecraft-data**（MIT），覆盖 1.21.x 的 **1196 个方块**，
随库分发（16 KB gzip），零第三方依赖。

---

## 3. 坐标与朝向

```
+X = 东    +Z = 南    +Y = 上      （与 Minecraft 一致）
box((x0,y0,z0),(x1,y1,z1))        闭区间，两端都含
yaw 只能是 0 / 90 / 180 / 270     顺时针（从上往下看）
```

`yaw` 的实际映射（`rot_y(v, yaw)`）：

| yaw | 局部 `+u` 落到 | 局部 `+v` 落到 |
|---|---|---|
| 0 | +X（东） | +Z（南） |
| 90 | +Z（南） | −X（西） |
| 180 | −X（西） | −Z（北） |
| 270 | −Z（北） | +X（东） |

`rot_y(V(1,0,0), 90) == V(0,0,1)`；`rot_y(V(0,0,1), 90) == V(-1,0,0)`

### 朝向符号

在 Frame 内写 `facing=` 时用这些（落世界时自动翻译成 `north/south/east/west`）：

```
+u / -u      沿局部 u 轴（Frame 内 = 我的右手 / 左手）
+v / -v      沿局部 v 轴（Frame 内 = 我的前方 / 后方）★ 最常用
+w / -w      上 / 下
front / back / left / right / up / down     同上，可读性更好
n / s / e / w                              也接受，但在 Frame 内不推荐
```

### Minecraft 的五套朝向属性（你只写一种，框架翻译）

| 方块族 | MC 实际属性 | 你写 |
|---|---|---|
| 楼梯 / 门 / 活板门 / 活塞 / 熔炉 | `facing=` | `facing="+v"` |
| 原木 / 柱 / 玄武岩 / 锁链 | `axis=` | `axis="y"` |
| 告示牌 / 头颅 / 旗帜 | `rotation=0..15` | `rotation=90`（也接受角度） |
| 门（`*_door`） | `half=upper/lower` | **上下两半各写一次**，不自动补（见下） |
| 床（`*_bed`） | `part=head/foot` | `part="head"`（床只有 head/foot，没有 half） |
| 连接类（墙 / 栅栏 / 玻璃板） | `north/east/...=true` | **不用写**，导出时自动算 |

### 实测补充（写实际建筑时踩出来的，与上表有关）

**1. 双格方块不会自动补另一半。** 门属于 `door` 族，只有 `facing / half / hinge / open / powered`，
没有 `part` 属性；写 `half="lower"` 只会落下半格，`lint` 报 `W2`：

```python
w.set((0, 64, 0), "oak_door", facing="south", half="lower")
w.set((0, 65, 0), "oak_door", facing="south", half="upper")   # ← 必须显式补上
# make("oak_door", part="upper")  →  BlockStateError（door 族不支持 part）
```

床走的是另一套：`part="head"` / `part="foot"`，同样要自己摆两格。

**2. `roof_gable` 的屋面会和拱顶筒壳互相穿插。** 屋面是后写的，会把已经铺好的
拱顶壳、肋券整段吃掉。动手前逐点验算一次净空（教堂实例的取值：檐口 99 / 正脊 111，
坡度 1.5，与拱顶最小留 2 格）。

**3. `roof_pyramid` 顶点格的 `facing` 不镜像对称**（`dx == 0` 时落到 `else` 分支付
`west`）。对称建筑的十字交叉面上会被 `compare.symmetry` 抓出来；改用"逐层四周收 1 格"
的自写实心攒尖顶。

**4. 组件模板必须在 `v` 方向自对称**（几何区间取 `[-a, a]` 或 `{0}`）。
实例用 `yaw=180` 镜像时 v 轴会翻转，模板在 v 上不对称会让镜像兄弟整体错开一格。

**5. 落在墙体中央的特征，中轴必须落在整数格。** 偶数长的墙（如 12 深）两侧端墙的
局部 u 轴天然差 1 格，窗、玫瑰窗永远对不齐 → 把开间做成奇数长（13 深）。

---

## 4. World：读写

```python
from mcbuild import World, box, V

w = World(seed=42)                      # seed 只影响 w.rng，建筑本身是确定性的
w.set((0, 64, 0), "stone")
w.fill(box((0, 64, 0), (7, 64, 7)), "oak_planks")
w.replace(box((0, 64, 0), (7, 3, 7)), src="stone", dst="bricks")
w.clear(box((0, 65, 0), (2, 65, 2)))
print(w.get((0, 64, 0)).short())        # 'oak_planks'
print(w.bounds(), w.count())            # Box((0,64,0),(7,64,7)) 64
```

**事务**：所有写入自动进 undo 栈。`w.checkpoint()` 设 diff 基线（不影响 undo）。

```python
w.checkpoint()
w.set((1, 65, 1), "gold_block")
print(w.render.diff())                  # 只画这一格的改动
w.undo()                                # 撤销
print(w.count())
```

### 材质混合 `w.material(...)`

让重复单元不再一模一样。上下文内的所有写入（`fill` / `wall` / `pillar` / 组件展开……）
都会按权重把方块换成变体：

```python
with w.material({"stone_bricks": {"cracked_stone_bricks": 0.12,
                                  "mossy_stone_bricks": 0.08}}):
    w.wall(box((0, 64, 0), (31, 71, 31)), "stone_bricks")
```

三条保证：

| 保证 | 原因 |
|---|---|
| **确定性**：同 seed 重跑逐格一致 | 图案由**位置哈希**决定（FNV-1a 纯整数运算），不用 `random`，也不受 `PYTHONHASHSEED` 影响 |
| **同组件不同实例图案不同** | 哈希输入是世界坐标 —— 20 个开间 place 到不同位置，纹理天然各不相同（这正是消除"复制粘贴感"的关键） |
| **模板改动不扰动别处** | 每个位置独立决定，不是随机序列，改一个位置不影响其他位置 |

变体与原方块**同族**时继承 state：

```python
with w.material({"spruce_stairs": {"oak_stairs": 0.3}}):
    w.stairs_run((0, 64, 0), "north", 6, "spruce_stairs")
# 变体仍是 oak_stairs[facing=north,half=bottom]，朝向没丢
```

`seed` 默认取 `World(seed=...)`；显式传参可让同一区域重复出同一图案。
`undo` 不会重新混合（撤销还原的是原样）。

### 形状与材质：`Shape` / `Brush`

`fill(box, block)` 是"形状 = 长方体、材质 = 常数"的特例。把两者拆开后，
**同一个形状换一个 brush 就换一种效果** —— 真实感的分界线往往就在"材质随位置变化"。

```python
from mcbuild import Shape, Brush

# 按高度风化：墙脚长苔 → 中段正常 → 上部干净
w.paint(Shape.box(box((0, 64, 0), (15, 84, 15))),
        Brush.by_height([(0.0, 0.25, "mossy_stone_bricks"),
                         (0.25, 0.70, "stone_bricks"),
                         (0.70, 1.01, "chiseled_stone_bricks")]))

# 布尔组合 + 按法线换材质
s = Shape.union(Shape.sphere((8, 80, 8), 10),
                Shape.box(box((0, 64, 0), (16, 80, 16))))
w.paint(Shape.subtract(s, Shape.sphere((8, 80, 8), 6)),
        Brush.by_normal({"up": "smooth_stone", "side": "stone_bricks",
                         "down": "deepslate"}))

w.erase(Shape.sphere((8, 70, 8), 5))          # 按形状挖空
```

**Shape 构造器**（几何）

| 构造器 | 说明 |
|---|---|
| `Shape.box(bx)` | 长方体 |
| `Shape.sphere(center, r)` / `Shape.ellipsoid(center, radii)` | 球 / 椭球（带解析法线） |
| `Shape.cylinder(center, r, height)` | 竖直圆柱（中心在下底圆心） |
| `Shape.torus(center, major, minor, axis="y")` | 圆环体（`major` 环半径 / `minor` 管半径） |
| `Shape.expr(pred, bounds)` | 任意谓词 `lambda p: ...` |
| `Shape.union(a, b, ...)` / `intersect` / `subtract(a, b)` | 布尔运算 |
| `Shape.hollow(shape, thickness=1)` | 只留外壳 |
| `Shape.warp(shape, amplitude=2.0, frequency=0.08, seed=0, octaves=1)` | **域变形**：用噪声揉坐标 |
| `Shape.lattice(bx, spacing, radius)` | 格状小球；配 `subtract` 挖规则孔洞阵列 |
| `Shape.field(center, radii, seed=0, frequency=0.09, threshold=-0.30)` | **噪声雕塑**：浮石 / 云团 / 岩体 |

后三个是"让几何自然起来"的主力。噪声由**位置哈希**驱动，同 seed 逐格可复现：

```python
# 规整的球揉一下就像岩石
w.paint(Shape.warp(Shape.sphere((0, 70, 0), 12), amplitude=2.5,
                   frequency=0.12, seed=5),
        Brush.by_normal({"up": "mossy_cobblestone", "side": "cobblestone"}))

# 立方体挖孔洞阵列（格状镂空）
bb = box((0, 64, 0), (23, 87, 23))
w.paint(Shape.subtract(Shape.box(bb), Shape.lattice(bb, spacing=8, radius=3.2)),
        Brush.solid("deepslate_tiles"))

# 云团 / 浮石：椭球内按噪声裁剪，填充率约一半
w.paint(Shape.field((0, 90, 0), (18, 10, 18), seed=3),
        Brush.gradient("y", [(0, "light_gray_concrete"), (10, "white_concrete")]))
```

`field` 的 `threshold` 越大越空（实测可调范围约 6%～85% 填充率），
`bias` 越大体积越向中心缩。

Shape 还提供 `shape.contains(p)`、`shape.bounds`、`shape.normal(p)`（体素差分估计）、
`shape.t(p)`（归一化参数，默认按高度：底 0 → 顶 1）。

**Brush 构造器**（材质）

| 构造器 | 说明 |
|---|---|
| `Brush.solid(block)` | 常数 |
| `Brush.by_height([(t0, t1, block), ...])` | 按 Shape 内归一化高度分段 |
| `Brush.by_normal({"up": ..., "side": ..., "down": ...})` | 按表面法线（可写六个方向或 `side`） |
| `Brush.by_distance(center, [(r0, r1, block), ...])` | 按到某点的距离 |
| `Brush.gradient(axis, [(坐标值, block), ...])` | 按**世界坐标**沿轴渐变 |
| `Brush.noise({block: 权重}, seed=0)` | 按位置哈希混合（确定性） |
| `Brush.fn(lambda p, shape: ...)` | 自定义，返回方块名或 `None`（跳过） |

`paint` 的遍历范围默认取 `shape.bounds`，可用 `bx=` 覆盖（必须包住所有命中坐标）。
两个操作都可 `undo`。

### 方块实体与实体

`set` 的 `nbt` 参数给方块实体数据；`entity` 放实体。导出时写进 `.schem` 的
`BlockEntities` / `Entities`，以及结构方块格式的对应字段。

```python
# 告示牌文字
w.set((0, 65, 0), "oak_sign", rotation=8,
      nbt={"front_text": {"messages": ['{"text":"滕王阁"}']}})

# 箱子内容（Items 用原始 NBT 结构，Slot 从 0 开始）
w.set((1, 64, 0), "chest",
      nbt={"Items": [{"Slot": 0, "id": "minecraft:diamond", "Count": 3}]})

# 实体：坐标自动 +0.5 居中（实体位置是浮点）
w.entity((4, 64, 4), "armor_stand", ShowArms=1)
w.entity((2, 66, 2), "painting", Facing=2, Motive="Kebab")
```

`nbt` 接受普通 Python dict（内部递归转 NBT）：`dict → Compound`、
`list → List`（元素类型必须一致）、`bool → Byte`、`int → Int`、`float → Double`。
方块被清空时，它上面的方块实体一并移除。

### 换配色 `w.repaint(...)`

迭代速度的瓶颈往往是换配色，不是建模。

```python
w.repaint(family=("stone", "quartz"))        # 石材整体换成石英
w.repaint({"stone_bricks": "deepslate_tiles"})   # 只换一种
w.repaint(lambda b: "gold_block" if b.name.endswith("_bricks") else None)
```

内置家族（`mcbuild.palette.FAMILIES`）：`stone` `deepslate` `blackstone` `quartz`
`sandstone` `red_sandstone` `bricks` `prismarine` `copper` `concrete` `wool`
`terracotta` `oak` `spruce` `birch` `dark_oak`。

家族间映射**先按关键词找同名变体**（`stone_bricks` → `quartz_bricks`、
`smooth_stone` → `smooth_quartz`），找不到才按色阶索引比例对齐。映射时
**继承原 blockstate**，所以楼梯换材质后还是楼梯、朝向不丢，`_stairs`/`_slab`/
`_wall` 后缀也会跟着换。可 `undo`。

### 干跑预览 `w.preview(...)`

**先看后果，再决定要不要提交。** 世界在 preview 期间一行未动：

```python
pv = w.preview(w.clear, box((0, 64, 0), (63, 100, 63)))
print(pv.report())
#   preview clear((0,64,0)..(63,100,63))
#     将改动 12000 格：新增 0 · 移除 12000 · 替换 0
#     影响范围 (0,64,0)..(63,100,63)  尺寸 (64,37,64)
#     涉及组件实例：bay#0 bay#1 bay#2 …共 8 个

if pv.removed > 2000:
    pv.discard()          # 太大了，换个范围
else:
    pv.commit()           # 确认后原子提交
```

| 成员 | 说明 |
|---|---|
| `pv.changed` / `added` / `removed` / `replaced` | 分类统计 |
| `pv.box` | 影响范围 |
| `pv.empty` | 空操作（改了等于没改） |
| `pv.instances_hit()` | 哪些组件实例的范围与改动相交 |
| `pv.report()` | 格式化的完整报告 |
| `pv.commit()` / `pv.discard()` | 只能调用一次；都调用过会抛 `RuntimeError` |

`commit` 是**重放**那个操作（不是回灌 patch），所以 `place` 出来的组件实例会正常登记。
框架是确定性的，重放同一操作得到同一结果。

preview 内如果抛异常，世界和 undo 栈都会回滚干净。

---

## 5. Frame：局部坐标

```python
with w.frame(at=(10, 64, 20), yaw=90) as f:
    f.fill(box((-3, 0, -3), (3, 4, 3)), "bricks")
    f.set((0, 0, 3), "oak_door", facing="+v", half="lower")     # 门朝外
    f.set((0, 1, 3), "oak_door", facing="+v", half="upper")
    f.mark("front_door", (0, 0, 3))         # 锚点自动落世界坐标
```

- Frame 有 World 的全部写入原语（`fill` / `wall` / `pillar` / `roof_gable` / …）
- `f.frame(at=..., yaw=...)` 可嵌套，yaw 父子叠加
- `f.to_world(local) -> V` / `f.to_local(world) -> V`
- `f.yaw` 是叠加后的有效 yaw

**四面复用套路**（写一次立面，四个朝向各实例化一次）：

```python
from mcbuild import Frame
def ring_frames(w, half, y):
    for yaw, at in ((0, (0, y, half)), (90, (-half, y, 0)),
                    (180, (0, y, -half)), (270, (half, y, 0))):
        yield yaw, Frame(w, at, yaw)

for yaw, f in ring_frames(w, 7, 68):
    f.fill(box((-7, 0, 0), (7, 3, 0)), "white_concrete")
    f.pillar((-7, 0, 0), 4, "red_concrete")
    f.set((0, 1, 0), "glass_pane")
    f.fill(box((-8, 4, 1), (8, 4, 1)), "dark_oak_stairs", half="top", facing="+v")
```

---

## 6. 形状原语

### 基础

```python
w.line((0,64,0), (7,68,7), "stone_bricks")          # 3D Bresenham
w.wall(box((0,65,0),(7,68,7)), "cobblestone")        # 四面墙
w.wall(..., skip=("n",))                             # 去掉北面
w.floor(box((0,64,0),(7,64,7)), "oak_planks")        # 底面
w.ceiling(box((0,68,0),(7,68,7)), "spruce_planks")   # 顶面
w.pillar((0, 64, 0), 8, "oak_log")                   # 向上 8 格
w.hollow_box(box((0,64,0),(7,70,7)), "stone_bricks") # 只写壳
```

### 圆 / 球

```python
w.cylinder(center=(0,64,0), r=5, height=8, block="stone_bricks")
w.dome(center=(0,64,0), r=6, block="stone_bricks")            # 半球
w.sphere(center=(0,70,0), r=4, block="glass", hollow=True)
from mcbuild.ops import circle_xz, disc_xz
pts = circle_xz((0,64,0), 6)                          # 返回格子列表，可自行处理
```

### 楼梯 / 屋顶

```python
w.stairs_run((0,64,0), "north", 5, "oak_stairs")      # 每级前进 1 升高 1
w.roof_gable(box((0,69,0),(15,72,7)), "spruce_stairs", axis="x")
w.roof_pyramid(box((0,69,0),(6,73,6)), "oak_stairs")  # 攒尖
w.spiral_stairs((0,64,0), r=3, turns=2, block="oak_stairs")
w.arch(box((0,64,0),(4,68,1)), "stone_bricks", axis="z")
```

### 中式

```python
w.hip_roof(box((-6,88,-6),(6,92,6)), "prismarine_stairs", axis="x", inset=4)
#   四坡顶（庑殿顶）。inset = 屋脊两端相对檐口的缩进格数。
#   ★约束：RISE <= INSET 且 RISE <= 半跨，否则阶梯屋面之间会漏空
#     （楼梯方块一格只能抬高一格）。RISE = box 的高度差。

w.eave_ring(box((-7,73,-7),(7,73,7)), "prismarine_stairs", depth=1)
#   环绕挑檐：只写外扩的一圈，主体范围内的格子不动，facing 自动朝外

w.railing(box((-9,68,-9),(9,68,9)), "red_concrete",
          rail_block="dark_oak_fence", spacing=3, height=2)
#   望柱 + 地栿 + 寻杖。柱位以每条边的中点对称分布
```

### 区域变换

```python
w.mirror(box((0,64,0),(7,70,7)), axis="x")            # 含朝向翻转
w.rotate_area(box((0,64,0),(7,70,7)), yaw=90)
w.translate_area(box((0,64,0),(7,70,7)), delta=(0,0,8))
w.repeat(box((0,64,0),(5,70,5)), step=(6,0,0), n=7)   # 复制 7 份（不含原件）
w.stack(box((0,64,0),(7,67,7)), dy=4, n=3)            # 垂直堆 3 层
```

---

## 7. 轴网 grid

把"第 N 个开间"变成一等公民。**大建筑必须用。**

```python
w.grid("bays", origin=(0, 64, -24), axis="z", spacing=6, n=8)      # 一维
w.grid("piers", origin=(-12,64,-24), axes=[("x",6,5), ("z",6,9)])  # 二维柱网

w.grid_at("bays", 3)        # → V(0, 64, -6)        第 4 个格点
w.grid_cell("bays", 3)      # → Box(...)            第 4 格占的 6 格宽范围
w.grid_span("bays", 2, 5)   # → Box(...)            第 2 到第 5 格点
w.grid_cover("bays", 2, 3)  # → Box(...)            覆盖第 2..3 格全部宽度

g = w.grids["bays"]
g.ndim, g.count(), g.at(0), g.cell(0)
```

索引越界抛 `IndexError`，维数不匹配抛 `ValueError`。

---

## 8. 组件 component

写一次，多处实例化，**改模板全部生效**。

```python
def pier(t, h=8, mat="oak_log"):
    """子组件：一根柱子。"""
    t.pillar((0, 0, 0), h - 1, mat)

def bay(t, w=6, d=6, h=8, mat="stone_bricks", pier="oak_log"):
    """一个开间。t 是 World 或 Frame —— 坐标与朝向自动继承。"""
    t.fill(box((0, 0, 0), (w-1, 0, d-1)), mat)               # 地面
    for cx in (0, w-1):
        for cz in (0, d-1):
            t.place("pier", at=(cx, 1, cz), h=h, mat=pier)   # ← 组件嵌套
    t.fill(box((1, h-2, 0), (w-2, h-2, 0)), "glass_pane")    # 后墙窗

w.define("pier", pier)
w.define("bay", bay)                       # ← 必须在 stage 函数外
w.grid("bays", origin=(0, 64, 0), axis="z", spacing=6, n=8)
for i in range(8):
    w.place("bay", at=w.grid_at("bays", i))
```

### 实例对象 `Instance`

```python
inst = w.instance("bay", 3)
inst.name, inst.at, inst.yaw, inst.params
inst.box          # Box —— 展开后的实际范围（可用于 render.view / compare）
inst.cells        # Set[V] —— 它写入的格子
inst.linked       # False = 已 unlink
inst.overrides    # Dict[局部 V, Block]
inst.parent       # 父实例（顶层为 None）
inst.children     # List[Instance] 直接子实例
inst.depth        # 嵌套深度，顶层为 0
inst.to_world((0,0,0))     # 局部 -> 世界
inst.to_local(p)           # 世界 -> 局部
```

### 组件嵌套

`t.place(...)` 里的 `t` 可以是 **World 或 Frame**，两者都能放组件：

- `t` 是 `World`：`at` 是世界坐标
- `t` 是 `Frame`：`at` 是**该 frame 的局部坐标**，朝向也叠加 `frame.yaw`

父子关系会被记录下来。**父组件 `replay` 时，子孙实例级联重建**：

```python
w.replay("bay")      # 4 个 bay 重放，每个的 4 个 pier 一起重建（实例数不变，不膨胀）
w.replay("pier")     # 也可以只重放子组件
```

后代实例自己的局部覆盖会按 `(名字, 世界位置)` **继承到重建出的新实例上**——
所以「改父模板」和「单独调某个子实例」两件事可以叠加，互不覆盖。

> 若模板改动导致子组件位置变了（比如 `w` 参数变了），`(名字, 位置)` 匹配不上，
> 该子实例的覆盖会丢失。这是位置语义变化后的必然结果。

### 展开失败回滚

组件写到一半抛异常，本次写入的方块和创建的实例（含全部后代）会**自动回滚**，
世界和 `undo` 栈都回到展开之前：

```python
def broken(t):
    t.fill(box((0,0,0),(4,4,4)), "stone")
    t.place("pier", at=(0,0,0))
    raise RuntimeError("写错了")
w.place("broken", at=(0,0,0))   # 抛 RuntimeError，但世界是干净的
```

子组件失败时，父组件也会一起回滚。

### 三种"改一个"的方式

```python
# ① 改模板，全部实例生效（未 unlink 的）
def bay2(t, w=6, d=6, h=8, mat="stone_bricks", pier="dark_oak_log"):
    ...
w.define("bay", bay2)
w.replay("bay")                       # 显式重放，返回重放个数
w.replay()                            # 不传参 = 重放全部组件

# ② 只改某一个实例（局部覆盖，replay 后仍然保留）
w.patch(w.instance("bay", 3), (1, 5, 0), "gold_block")

# ③ 断开同步，让它变成独立体素（"除非特殊声明"）
w.unlink(w.instance("bay", 5))
```

> **`patch` 的坐标是实例内局部坐标，不是世界坐标。**
> 这样模板改动导致实例移动/变形后，覆盖依然跟着实例走。
>
> `unlink` 只切断"模板改动不再跟随"。若它的**父组件**被重放，它仍会随父的 patch
> 一起重建 —— 因为它的体素归属父的展开过程。

---

## 9. 比较器 compare

**大建筑里对称错误是最常见的低级错误，而它在 ASCII 里肉眼几乎看不出来。**

```python
diffs = w.compare.symmetry(box((-12,63,-12),(12,96,12)), axis="x")
print(w.compare.report(diffs, limit=8))
# 共 3 处不一致
#   mirror: (-1,68,7) = dark_oak_door[...] ≠ (1,68,7) = dark_oak_door[...,hinge=right]

w.compare.is_symmetric(bx, axis="x")     # 快捷 bool
w.compare.rotational(bx, yaw=90)         # 旋转对称（区域须 x/z 等长）
w.compare.regions(boxA, boxB, yaw=0)     # 两个同尺寸区域比对
w.compare.instances("bay", 0, 3)         # 8 个开间本应完全一致
```

`Diff` 字段：`.kind` `.a` `.b` `.got` `.want`

**规模**：耗时是 **O(已占方块数)**，与包围盒体积无关 —— 扫描范围可以放心给整栋建筑的
包围盒，不需要手动缩小。实测：

| 规模 | 包围盒体积 | 方块数 | `symmetry` |
|---|---|---|---|
| 滕王阁 | 22,100 | 4,902 | ~5 ms |
| 教堂 144×86×160 | 1,981,440 | 157,646 | 0.40 s |
| 塔楼 120²×160 | 2,304,000 | 175,490 | 0.37 s |

`rotational` / `regions` 同量级（0.4–0.6 s），`instances` 更快（只遍历一个实例的格子）。

**默认值已归一化**：Minecraft 的 blockstate 有默认值，所以 `oak_door[half=lower]`
与 `oak_door[half=lower,hinge=left]` 是同一个东西。比较时会先补全默认值再比，
所以一边显式写、一边缺省**不会**被判为不一致。
（导出与 `key()` 仍用原始 state —— 补全会让 palette 拖一长串默认属性。）

### 结构化 diff

`w.render.diff()` 画的是图；`w.compare` 给的是**能统计的数据**：

```python
w.checkpoint()                      # 设基线
...改动...
d = w.compare.since_checkpoint()
print(d.report(world=w))
#   diff since checkpoint：共 262 处（新增 0 · 移除 5 · 替换 257）
#     范围 (0,64,0)..(22,70,15)
#     按区域：nave 256 · tower 6
#     [cha] (0,64,0) stone_bricks -> deepslate_tiles
#     ...

d.by_kind()          # {'added': 0, 'removed': 5, 'changed': 257}
d.by_region(w)       # {'nave': 256, 'tower': 6, '(未分区)': 1}
d.box()              # 变化范围的包围盒
d.added / d.removed / d.changed      # 三份 Change 列表
```

大建筑里"**哪一块被动了**"比"哪几格被动了"有用得多，所以 `by_region` 是重点。

```python
w.compare.diff(old_world)                        # 旧版 -> 现在
w.compare.diff(old_world, mode="shape")          # 忽略朝向等属性
w.compare.duplicates([bx1, bx2, bx3], mode="shape")   # 找重复的建筑
```

`mode="shape"` 忽略的是**属性**（朝向、half…），不是材质 ——
换了材质的方块仍算不同。

---

## 10. 分步 stage

```python
def build_podium(w): ...
def build_nave(w): ...

w = World()
w.define("bay", bay)              # ← 模板在阶段外
w.stage("podium", build_podium)
w.stage("nave", build_nave)

w.stages                          # [Stage(podium, ...), Stage(nave, ...)]
w.stage_box("nave")               # → Box
w.rerun("nave")                   # 重跑该阶段及之后（旧实例自动清理）
w.revert_to("nave")               # 撤销该阶段及之后

with w.stage("roof"):             # 也可用 with 形式（但不可 rerun）
    w.hip_roof(...)
```

### 跨对话分步（推荐的大建筑做法）

```python
# 第 1 轮
w = World(); w.stage("podium", build_podium); w.save("church.json")
# 第 2 轮
w = World.load("church.json"); w.stage("nave", build_nave); w.save("church.json")
# 第 3 轮 —— 只在这一个阶段里工作，上下文不会越堆越长
```

> `stage` 的函数引用不会被 `save` 持久化。跨对话后要 `rerun` 需重新 `define` / 重新注册函数。

### 跨对话能保住什么

`w.save()` 除体素外还存**组件实例 / 命名区域 / 阶段**的元数据，所以第 2 轮
`load` 回来之后，组件同步与分区能力仍然可用：

```python
w = World.load("church.json")
len(w.instances), len(w.regions), len(w.stages)   # 都还在
w.region_of("nave").translate((40, 0, 0))         # ✅ 区域可继续操作
w.stage_box("nave")                               # ✅ 阶段范围可引用

w.define("bay", bay_v2)      # 模板要重新注册（函数本来就不能序列化）
w.replay("bay")              # ✅ 重放，且每个实例的局部覆盖逐条继承
```

| 存了什么 | 没存什么（下轮脚本里会重新注册） |
|---|---|
| 实例的 `name / at / yaw / params / overrides / 父子关系` | 模板函数 `_components` |
| 区域的 `name / cells` | 实例的 patch（重建时不需要） |
| 阶段的 `name / box` | 阶段的 fn（所以 `rerun` 不可用，`stage_box` 可用） |

两点注意：

- **`params` 里不能放函数之类的不可序列化值** —— 那条实例会被跳过（其余照常），
  避免一条坏数据毁掉整个存档
- 恢复出来的实例没有 patch，`replay` 直接按 `at/yaw/params` 重建，**不会**先撤销
  （位置由参数决定，重建即覆盖）

`meta=False` 可关掉这些元数据（只存体素，文件更小）。

> **`stage` 切的是时间。** 如果建筑里有多个**独立单元**（建筑群、空岛群、
> 以后想单独搬动的部件），还需要按**空间**切分 —— 见下一节。

---

## 10.5 命名区域 region

`stage` 管**时间**（构建顺序），`region` 管**空间**（命名分区）。

### 什么时候该分区：先问三个问题

| 问自己 | 是 → 分区 |
|---|---|
| 这栋建筑里有"可以单独拿出来"的部分吗？（一栋楼、一个岛、一座塔、一道桥） | |
| 以后会不会想单独搬动、复制、镜像、删除其中某一部分？ | |
| 需不需要按部分查 lint、看 diff、单独导出？ | |

**任一为"是"就分**。三个都"否"（单体建筑：一座教堂、一间小屋、一座桥）就**别分** ——
分区本身不产生价值，它只是让"单独操作某一块"变得可能。

具体到场景：

| 场景 | 分不分 | 怎么分 |
|---|---|---|
| 一座教堂 / 一间小屋 / 一座塔 | ✗ | 用 `stage` 分步就够了 |
| 空岛群、村落、建筑群 | ✓ | 每个岛/每栋楼一个 region |
| 岛上有楼阁、城里分区 | ✓ | **嵌套**：楼阁套在岛的 `with` 里 |
| 一座大楼里要单独搬动的部件（中庭 / 附楼 / 停机坪） | ✓ | 按部件名 region |
| 大建筑想按块查问题 | ✓ | 分区后 `lint(region=...)`、`diff.by_region(w)` 才有意义 |

### 和 stage 的分工（不冲突，可叠加）

```python
with w.stage("islands"):                 # 时间：这一轮做"群岛"
    with w.region("island_a"):           # 空间：这个岛
        build_island(w)
    with w.region("island_b"):
        build_island(w)
```

**判断口诀**：按"我要一次做完什么"切 → `stage`；按"我以后要单独动什么"切 → `region`。

### 用法

```python
with w.region("island_a") as isl:
    w.fill(box((0, 64, 0), (15, 64, 15)), "grass_block")
    with w.region("pav_1") as p1:          # ← 嵌套：楼阁是岛的子区域
        build_pavilion(w)
    with w.region("pav_2") as p2:
        build_pavilion(w)

p1.translate((40, 0, 0))            # 单独搬楼阁（连它自己铺的地板一起）
isl.translate((0, 0, 60))           # 搬岛 —— 两个楼阁跟着走
p1.mirror(axis="x")                 # 镜像（含朝向翻转）
c = p1.copy_to((0, 0, 40), name="pav_3")   # 复制一份，原区域保留
p1.export_schem("out/pav_1.schem")  # 单独导出（平移到原点，方便粘贴）
p1.export_tiled("out/pav_1_parts")  # 单独导出并按 48³ 分块
```

### 复制：`copy_to` 会连子区域一起复制

```python
island_b = isl.copy_to((40, 0, 0), name="island_b")
# 新岛不只是体素 —— island_b/pav_1、island_b/pav_2 也一起建好了
w.region_of("island_b/pav_1").translate((0, 0, 20))   # 仍然能独立操作
```

| 参数 | 说明 |
|---|---|
| `delta` | 位移 |
| `name` | 新区域名（默认 `原名_copy`） |
| `yaw` | 旋转复制（子区域绕**父的中心**转，不会错位） |
| `with_children` | 默认 `True` 连子区域一起复制并重建层级；`False` 只复制体素 |

子区域命名为 `新父名/原子名`（如 `island_b/pav_1`），一眼看出从属。
**原区域保留不动** —— 这是"再造一个"而不是"搬过去"，搬移用 `translate`。

> 空岛场景最常用的一招：造好一个岛 → 复制若干份 → 每份各自微调
> （改楼阁朝向、换个材质、加段围墙），比从零建快得多。

| 成员 | 说明 |
|---|---|
| `r.cells` | 我在这个区域里**写过**的格子（原始语义） |
| `r.owned()` | **独占**的格子 ← 变换与导出都用它 |
| `r.parent` / `r.children()` | 层级（嵌套时才有） |
| `r.box` | 区域范围 |
| `r.blocks()` / `r.histogram()` | 区域内实际的方块与统计 |
| `w.region_of(name)` / `w.region_at(pos)` | 按名取、按坐标反查 |
| `w.region_table()` | **一览表**（含层级、大小、作用格数） |
| `w.regions` | `{name: Region}` |

### 重叠归属：两条规则

区域可以重叠（塔立在岛上、楼阁地板与岛面同格），归属规则是：

| 规则 | 说明 |
|---|---|
| **后定义的拥有重叠部分** | 那格的内容确实是它写的。岛先铺地面、塔后立上去并自己铺了地基 → 地基归塔，搬走塔会连带搬走地基（原地留洞，这是拆除的正常结果） |
| **祖先 / 后代互相豁免** | 岛上的楼阁能独立搬移，哪怕地板和岛面同格；搬岛时楼阁也跟着走 |

实测：岛 64 格 + 塔 169 格、重叠 25 → 岛独占 39、塔独占 169（全部）；
搬走塔后地基跟着走。而嵌套的楼阁则两边都能独立操作。

`w.region_table()` 是建筑群开工前该先看一眼的东西：

```python
for r in w.region_table():
    print("  " * r["depth"] + f"{r['name']} parent={r['parent']} "
          f"cells={r['cells']} owned={r['owned']} op={r['op']}")
# island   parent=None  cells=381 owned=381 op=381
#   pav_1  parent=island cells=150 owned=150 op=150
#   pav_2  parent=island cells=125 owned=125 op=125
```

`op` 是变换/导出**实际作用**的格数（自己的独占 + 各后代的独占）。

> 同一个名字可以多次 `with`，内容会累积（适合分散在多处、逐步补完的建筑）。
> 区域内涉及组件实例时，变换会自动 `unlink` 它们 —— 位置变了之后 patch 记录不再有效。
> `region_at(pos)` 默认忽略空位置（问"这一点属于谁"通常关心有内容的地方）；
> 查历史归属传 `solid_only=False`。

---

## 11. 查询 query

```python
w.query.count()                          # 总格数
w.query.count("door")                    # 门的数量
w.query.count(lambda b: b.is_air is False and b.get("half") == "lower")
w.query.where("torch")                   # [V, ...]
w.query.nearest("front_door", "torch")   # 离锚点最近的火把（origin 可传名字）
w.query.nearest((0,64,0), "oak_log")
w.query.empty((3,65,3))                  # True / False
w.query.neighbors((0,64,0))              # {'north': Block, 'up': Block, ...}
w.query.raycast((0, 70, 0), (0,-1,0), 32)   # → (V, Block, dist) | None
w.query.histogram(5)                     # [('minecraft:stone', 312), ...]
w.query.support_report()                 # 会长距离悬空的方块清单
```

## 12. 渲染 render

```python
print(w.render.slice(64))                       # 水平切片
print(w.render.slice(64, bx=box((0,64,0),(15,64,15))))
print(w.render.slice(69, overlay="facing"))     # 朝向层 ^ > v <
print(w.render.section(axis="z", at=0))         # 正立面剖面
print(w.render.section(axis="x", at=5, bx=bx))
print(w.render.diff())                          # 只画本轮改动（+ - ~）
print(w.render.summary())
print(w.render.iso(step=2))                     # ★ 必须带 step
print(w.render.budget(1200).slice(64))          # 限字符预算
```

### 视口（大建筑必用）

```python
# 三视图：水平 + X 剖面 + Z 剖面，center 接受 V / 锚点名 / Box
print(w.render.view(center=(0,70,0), size=(16,12,16)))
print(w.render.view(center=w.stage_box("nave")))              # 看某一阶段
print(w.render.view(center=w.instance("bay", 3).box))         # 看某个实例
print(w.render.view(center=w.region_of("island_a").box))      # 看某个分区 ← 建筑群时最常用

# 全景 + 视口框（行首 '>' 标出视口所在行）
print(w.render.overview(y=67, step=4, center=(0,70,0), size=(12,8,12)))
```

**输出格式**：1 格 1 字符 + 每 5 格刻度尺 + 指北针（`N↑ = z 减小`）+ 自动图例。
超预算自动降采样并标 `scale=1:N`。

### 12.1 图像渲染（`w.image`，多模态预览）

ASCII 验"几何对不对"，图像验**"好不好看"**——配色协调度、屋面层次是否被压死、
云海像不像云，这些只有看图才发现得了。

```python
w.image.save("out/hero.png")                          # 整场
w.image.save("out/pav.png", bx=w.stage_box("pavilion"))        # 只渲主阁
w.image.save("out/pav.png", bx=w.stage_box("pavilion"), tw=16, bh=16)   # 放大特写
w.image.save("out/hall.png", bx="hall")               # bx 也接受 mark_box 的区域名
w.image.preview("out/hero.png")                       # 存完尝试调用系统看图器
```

| 参数 | 默认 | 含义 |
|---|---|---|
| `out` | — | 输出 PNG 路径（目录不存在会自动建） |
| `bx` | `None` | 渲染范围（世界坐标闭区间）· `None`=整场 · 接受 `Box` / 六元组 / `mark_box` 名字 |
| `tw` / `bh` | `8` / `8` | 每格的水平像素宽 / 高度像素。**局部特写就调大** |
| `bg` / `horizon` | 天空蓝 | 背景渐变（上 → 地平线） |
| `sky_gain` | `0.10` | 高度天光：高处略亮 |

**取景要点**

- `bx` 是**范围过滤**，不是剖切——跨界方块要么整块画、要么整块不画。取景留一格余量，
  否则斜面屋顶边缘会出现锯齿状断口。
- 相机固定在 `+x/+y/+z` 俯视，可见面固定为 顶面 / `+z`(南) / `+x`(东)。要看另一侧就
  用 `rotate_area` 转场景，或换 `bx` 取景。
- **`bx` 用负坐标没问题**（走的是 Python 参数，不是 shell）。命令行要 `--box=-32,...` 写法。

**调色板**：默认表覆盖常见材质（石 / 木 / 海晶 / 玻璃 / 植被 / 光源…，约 90 个）。
写自己的建筑时补齐缺的颜色，**未登记的方块走 `DEFAULT_COLOR` 灰褐，不会报错**：

```python
w.image.color("warped_planks", (43, 122, 122))          # 单个（链式）
w.image.colors({                                        # 批量
    "crimson_planks": (143, 58, 74),
    "blackstone": (42, 36, 40),
})
```

> **调色板随世界走，不是全局**。`w.image.color(...)` 只影响这一个 `World`；
> `DEFAULT_PALETTE` 本身不会被改写（测试里会断言这点）。

**性能**：5 万方块整场约 1.3 s；局部特写 0.1 s 级。图像内部有面剔除 + 画家算法，
实心体内部不产生可见面。

**与 ASCII 的分工**：`slice`/`section` 带坐标刻度，是**定位**工具（改哪一格）；
`w.image` 不带坐标，是**验收**工具（整体观感）。两者互补，不要互相替代。

---

## 13. 校验 lint

```python
issues = w.lint()
for i in issues:
    print(i.code, i.level, i.pos, i.block, i.msg)
```

| 码 | 级别 | 含义 |
|---|---|---|
| `E1` | Error | 非法 blockstate —— **在写入时就抛异常**，不会走到 lint |
| `W1` | Warn | 重力方块下方悬空 / 装饰方块无支撑 / 悬挂类上方无支撑 |
| `W2` | Warn | 双格方块（门 / 床）缺另一半 |
| `W3` | Warn | 门外被实体方块堵住 |
| `W4` | Info | 存在与外部不连通的封闭空间 |
| `W5` | Warn | 连接属性（墙/栅栏/玻璃板）与实际邻居不符 |
| `W6` | Info | 封闭空间内无光源 |

> `W4`/`W6` 在"门窗都关着"的建筑上必然出现，所以降为 `Info` ——
> 它们不该和真正的悬空/堵塞混在一起报警。

### 分级：排序、按区域分解、过滤

`lint()` 的结果按**严重度 → 码 → 坐标**排序（严重的不埋在末尾）。
大建筑上告警会有成千条，用两个办法收窄：

```python
# ① 汇总：按码统计并分解到区域 —— 一眼看出"哪个建筑有问题"
w.lint_summary()
# {'W1': {'count': 1240, 'level': 'Warn', 'msg': '下方悬空，会被破坏掉落',
#         'regions': {'nave': 900, 'tower': 340}, 'sample': (0,64,0)},
#  'W4': {'count': 3, 'level': 'Info', ...}}
#   按 count 降序返回

# ② 过滤
w.lint(level="warn")          # 只看建议修的
w.lint(region="nave")         # 只看某个命名区域（也接受 Region 对象）
w.lint(codes=("W1", "W2"))    # 只看这些码
w.lint(region="tower", level="warn")   # 可组合
```

`w.report()` 的 LINT 段也会带上区域分布：

```
W1(Warn) x4  下方悬空，会被破坏掉落   区域: nave 4
     (0,65,16)  torch
     ...
```

> 想按"区域"收窄，前提是构建时用了 `with w.region(...)`（见 §10.5）。
> 没分区的改动会归到 `(未分区)`。

---

## 14. 方块与别名

### 直接写英文 id，写错会被告知

**不需要**被下面那 76 条别名限制 —— 你的世界知识里有的是方块名，直接写就行。
注册表覆盖 1.21.x 的 **1196 个方块**，写完自查：

```python
from mcbuild import registry

registry.exists("waxed_oxidized_cut_copper_stairs")   # True
registry.check("oak_stairz")
#   "未知方块 'oak_stairz'；是否想写: oak_stairs / pale_oak_stairs / dark_oak_stairs ..."

registry.search("banner")        # 32 个旗帜类方块名
registry.search("_stairs")       # 所有楼梯
registry.states("oak_stairs")    # {'facing': [...], 'half': [...], 'shape': [...], ...}
registry.defaults("oak_stairs")  # {'facing': 'north', 'half': 'bottom', ...}
```

**整个建筑一起查**：

```python
for pos, bid, msg in w.unknown_blocks():
    print(pos, msg)
# (1,1,1) 未知方块 'minecraft:oak_stairz'；是否想写: oak_stairs / pale_oak_stairs ...
```

`unknown_blocks()` 每种方块只报一次（不会刷屏），且**跳过非 `minecraft:` 命名空间**
—— mod 方块（`create:cogwheel`）不会被当成错误。

> 逐格写错名不会当场抛异常（那样太吵，而且 mod 方块无法预判），
> 所以这是事后自查的入口。别把它当成每步必跑 —— 通常写完一段再查一次。

### 属性校验也来自真实数据

方块**属性**的合法取值同样从这份数据来（1196 个方块的真实定义），
不再是手写的十几个"族"兜底：

```python
w.set(pos, "lantern", hanging="true")        # ✅ 手写表里 lantern 没属性，现在能校验
w.set(pos, "redstone_wire", power="13")      # ✅ 0..15
w.set(pos, "redstone_wire", power="20")      # ✗ BlockStateError（可用 0..15）
w.set(pos, "oak_stairs", shape="inner_left") # ✅
w.set(pos, "oak_stairs", shape="banana")     # ✗ BlockStateError
```

`registry` 里没有的方块（mod、更晚的版本）自动回退到内置的族规则，不会误拦。

> 顺带：**默认值不再造成比较误报**。`oak_door[half=lower]` 和
> `oak_door[half=lower,hinge=left]` 语义相同，`compare` 会先补全默认值再比 ——
> 所以属性**不用**刻意写全了。

### 别名：只有英文简写

```python
w.set(pos, "planks")        # → minecraft:oak_planks
w.set(pos, "stairs")        # → minecraft:oak_stairs
```

完整表：`planks` `log` `stairs` `slab` `wall` `fence` `door` `wool` `concrete`。

其余**一律直接写英文 id**（`prismarine_stairs` / `end_stone_bricks` / `white_concrete` …）。
带命名空间的（`minecraft:stone` / `create:cogwheel`）原样保留。

> 直接用真名 —— 写错了 `registry.check()` 会告诉你。

### 方块族判定（决定它接受哪些属性）

| 族 | 判定规则 | 可用属性 |
|---|---|---|
| `stairs` | `*_stairs` | `facing` `half` `shape` |
| `slab` | `*_slab` | `type`（写 `half="top"` 也行） |
| `door` | `*_door` | `facing` `half` `hinge` `open` `powered` |
| `trapdoor` | `*_trapdoor` | `facing` `half` `open` `powered` |
| `gate` | `*_fence_gate` | `facing` `in_wall` `open` |
| `wall` | `*_wall` | `north/east/south/west/up`（自动算） |
| `fence` | `*_fence` | 四向 bool（自动算） |
| `pane` | `*_pane` | 四向 bool（自动算） |
| `torch` | 名字含 `torch` | `facing` `lit` |
| `ladder` | `ladder` | `facing` |
| `bed` | `*_bed` | `facing` `part` `occupied` |
| `sign` | `*_sign` | `rotation`（0..15） |
| `axis` | `*_log` `*_wood` `*_stem` `*_hyphae` 等 | `axis` |
| `solid` | 其余 | 无属性 |

**写错属性和取值会抛 `BlockStateError`**，例如：

```python
w.set((0,64,0), "oak_stairs", facing="northeast")
# BlockStateError: facing 取值非法: 'northeast'（可用 north/south/east/west/up/down）
w.set((0,64,0), "stone", facing="north")
# BlockStateError: minecraft:stone(solid) 不支持属性 'facing'，可用: []
w.set((0,64,0), "oak_door", half="middle")
# BlockStateError: minecraft:oak_door: half='middle' 非法，可用: ['upper', 'lower']
w.set((0,64,0), "oak_log", axis="w")
# BlockStateError: axis 取值非法: 'w'（可用 ('x', 'y', 'z')）
```

两个例外：

- **`waterlogged`** 对任何方块都接受，不校验（`oak_stairs[waterlogged=true]` 能写进去）
- **连接属性**（墙/栅栏/玻璃板的 `north/east/...`）不要自己写，导出时自动算；
  也读不到 —— 它只存在于导出产物里，`w.get()` 拿到的仍是没连接信息的原始方块

---

## 15. 导入导出

```python
w.export_schem("out/a.schem")            # Sponge v3，WorldEdit / Litematica 通用
w.export_nbt("out/a.nbt")                # 结构方块格式（单块 ≤48³）
w.export_json("out/a.json")              # 可回放，含锚点、方块实体、实体
w2 = World.load("out/a.json")

w3 = World.from_schem("out/a.schem")     # 从 .schem 新建，还原到导出时的位置
w3.import_schem("tower.schem", at=(10, 64, 10))   # 当零件摆到指定位置
```

**往返保真**：`.schem` 的 `Offset` 记的是导出时的世界原点，所以"导出再导入"
能回到原来的位置（非原点建筑也一样）。方块实体与实体一并还原。
给了 `at=` 就忽略 `Offset`，落到指定坐标 —— 这是把外部零件当积木用的方式。

导出时自动计算墙 / 栅栏 / 玻璃板的连接属性 —— **在副本上算，不会污染原世界**。
因此 `w.get(pos)` 读到的仍是没有连接信息的原始方块；也正因为如此，
导入回来的连接类方块会带上这些属性（往返时这部分 state 会多出来，属预期）。

### 分块导出 `export_tiled`

结构方块单块上限 48³，教堂尺度必须切开：

```python
parts = w.export_tiled("out/cathedral", chunk=48, prefix="cath")
for it in parts:
    print(it["file"], it["box"], it["blocks"])
# cath_0_0_0.nbt (-20,57,-8)..(20,104,39) 21170
# cath_0_0_1.nbt (-23,61,40)..(23,104,87) 24315
# ...
```

| 返回字段 | 含义 |
|---|---|
| `file` | 文件名（`prefix_ix_iy_iz.nbt`） |
| `box` | 该块覆盖的**世界坐标**范围 |
| `blocks` | 该块方块数 |

各块的 `box` 并集精确等于原包围盒，方块总数不变（实测 7 块 63513 = 63513）。
每块导出文件是紧凑的 0-based，按 `box.lo` 定位摆回即可还原。
`ext="schem"` 可改成输出 `.schem`。

### 多 agent / 多进程协作

框架的协作模型是**空间分工 + 文件合并**，不是共享同一个 `World`。

**分工方**：各建各的，导出时带上区域

```python
w = World()
with w.region("island_a") as isl:
    build_island(w)
    with w.region("pav_1"):
        build_pavilion(w)
isl.export_schem("out/island_a.schem")   # 区域结构随文件走
print(w.render.overview(step=2))         # 自检
print(w.lint(region="island_a"))         # 自检
```

**汇合方**：按坐标拼起来

```python
w = World()
w.import_schem("out/island_a.schem", at=(0, 64, 0))
w.import_schem("out/island_b.schem", at=(60, 64, 0))
w.region_table()
# island_a         parent=None       op=148
# island_b         parent=None       op=148
#   island_a/pav_1  parent=island_a  op=64
#   island_b/pav_1  parent=island_b  op=64
```

**区域随文件走**：`export_schem` 把命名分区写进 `.schem` 的自定义字段，
导入时自动重建（父子关系一起）。合并之后仍然能按区域操作 ——
否则拿到手的只是一堆体素，搬不动、查不了、分不开。

子区域重名时自动带上父名前缀（`island_b/pav_1`），不是干巴巴的 `pav_1@2`。

**外部文件**（WorldEdit / Litematica / 网上下载的 `.schem`）没有区域信息，
导入时用**文件名**建一个区域把整块圈进去；可用 `name=` / `prefix=` 覆盖：

```python
w.import_schem("castle_tower.schem", at=(10, 64, 10), prefix="src/")
# → 区域 src/castle_tower，可以单独搬移 / 导出
```

**冲突检测**：`w.merge(other, on_conflict=...)`

| 模式 | 冲突位置（两边都有方块且不同）怎么办 |
|---|---|
| `"overwrite"`（默认） | 用对方的 |
| `"skip"` | 保留自己的 |
| `"report"` | **不写入**，只列出来，先看清楚再决定 |

```python
rep = w.merge(part_b, on_conflict="report")
if rep["conflict_count"]:
    for pos, mine, theirs in rep["conflicts"][:10]:
        print(pos, mine.short(), "->", theirs.short())
```

返回 `{added, overwritten, skipped, conflict_count, conflicts, regions, entities}`。
"冲突"用**归一化比较** —— 一边写 `hinge` 一边缺省不算冲突。

> 两个 agent 同时写同一个 `World` 不是支持的用法（没有并发原语）。
> 正确做法是各建各的、文件交换、由一方合并。

---

## 16. 完整示例：一个带开间的中殿

```python
from mcbuild import World, box, V

H, SPAN, BAYS = 12, 8, 6

def bay(t, span=SPAN, h=H, mat="stone_bricks", pier="red_concrete"):
    """一个开间：四角束柱 + 三面墙 + 尖券窗洞。"""
    half = span // 2
    t.fill(box((-half, 0, -half), (half, 0, half)), "stone_bricks")     # 地面
    for sx in (-half, half):
        for sz in (-half, half):
            t.pillar((sx, 1, sz), h - 1, pier)                          # 束柱
    t.wall(box((-half, 1, -half), (half, h - 1, half)), mat, skip=("s",))
    t.set((0, 2, half), "glass_pane")                                   # 采光窗
    t.set((0, 3, half), "glass_pane")

def podium(w):
    w.fill(box((-SPAN, 63, -SPAN), (SPAN, 63, SPAN + SPAN * BAYS)), "stone_bricks")

def nave(w):
    w.grid("bays", origin=(0, 64, 0), axis="z", spacing=SPAN, n=BAYS)
    for i in range(BAYS):
        w.place("bay", at=w.grid_at("bays", i))

w = World(seed=1)
w.define("bay", bay)                       # ★ 模板在阶段外
w.stage("podium", podium)
w.stage("nave", nave)

print(w.render.slice(65))                  # 检查平面
print(w.compare.instances("bay", 0, 3))    # 开间应当一致

# 改模板 -> 全部开间生效
def bay2(t, span=SPAN, h=H, mat="stone_bricks", pier="dark_oak_log"):
    ...
w.define("bay", bay2)
w.replay("bay")

# 只改第 4 个开间
w.patch(w.instance("bay", 3), (0, 4, 0), "glowstone")

print(w.render.view(center=w.instance("bay", 3).box, size=(16, 16, 16)))
print(w.report("ok: 中殿完成"))
w.export_schem("out/nave.schem")
```

---

## 17. 报错速查

| 异常 | 触发场景 | 怎么修 |
|---|---|---|
| `BlockStateError` | 属性名或取值不合法 | 查 §14 的族属性表 |
| `KeyError: 未定义的组件` | `place` 前没 `define` | 先 `w.define(name, fn)` |
| `KeyError: 未定义的轴网` | `grid_at` 用了没定义的轴网名 | 先 `w.grid(...)` |
| `KeyError: 未定义的点锚点` | `anchor` 名字打错 | 用 `w.marks.points` 看现有锚点 |
| `IndexError: 索引越界` | 轴网索引超出 `0..n-1` | 检查 `g.count()` |
| `ValueError: 轴网只支持 1 维或 2 维` | `axes` 给了 3 个轴 | 最多 2 维 |
| `ValueError: rotational 要求区域在 x/z 上等长` | 旋转对称用了长方形区域 | 换成正方形 |
| `ValueError: 两区域尺寸不同` | `regions` 比了两个尺寸不一的区域 | 对齐尺寸 |
| `ValueError: 阶段 ... 没有可重跑的函数` | 用 `with w.stage(...)` 建的阶段去 `rerun` | 改用 `w.stage(name, fn)` |
| `ValueError: set() 需要 block 或 blockstate 参数` | `set(pos)` 少了方块 | 补上 |
| `ValueError: 空世界，无法导出` | 没写任何方块就导出 | 先建东西 |
| `ValueError: 空世界，无法渲染` | 空世界调 `w.image.save()` | 先建东西，或给非空 `bx` |
| `ValueError: 区域内没有可见方块` | `w.image` 的 `bx` 里全是空气 | 检查 `bx` 范围 / 用带坐标的 `slice` 先定位 |
| `ValueError: 未定义的区域锚点` | `w.image` 的 `bx` 传了不存在的 `mark_box` 名 | 用 `w.marks.boxes` 看现有区域名 |

---

## 18. 推荐工作流

**小建筑（< 1 万方块）**

```
define 需要的组件 → stage 建 → slice/section 检查 → compare 对称校验 → 导出
```

**大建筑（> 5 万方块）**

```
① 用 grid 定轴网，把建筑拆成命名阶段（台基 / 中殿 / 侧廊 / 塔楼 / 屋顶）
② 一轮只做一个阶段：load → stage → view 检查该阶段 → save
③ 每个阶段内部用组件复用重复单元（开间 / 柱列 / 扶壁）
④ 每完成一层做一次 compare.symmetry，别等全建完再查
⑤ 舞台检查用 render.view(center=w.stage_box("阶段名"))，不要渲染全世界
⑥ 最后 revision：改模板 replay / 局部 patch / unlink 转义
```

**建筑群 / 空岛群（多个独立单元）** ← 这种形态**必须分区**，否则后期搬不动

```
① 每个岛 / 每栋楼开一个 region；从属关系用嵌套表达
   with w.region("island_a") as a:
       build_island(w)
       with w.region("pav_1") as p:     # 岛上的楼阁
           build_pavilion(w)
② w.region_table() 确认层级与大小（op 是各区域实际作用的格数）
③ 位置不合适就按区域搬：a.translate(...) —— 不用重跑脚本
④ 缺一个就复制一个：p.copy_to((0, 0, 40), name="pav_2")   # 连子区域一起复制
⑤ 出了问题按区域收窄：w.lint(region="island_a")、d.by_region(w)、a.export_schem(...)
⑥ 交付时可以每栋楼一个文件：for r in w.region_table(): w.region_of(r["name"]).export_schem(...)
```

> 建筑群的常见失误是**一开始不分，建完才想搬** —— 那时候只能整片挪，
> 挪完还得手工修接缝。开第一个岛的时候就该开 region。

**每轮反馈只看三样**：`w.report()` 的四段、`w.render.view(...)` 的局部、
`w.compare` 的差异列表。**不要**输出整个世界。

**视觉检查**（多模态环境）：`w.render` 全绿只说明几何成立，不说明好看。
收尾时渲一张 `w.image.save("out/final.png")` 自己看，重点查三件事：

1. **视线是否被压死**——远景或配属建筑有没有被主体的屋檐完全遮住（坐标上不冲突，
   投影到图上才发现得了）；
2. **云 / 植被 / 水面这类"软"材质读起来对不对**——形状是否碎成噪点、颜色在背景上
   是否还立得住（白背景 + 白云 = 看上去是雪原）；
3. **重色是否堆在一处**——屋面 / 木构 / 台基的明度层次有没有分开。

发现问题就回去改脚本重渲，**不要**靠 ASCII 猜。
