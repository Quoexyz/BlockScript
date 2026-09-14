"""向量、包围盒、方向常量与绕 Y 轴旋转。

坐标约定与 Minecraft 一致：
    +X = 东   +Z = 南   +Y = 上
yaw 约定：从上往下看顺时针旋转的角度（度），且必须是 90 的倍数。
    yaw=0   局部 +u -> +X(东),  +v -> +Z(南)
    yaw=90  局部 +u -> +Z(南),  +v -> -X(西)
"""

from __future__ import annotations

from typing import Iterator, NamedTuple


class V(NamedTuple):
    """整数三维向量。"""

    x: int
    y: int
    z: int

    def __add__(self, o) -> "V":
        return V(self.x + o[0], self.y + o[1], self.z + o[2])

    def __sub__(self, o) -> "V":
        return V(self.x - o[0], self.y - o[1], self.z - o[2])

    def __neg__(self) -> "V":
        return V(-self.x, -self.y, -self.z)

    def __mul__(self, k: int) -> "V":
        return V(self.x * k, self.y * k, self.z * k)

    __rmul__ = __mul__

    def replace(self, **kw) -> "V":
        d = {"x": self.x, "y": self.y, "z": self.z}
        d.update(kw)
        return V(int(d["x"]), int(d["y"]), int(d["z"]))

    def __repr__(self) -> str:  # noqa: D105
        return f"({self.x},{self.y},{self.z})"


class Box(NamedTuple):
    """闭区间包围盒，lo/hi 均包含在内。"""

    lo: V
    hi: V

    @property
    def size(self) -> V:
        return V(self.hi.x - self.lo.x + 1,
                 self.hi.y - self.lo.y + 1,
                 self.hi.z - self.lo.z + 1)

    def volume(self) -> int:
        s = self.size
        return s.x * s.y * s.z

    def __contains__(self, v) -> bool:
        if not isinstance(v, V):
            return False
        return (self.lo.x <= v.x <= self.hi.x
                and self.lo.y <= v.y <= self.hi.y
                and self.lo.z <= v.z <= self.hi.z)

    def __iter__(self) -> Iterator[V]:
        for y in range(self.lo.y, self.hi.y + 1):
            for z in range(self.lo.z, self.hi.z + 1):
                for x in range(self.lo.x, self.hi.x + 1):
                    yield V(x, y, z)

    def intersect(self, other: "Box") -> "Box | None":
        lo = V(max(self.lo.x, other.lo.x), max(self.lo.y, other.lo.y), max(self.lo.z, other.lo.z))
        hi = V(min(self.hi.x, other.hi.x), min(self.hi.y, other.hi.y), min(self.hi.z, other.hi.z))
        if lo.x > hi.x or lo.y > hi.y or lo.z > hi.z:
            return None
        return Box(lo, hi)

    def union(self, other: "Box") -> "Box":
        return Box(V(min(self.lo.x, other.lo.x), min(self.lo.y, other.lo.y), min(self.lo.z, other.lo.z)),
                   V(max(self.hi.x, other.hi.x), max(self.hi.y, other.hi.y), max(self.hi.z, other.hi.z)))

    def __repr__(self) -> str:  # noqa: D105
        return f"{self.lo}..{self.hi}"


def box(a, b=None) -> Box:
    """构造包围盒。box(V) / box(a, b) 两角顺序任意。"""
    if b is None:
        if isinstance(a, Box):
            return a
        b = a
    a = V(int(a[0]), int(a[1]), int(a[2]))
    b = V(int(b[0]), int(b[1]), int(b[2]))
    return Box(V(min(a.x, b.x), min(a.y, b.y), min(a.z, b.z)),
               V(max(a.x, b.x), max(a.y, b.y), max(a.z, b.z)))


NORTH = V(0, 0, -1)
SOUTH = V(0, 0, 1)
EAST = V(1, 0, 0)
WEST = V(-1, 0, 0)
UP = V(0, 1, 0)
DOWN = V(0, -1, 0)

CARDINAL_VEC = {"north": NORTH, "south": SOUTH, "east": EAST, "west": WEST,
                "up": UP, "down": DOWN}

# 从上往下看顺时针：北 -> 东 -> 南 -> 西
_CW_NEXT = {"north": "east", "east": "south", "south": "west", "west": "north"}


def norm_yaw(yaw: int) -> int:
    """把任意角度规整到 0/90/180/270。"""
    q = int(round(yaw / 90.0)) % 4
    return q * 90


def rot_y(v, yaw: int) -> V:
    """绕 Y 轴顺时针旋转（从上往下看）。"""
    v = V(int(v[0]), int(v[1]), int(v[2]))
    y = norm_yaw(yaw)
    if y == 0:
        return v
    if y == 90:
        return V(-v.z, v.y, v.x)
    if y == 180:
        return V(-v.x, v.y, -v.z)
    return V(v.z, v.y, -v.x)


def rotate_cardinal(name: str, yaw: int) -> str:
    """把水平朝向名按 yaw 顺时针旋转。"""
    if name not in _CW_NEXT:
        return name
    n = norm_yaw(yaw) // 90
    for _ in range(n):
        name = _CW_NEXT[name]
    return name


def mirror_cardinal(name: str, axis: str) -> str:
    """镜像朝向名。axis='x' 表示沿 X 轴翻转（东西互换）。"""
    if axis == "x":
        return {"east": "west", "west": "east"}.get(name, name)
    if axis == "z":
        return {"north": "south", "south": "north"}.get(name, name)
    return name


def rotate_axis(axis: str, yaw: int) -> str:
    """轴向属性只有 x/z 会互换。"""
    if axis == "y" or axis not in ("x", "z"):
        return axis
    if norm_yaw(yaw) % 180 == 90:
        return "z" if axis == "x" else "x"
    return axis
