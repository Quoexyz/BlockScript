"""局部坐标系。

模型在 Frame 里只写相对坐标和相对方向（+u/-u/+v/-v/+w/-w，
或 front/back/left/right/up/down），落世界时统一做平移 + 旋转。
支持嵌套（相对父 frame 再偏移）。
"""

from __future__ import annotations

from .block import Block, make, rotate_block
from .ops import OpsMixin
from .vec import V, box, norm_yaw, rot_y, rotate_axis


class Frame(OpsMixin):
    def __init__(self, world, at=(0, 0, 0), yaw: int = 0, parent: "Frame | None" = None):
        self.world = world
        self.at = V(int(at[0]), int(at[1]), int(at[2]))
        self._local_yaw = norm_yaw(yaw)
        self.parent = parent
        # 有效 yaw 用于朝向重映射（父子的 yaw 叠加）
        self.yaw = norm_yaw((parent.yaw if parent else 0) + yaw)

    # -------------------------------------------------- 坐标变换
    def to_world(self, p) -> V:
        q = rot_y(V(int(p[0]), int(p[1]), int(p[2])), self._local_yaw) + self.at
        return self.parent.to_world(q) if self.parent else q

    def to_local(self, p) -> V:
        q = V(int(p[0]), int(p[1]), int(p[2]))
        if self.parent:
            q = self.parent.to_local(q)
        return rot_y(q - self.at, -self._local_yaw)

    def map_axis(self, axis: str) -> str:
        return rotate_axis(axis, self.yaw)

    @property
    def root(self):
        return self.world

    def _tx(self, name="", **kw):
        return self.world._tx(name, **kw)

    def __enter__(self) -> "Frame":
        return self

    def __exit__(self, *exc) -> None:
        return None

    # -------------------------------------------------- 基础写入
    def _resolve(self, block, state: dict) -> Block:
        if isinstance(block, Block):
            return rotate_block(block, self.yaw)
        return make(block, yaw=self.yaw, **state)

    def set(self, pos, block=None, **state) -> Block:
        b = self._resolve(block, state)
        self.world.set(self.to_world(pos), b)
        return b

    def fill(self, bx, block=None, **state) -> int:
        bx = box(bx)
        b = self._resolve(block, state)
        return self.world.fill(box(self.to_world(bx.lo), self.to_world(bx.hi)), b)

    def get(self, pos) -> Block:
        return self.world.get(self.to_world(pos))

    def empty(self, pos) -> bool:
        return self.get(pos).is_air

    # -------------------------------------------------- 标记
    def mark(self, name: str, pos) -> V:
        return self.world.marks.set_point(name, self.to_world(pos))

    def mark_box(self, name: str, bx):
        bx = box(bx)
        return self.world.marks.set_box(
            name, box(self.to_world(bx.lo), self.to_world(bx.hi)))

    def anchor(self, name: str) -> V:
        """取世界坐标锚点，若要局部坐标请自行 to_local。"""
        return self.world.marks.anchor(name)

    def frame(self, at=(0, 0, 0), yaw: int = 0) -> "Frame":
        """嵌套子坐标系（at 相对当前 frame）。"""
        return Frame(self.world, at, yaw, parent=self)

    # -------------------------------------------------- 组件
    def place(self, name: str, at=(0, 0, 0), yaw: int = 0, **params):
        """在局部坐标系里展开一个组件：坐标与朝向都会落到世界。

        这让组件可以嵌套 —— 组件内部的 ``t.place("子组件", ...)`` 用的是
        当前组件的局部坐标，父子关系会被记录下来。
        """
        return self.world.place(name, at=self.to_world(at),
                                yaw=self.yaw + int(yaw), **params)

    def __repr__(self) -> str:  # noqa: D105
        return f"Frame(at={self.at}, yaw={self.yaw})"
