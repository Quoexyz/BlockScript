# mcbuild 模型 API 手册

> **目标读者：LLM。代码量大，非必要不读用不上的源码，这份文档就是全部接口。**
> 版本 0.2.0 · 2026-09-10 · 92 个方法 / 16 个模块 / 零第三方依赖

---

## 1. 十条铁律

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
| 8 | **blockstate 属性要么全写、要么全不写** | 一边显式 `hinge="left"` 一边缺省，`compare` 会误报不一致 |
| 9 | **写完就渲染检查**（`slice`/`view`），不要盲写一大段 | 反馈闭环是这个框架的全部价值 |
| 10 | **非法 blockstate 会抛异常**，不会静默兜底 | 这是故意的，早暴露早修 |

---

## 2. 全部方法速查表

### 2.1 World（`world.py`）

| 方法 | 签名 | 说明 |
|---|---|---|
| `set` | `set(pos, block, **state) -> Block` | 写一个方块 |
| `get` | `get(pos) -> Block` | 读一个方块（空气返回 `AIR`） |
| `fill` | `fill(box, block, **state) -> int` | 填满闭区间盒，返回格数 |
| `clear` | `clear(box) -> int` | 清空区域 |
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
| `lint` | `lint() -> List[Issue]` | 物理校验 |
| `report` | `report(exec_line="", render_box=None) -> str` | 四段式反馈文本 |
| `save` / `load` | `save(path)` / `World.load(path)` | JSON 存档 / 读档 |

属性：`w.query` · `w.render` · `w.compare` · `w.marks` · `w.cells` · `w.instances` · `w.stages` · `w.grids`

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
| `instances` | `instances(name, i=0, j=1) -> List[Diff]` | 两实例局部布局比对 |
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

### 2.9 方块（`block.py`）

`make(block, yaw=0, **state) -> Block` · `classify(id) -> 族名` ·
`rotate_block(b, yaw)` · `mirror_block(b, axis)` · `is_solid(b) -> bool`

模块级常量：`AIR` · `STAIRS_UPHILL`（楼梯 facing 语义，改它可全局翻转）

### 2.10 导入导出（`io.py`）

`export_schem(w, path, version=3)` · `export_nbt(w, path)` · `export_json(w, path)` ·
`import_json(path, world=None)`
（`import_schem` 未实现）

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

**已知限制**：blockstate 默认值未归一化 —— 一边显式写 `hinge="left"`、一边缺省，
会被判为不一致（语义其实相同）。规避：属性要么全写、要么全不写。

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
print(w.render.view(center=w.stage_box("nave")))
print(w.render.view(center=w.instance("bay", 3).box))

# 全景 + 视口框（行首 '>' 标出视口所在行）
print(w.render.overview(y=67, step=4, center=(0,70,0), size=(12,8,12)))
```

**输出格式**：1 格 1 字符 + 每 5 格刻度尺 + 指北针（`N↑ = z 减小`）+ 自动图例。
超预算自动降采样并标 `scale=1:N`。

---

## 13. 校验 lint

```python
issues = w.lint()
for i in issues:
    print(i.code, i.pos, i.block, i.msg)
```

| 码 | 级别 | 含义 |
|---|---|---|
| `E1` | Error | 非法 blockstate —— **在写入时就抛异常**，不会走到 lint |
| `W1` | Warn | 重力方块下方悬空 / 装饰方块无支撑 / 悬挂类上方无支撑 |
| `W2` | Warn | 双格方块（门 / 床）缺另一半 |
| `W3` | Warn | 门外被实体方块堵住 |
| `W4` | Warn | 存在与外部不连通的封闭空间 |
| `W5` | Warn | 连接属性（墙/栅栏/玻璃板）与实际邻居不符 |
| `W6` | Warn | 封闭空间内无光源 |

> W4/W6 在"门窗都关着"的建筑上必然出现，属正常告警，不必强行消除。

---

## 14. 方块与别名

### 中文别名（76 个，直接写中文即可）

| | | | |
|---|---|---|---|
| 石头 → `stone` | 圆石 → `cobblestone` | 石砖 → `stone_bricks` | 苔石砖 → `mossy_stone_bricks` |
| 裂纹石砖 → `cracked_stone_bricks` | 花岗岩 → `granite` | 闪长岩 → `diorite` | 安山岩 → `andesite` |
| 砖块 → `bricks` | 砂岩 → `sandstone` | 红砂岩 → `red_sandstone` | 玻璃 → `glass` |
| 玻璃板 → `glass_pane` | 黑曜石 → `obsidian` | 泥土 → `dirt` | 草方块 → `grass_block` |
| 沙子 → `sand` | 砾石 → `gravel` | 雪块 → `snow_block` | 冰 → `ice` |
| 地狱岩 → `netherrack` | 地狱砖 → `nether_bricks` | 石英块 → `quartz_block` | 末地石 → `end_stone` |
| 深板岩 → `deepslate` | 深板岩砖 → `deepslate_bricks` | 黑石 → `blackstone` | 磨制黑石 → `polished_blackstone` |
| 羊毛 → `white_wool` | 混凝土 → `white_concrete` | 陶瓦 → `white_terracotta` | 橡木木板 → `oak_planks` |
| 云杉木板 → `spruce_planks` | 白桦木板 → `birch_planks` | 丛林木板 → `jungle_planks` | 金合欢木板 → `acacia_planks` |
| 深色橡木木板 → `dark_oak_planks` | 橡木原木 → `oak_log` | 云杉原木 → `spruce_log` | 白桦原木 → `birch_log` |
| 橡木木材 → `oak_wood` | 云杉木材 → `spruce_wood` | 橡木楼梯 → `oak_stairs` | 云杉楼梯 → `spruce_stairs` |
| 石砖楼梯 → `stone_bricks_stairs` | 石楼梯 → `stone_stairs` | 圆石楼梯 → `cobblestone_stairs` | 橡木半砖 → `oak_slab` |
| 石砖半砖 → `stone_bricks_slab` | 圆石半砖 → `cobblestone_slab` | 石砖墙 → `stone_bricks_wall` | 圆石墙 → `cobblestone_wall` |
| 橡木栅栏 → `oak_fence` | 橡木门 → `oak_door` | 云杉门 → `spruce_door` | 火把 → `torch` |
| 墙上火把 → `wall_torch` | 梯子 → `ladder` | 灯笼 → `lantern` | 灵魂灯笼 → `soul_lantern` |
| 萤石 → `glowstone` | 书架 → `bookshelf` | 工作台 → `crafting_table` | 熔炉 → `furnace` |
| 箱子 → `chest` | 床 → `red_bed` | 告示牌 → `oak_sign` | |

英文简写：`planks` `log` `stairs` `slab` `wall` `fence` `door` `wool` `concrete`

其他方块直接写英文 id（`prismarine_stairs` / `end_stone_bricks` / `white_concrete` …），
未知方块按实心处理、不报错。

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
w.export_nbt("out/a.nbt")                # 结构方块格式（≤48³）
w.export_json("out/a.json")              # 可回放，含锚点
w2 = World.load("out/a.json")
```

导出时自动计算墙 / 栅栏 / 玻璃板的连接属性 —— **在副本上算，不会污染原世界**。
因此 `w.get(pos)` 读到的仍是没有连接信息的原始方块，连接属性只存在于导出产物里。

> 结构方块 `.nbt` 上限 48×48×48；更大的建筑要分块导出（`export_tiled` 尚未实现，
> 目前可手动分区域多次导出）。

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

**每轮反馈只看三样**：`w.report()` 的四段、`w.render.view(...)` 的局部、
`w.compare` 的差异列表。**不要**输出整个世界。
