"""形状与材质分离。

`Shape` 回答空间问题：某个坐标属不属于这个体积、表面法线朝哪、
在形状里的归一化参数 ``t`` 是多少。
`Brush` 回答材质问题：这个坐标该写什么方块。

``w.paint(shape, brush)`` 把两者组合起来 —— 于是**同一个形状换一个 brush
就换一种效果**，同一个 brush 换一个形状就换一处位置。

    # 按高度风化：墙脚长苔、中段正常、上部干净
    w.paint(Shape.box(box((0, 64, 0), (15, 84, 15))),
            Brush.by_height([(0.0, 0.22, "mossy_stone_bricks"),
                             (0.22, 0.65, "stone_bricks"),
                             (0.65, 1.0, "chiseled_stone_bricks")]))

    # 组合形状 + 按法线换材质
    s = Shape.union(Shape.sphere((0, 80, 0), 10), Shape.box(box((-8, 64, -8), (8, 80, 8))))
    w.paint(Shape.subtract(s, Shape.sphere((0, 80, 0), 6)),
            Brush.by_normal({"up": "smooth_stone", "side": "stone_bricks"}))

为什么值得：`fill(box, block)` 是"形状 = 长方体、材质 = 常数"的特例。
真实感的分界线往往在材质随**位置**变化——墙脚比檐口脏、顶面比侧面亮——
纯随机混合（``w.material``）做不到这一点。
"""

from __future__ import annotations

import math
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from .block import AIR, Block, make
from .vec import V, Box, box, rot_y

Pred = Callable[[V], bool]
NormalFn = Callable[[V], V]
TFn = Callable[[V], float]

_DIRS = ("up", "down", "north", "south", "east", "west")


# ---------------------------------------------------------------- 噪声
# 位置哈希驱动的 3D value noise。刻意不用 `random`：
# 确定性是硬约束（同一份脚本必须逐格可复现），所以噪声也必须由坐标唯一决定。

def _h01(seed: int, x: int, y: int, z: int) -> float:
    from .world import _pos_hash
    return _pos_hash(seed, x, y, z) / 0xFFFFFFFF


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _smooth(t: float) -> float:
    return t * t * (3.0 - 2.0 * t)


def noise3(seed: int, x: float, y: float, z: float) -> float:
    """3D value noise，返回 -1..1。格点哈希 + 三线性插值，确定性。"""
    xi, yi, zi = math.floor(x), math.floor(y), math.floor(z)
    xf, yf, zf = x - xi, y - yi, z - zi
    u, v, w = _smooth(xf), _smooth(yf), _smooth(zf)

    def c(dx, dy, dz):
        return _h01(seed, xi + dx, yi + dy, zi + dz) * 2.0 - 1.0

    x00 = _lerp(c(0, 0, 0), c(1, 0, 0), u)
    x10 = _lerp(c(0, 1, 0), c(1, 1, 0), u)
    x01 = _lerp(c(0, 0, 1), c(1, 0, 1), u)
    x11 = _lerp(c(0, 1, 1), c(1, 1, 1), u)
    return _lerp(_lerp(x00, x10, v), _lerp(x01, x11, v), w)


def fbm3(seed: int, x: float, y: float, z: float, octaves: int = 3,
         lacunarity: float = 2.0, gain: float = 0.5) -> float:
    """分形叠加（多倍频噪声），生成更自然的起伏。"""
    total = 0.0
    amp = 1.0
    norm = 0.0
    freq = 1.0
    for i in range(max(1, int(octaves))):
        total += noise3(seed + i * 7919, x * freq, y * freq, z * freq) * amp
        norm += amp
        amp *= gain
        freq *= lacunarity
    return total / norm if norm else 0.0


def _noise(seed: int, x: float, y: float, z: float, octaves: int) -> float:
    return fbm3(seed, x, y, z, octaves) if octaves > 1 else noise3(seed, x, y, z)


def dir_of(n: V) -> str:
    """把任意法线粗化成六个方向名之一。"""
    ax, ay, az = abs(n.x), abs(n.y), abs(n.z)
    if ay >= ax and ay >= az:
        return "up" if n.y > 0 else "down"
    if ax >= az:
        return "east" if n.x > 0 else "west"
    return "south" if n.z > 0 else "north"


class Shape:
    """一个体素体积。只回答"属不属于"，不关心材质。"""

    __slots__ = ("_pred", "_bounds", "_normal", "_t", "label")

    def __init__(self, pred: Pred, bounds: Box, normal: Optional[NormalFn] = None,
                 t: Optional[TFn] = None, label: str = "shape") -> None:
        self._pred = pred
        self._bounds = box(bounds)
        self._normal = normal
        self._t = t
        self.label = label

    # ------------------------------------------------------------ 查询
    @property
    def bounds(self) -> Box:
        return self._bounds

    def contains(self, p) -> bool:
        return self._pred(V(int(p[0]), int(p[1]), int(p[2])))

    __contains__ = contains

    def normal(self, p) -> V:
        """表面法线。没提供解析法线时用中心差分估计（对体素足够）。"""
        if self._normal is not None:
            return self._normal(p)
        c = V(int(p[0]), int(p[1]), int(p[2]))
        return V(int(self.contains(c + V(1, 0, 0))) - int(self.contains(c - V(1, 0, 0))),
                 int(self.contains(c + V(0, 1, 0))) - int(self.contains(c - V(0, 1, 0))),
                 int(self.contains(c + V(0, 0, 1))) - int(self.contains(c - V(0, 0, 1))))

    def t(self, p) -> float:
        """归一化参数，默认按高度：底 0 → 顶 1。"""
        if self._t is not None:
            return self._t(p)
        b = self._bounds
        span = max(1, b.hi.y - b.lo.y)
        return (p.y - b.lo.y) / span

    # ------------------------------------------------------------ 构造器
    @classmethod
    def expr(cls, pred: Pred, bounds, label: str = "expr") -> "Shape":
        """任意谓词。bounds 是遍历范围（必须包住所有可能命中的坐标）。"""
        return cls(pred, bounds, label=label)

    @classmethod
    def box(cls, bx) -> "Shape":
        b = box(bx)
        return cls(lambda p: p in b, b, label="box")

    @classmethod
    def sphere(cls, center, r: float) -> "Shape":
        c = V(int(center[0]), int(center[1]), int(center[2]))
        r = float(r)
        lo = V(c.x - int(r) - 1, c.y - int(r) - 1, c.z - int(r) - 1)
        hi = V(c.x + int(r) + 1, c.y + int(r) + 1, c.z + int(r) + 1)
        rr = r * r

        def pred(p: V) -> bool:
            d = (p.x - c.x) ** 2 + (p.y - c.y) ** 2 + (p.z - c.z) ** 2
            return d <= rr

        def nrm(p: V) -> V:
            return V(p.x - c.x, p.y - c.y, p.z - c.z)

        return cls(pred, box(lo, hi), normal=nrm, label=f"sphere({c},{r:g})")

    @classmethod
    def cylinder(cls, center, r: float, height: int) -> "Shape":
        """竖直圆柱（中心在下底圆心）。"""
        c = V(int(center[0]), int(center[1]), int(center[2]))
        r = float(r)
        rr = r * r
        lo = V(c.x - int(r) - 1, c.y, c.z - int(r) - 1)
        hi = V(c.x + int(r) + 1, c.y + int(height) - 1, c.z + int(r) + 1)

        def pred(p: V) -> bool:
            return (0 <= p.y - c.y < height
                    and (p.x - c.x) ** 2 + (p.z - c.z) ** 2 <= rr)

        return cls(pred, box(lo, hi), label="cylinder")

    @classmethod
    def ellipsoid(cls, center, radii) -> "Shape":
        c = V(int(center[0]), int(center[1]), int(center[2]))
        rx, ry, rz = (float(radii[0]), float(radii[1]), float(radii[2]))
        lo = V(c.x - int(rx) - 1, c.y - int(ry) - 1, c.z - int(rz) - 1)
        hi = V(c.x + int(rx) + 1, c.y + int(ry) + 1, c.z + int(rz) + 1)

        def pred(p: V) -> bool:
            return (((p.x - c.x) / rx) ** 2 + ((p.y - c.y) / ry) ** 2
                    + ((p.z - c.z) / rz) ** 2) <= 1.0
        return cls(pred, box(lo, hi), label="ellipsoid")

    # ------------------------------------------------------------ 布尔
    @classmethod
    def union(cls, *shapes: "Shape") -> "Shape":
        lo = shapes[0].bounds.lo
        hi = shapes[0].bounds.hi
        for s in shapes[1:]:
            lo = V(min(lo.x, s.bounds.lo.x), min(lo.y, s.bounds.lo.y),
                   min(lo.z, s.bounds.lo.z))
            hi = V(max(hi.x, s.bounds.hi.x), max(hi.y, s.bounds.hi.y),
                   max(hi.z, s.bounds.hi.z))
        return cls(lambda p: any(s.contains(p) for s in shapes), box(lo, hi),
                   label="union")

    @classmethod
    def intersect(cls, *shapes: "Shape") -> "Shape":
        return cls(lambda p: all(s.contains(p) for s in shapes),
                   shapes[0].bounds, label="intersect")

    @classmethod
    def subtract(cls, a: "Shape", b: "Shape") -> "Shape":
        return cls(lambda p: a.contains(p) and not b.contains(p),
                   a.bounds, label="subtract")

    @classmethod
    def hollow(cls, shape: "Shape", thickness: int = 1) -> "Shape":
        """只留外壳。厚壳判断：到边界的切比雪夫距离 < thickness 的算内部。"""
        t = max(0, int(thickness))

        def inner(p: V) -> bool:
            for dx in range(-t, t + 1):
                for dy in range(-t, t + 1):
                    for dz in range(-t, t + 1):
                        if max(abs(dx), abs(dy), abs(dz)) > t:
                            continue
                        if not shape.contains(p + V(dx, dy, dz)):
                            return False
            return True

        return cls(lambda p: shape.contains(p) and not inner(p),
                   shape.bounds, label="hollow")

    # ------------------------------------------------------------ 参数曲面 / 变形
    @classmethod
    def torus(cls, center, major: float, minor: float, axis: str = "y") -> "Shape":
        """圆环体。``major`` 是环半径，``minor`` 是管半径，``axis`` 是环面法线方向。"""
        c = V(int(center[0]), int(center[1]), int(center[2]))
        R, r = float(major), float(minor)
        pad = int(math.ceil(R + r)) + 1

        def pred(p: V) -> bool:
            dx, dy, dz = p.x - c.x, p.y - c.y, p.z - c.z
            if axis == "y":
                rad, axial = math.hypot(dx, dz), dy
            elif axis == "x":
                rad, axial = math.hypot(dy, dz), dx
            else:
                rad, axial = math.hypot(dx, dy), dz
            return (rad - R) ** 2 + axial ** 2 <= r * r

        return cls(pred, box(V(c.x - pad, c.y - pad, c.z - pad),
                             V(c.x + pad, c.y + pad, c.z + pad)),
                   label=f"torus(R={R:g},r={r:g})")

    @classmethod
    def warp(cls, shape: "Shape", amplitude: float = 2.0, frequency: float = 0.08,
             seed: int = 0, octaves: int = 1) -> "Shape":
        """域变形：用噪声扰动坐标后再判断是否属于原形状。

        这是"让几何自然起来"的主力 —— 规整的球体揉一下就像岩石，
        笔直的地基揉一下就像天然崖壁。
        """
        a = float(amplitude)
        pad = int(math.ceil(a)) + 1
        b = shape.bounds
        bounds = box(V(b.lo.x - pad, b.lo.y - pad, b.lo.z - pad),
                     V(b.hi.x + pad, b.hi.y + pad, b.hi.z + pad))
        f = float(frequency)
        oct_ = max(1, int(octaves))

        def pred(p: V) -> bool:
            q = V(int(math.floor(p.x + _noise(seed, p.x * f, p.y * f, p.z * f, oct_) * a)),
                  int(math.floor(p.y + _noise(seed + 7919, p.x * f, p.y * f,
                                              p.z * f, oct_) * a)),
                  int(math.floor(p.z + _noise(seed + 104729, p.x * f, p.y * f,
                                              p.z * f, oct_) * a)))
            return shape.contains(q)

        return cls(pred, bounds, label="warp")

    @classmethod
    def lattice(cls, bx, spacing: int, radius: float) -> "Shape":
        """格状排布的小球。配合 ``Shape.subtract`` 挖出规则镂空（孔洞阵列）。"""
        b = box(bx)
        sp = max(1, int(spacing))
        rr = float(radius) ** 2

        def pred(p: V) -> bool:
            dx = (p.x - b.lo.x) % sp
            dy = (p.y - b.lo.y) % sp
            dz = (p.z - b.lo.z) % sp
            dx = min(dx, sp - dx)
            dy = min(dy, sp - dy)
            dz = min(dz, sp - dz)
            return dx * dx + dy * dy + dz * dz <= rr

        return cls(pred, b, label="lattice")

    @classmethod
    def field(cls, center, radii, seed: int = 0, frequency: float = 0.09,
              threshold: float = -0.30, octaves: int = 3, bias: float = 0.50) -> "Shape":
        """噪声雕塑：椭球范围内按噪声裁剪，生成有机形状（浮石 / 云团 / 岩体）。

        ``threshold`` 调密实度（**越大越空**），``bias`` 控制边缘衰减
        （越大体积越向中心缩）。默认参数给出约一半的填充率。
        同一 seed 结果完全一致。
        """
        c = V(int(center[0]), int(center[1]), int(center[2]))
        rx, ry, rz = (float(radii[0]), float(radii[1]), float(radii[2]))
        base = Shape.ellipsoid(center, radii)
        f = float(frequency)
        th = float(threshold)
        bi = float(bias)
        oct_ = max(1, int(octaves))

        def pred(p: V) -> bool:
            if not base.contains(p):
                return False
            d = math.sqrt(((p.x - c.x) / rx) ** 2 + ((p.y - c.y) / ry) ** 2
                          + ((p.z - c.z) / rz) ** 2)
            n = _noise(seed, p.x * f, p.y * f, p.z * f, oct_)
            return n - d * bi > th

        return cls(pred, base.bounds, label="field")

    def __repr__(self) -> str:  # noqa: D105
        return f"Shape({self.label}, {self._bounds})"


class Brush:
    """材质侧：给定坐标（和它所在 Shape 的上下文）返回要写的方块。"""

    __slots__ = ("_fn", "label")

    def __init__(self, fn: Callable[[V, Shape], Optional[Block]], label: str = "brush") -> None:
        self._fn = fn
        self.label = label

    def of(self, p: V, shape: Shape) -> Optional[Block]:
        return self._fn(p, shape)

    # ------------------------------------------------------------ 构造器
    @classmethod
    def solid(cls, block, **state) -> "Brush":
        b = make(block, **state)
        return cls(lambda p, s: b, label=f"solid({b.short()})")

    @classmethod
    def by_height(cls, stops: Sequence[Tuple[float, float, object]],
                  grad: float = 0.0) -> "Brush":
        """按形状内的归一化高度分段上色。

        stops: ``[(t_lo, t_hi, block), ...]``，t 取值 0（底）到 1（顶）。
        ``grad`` > 0 时在段间加一段过渡带（按位置哈希混合），避免硬边。
        """
        table = [(float(a), float(b), make(c)) for a, b, c in stops]

        def fn(p: V, s: Shape) -> Optional[Block]:
            t = s.t(p)
            for a, b, c in table:
                if a <= t < b:
                    return c
            return table[-1][2] if t >= table[-1][1] else table[0][2]

        return cls(fn, label="by_height")

    @classmethod
    def by_normal(cls, mapping: Dict[str, object], default=None) -> "Brush":
        """按表面法线换材质。键可写 up/down/north/south/east/west，
        也可写 side（等价于任意水平方向）。"""
        table = {k.lower(): make(v) for k, v in mapping.items()}
        dflt = make(default) if default is not None else None

        def fn(p: V, s: Shape) -> Optional[Block]:
            d = dir_of(s.normal(p))
            if d in table:
                return table[d]
            if d != "up" and d != "down" and "side" in table:
                return table["side"]
            return dflt

        return cls(fn, label="by_normal")

    @classmethod
    def by_distance(cls, center, stops: Sequence[Tuple[float, float, object]]) -> "Brush":
        """按到某点的距离分段（球面径向分层）。"""
        c = V(int(center[0]), int(center[1]), int(center[2]))
        table = [(float(a), float(b), make(v)) for a, b, v in stops]

        def fn(p: V, s: Shape) -> Optional[Block]:
            d = ((p.x - c.x) ** 2 + (p.y - c.y) ** 2 + (p.z - c.z) ** 2) ** 0.5
            for a, b, v in table:
                if a <= d < b:
                    return v
            return table[-1][2] if d >= table[-1][1] else table[0][2]

        return cls(fn, label="by_distance")

    @classmethod
    def gradient(cls, axis: str = "y", stops: Sequence[Tuple[float, object]] = ()) -> "Brush":
        """沿某个轴按**世界坐标**渐变（与形状无关），stops 是 [(坐标值, block), ...]。"""
        ai = {"x": 0, "y": 1, "z": 2}[axis.lower()]
        table = sorted(((float(k), make(v)) for k, v in stops), key=lambda kv: kv[0])

        def fn(p: V, s: Shape) -> Optional[Block]:
            v = p[ai]
            out = table[0][1]
            for k, b in table:
                if v >= k:
                    out = b
                else:
                    break
            return out

        return cls(fn, label=f"gradient({axis})")

    @classmethod
    def noise(cls, mapping: Dict[str, float], seed: int = 0,
              base=None, **base_state) -> "Brush":
        """按位置哈希混合（同 shape 内每个位置独立决定，确定性）。"""
        from .world import _pos_hash
        table = [(make(k), float(v)) for k, v in mapping.items()]
        base_b = make(base, **base_state) if base is not None else None

        def fn(p: V, s: Shape) -> Optional[Block]:
            r = _pos_hash(seed, p.x, p.y, p.z) / 0x100000000
            acc = 0.0
            for blk, w in table:
                acc += w
                if r < acc:
                    return blk
            return base_b

        return cls(fn, label="noise")

    @classmethod
    def fn(cls, f: Callable[[V, Shape], object]) -> "Brush":
        """自定义：``lambda p, shape: "stone" if p.y % 2 else None``（None 表示跳过）。"""
        cache: Dict[object, Block] = {}

        def inner(p: V, s: Shape) -> Optional[Block]:
            v = f(p, s)
            if v is None or v is False:
                return None
            if isinstance(v, Block):
                return v
            b = cache.get(v)
            if b is None:
                b = cache[v] = make(v)
            return b

        return cls(inner, label="fn")

    def __repr__(self) -> str:  # noqa: D105
        return f"Brush({self.label})"
