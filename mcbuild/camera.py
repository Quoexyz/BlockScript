"""第一人称透视渲染 —— 站在建筑里往外拍一张。

`image.py` 是**等距平行投影**：没有视点，所有视线平行，所以没有近大远小。
看整体比例很好用，但站在走廊里看两端的墙一样大，读不出纵深 ——
**室内必须用透视**。本模块实现一个最普通的针孔相机。

    w.camera.shot("out/inside.png",
                  eye=(2.5, 66.6, 5.5),        # 眼睛位置（可给浮点）
                  look_at=(2.5, 66.0, 24.0),   # 看向哪
                  fov=70)                       # 水平视场角

    w.camera.shot("out/back.png", eye=(2.5, 66.6, 24.0), yaw=180, pitch=-8)

**与 `w.image` 的关系**：共用调色板、子格形状、PNG 写出，但投影模型不同。
等距看整体（外部全景）、透视看人视角（室内 / 特写），两者互补，不要互相替代。

约定：

* ``yaw`` 与 `world.rot_y` 一致，俯视顺时针 —— ``0`` 朝 +z（南），
  ``90`` 朝 -x（西），``180`` 朝 -z（北），``270`` 朝 +x（东）
* ``pitch`` **向下为正**（和 Minecraft 一致），``0`` 水平，``-15`` 抬头
* ``look_at`` 与 ``yaw``/``pitch`` 二选一：前者"看向那个东西"，后者"朝西偏下 10 度"

已知限制：画家算法按面中心距离排序，相机**贴脸**某一格时那格自己的几个面
可能互相遮挡错乱（体素是轴对齐的，绝大多数角度没事）。彻底解决要上 z-buffer，
不划算 —— 贴脸拍改用带坐标的 `w.render.section()` 更合适。
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from .block import is_solid
from .image import (CLOUD_KINDS, FULL, SKY_HORIZON, SKY_TOP, Canvas, RGB,
                    color_of, shape_of)
from .vec import Box, V, box


# ============================================================ 向量小工具
# 用裸元组而不是 V：相机坐标是浮点的，而 V 是整数网格坐标，混用容易出错。

def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _norm(a):
    m = math.sqrt(_dot(a, a))
    return (0.0, 0.0, 0.0) if m < 1e-9 else (a[0] / m, a[1] / m, a[2] / m)


# ============================================================ 立方体六个面

#: ``(法线, 4 个顶点相对格子 min 角的偏移)`` —— 顶点从外侧看是逆时针的。
#: 等距渲染只画三个面（顶/南/东），**透视必须六个都支持** ——
#: 站在屋里往北看，看到的是北墙的南侧面；往南看则是南墙的北侧面。
_FACES = (
    ((0, 1, 0), ((0, 1, 0), (0, 1, 1), (1, 1, 1), (1, 1, 0))),
    ((0, -1, 0), ((0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1))),
    ((0, 0, 1), ((0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1))),
    ((0, 0, -1), ((0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0))),
    ((1, 0, 0), ((1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1))),
    ((-1, 0, 0), ((0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0))),
)

#: 固定光照下的面明暗。**不随相机变** —— 否则转个角度同一面就变色了。
FACE_SHADE = {
    (0, 1, 0): 1.00, (0, -1, 0): 0.48,
    (0, 0, 1): 0.78, (0, 0, -1): 0.70,
    (1, 0, 0): 0.62, (-1, 0, 0): 0.56,
}


def _blocked(world, pos, normal) -> bool:
    """这个面外侧是不是被实心方块挡住了（整格方块才判）。"""
    nb = world.get(pos + V(normal[0], normal[1], normal[2]))
    return (not nb.is_air) and is_solid(nb)


def _resolve_box(world, bx) -> Optional[Box]:
    if bx is None:
        return world.bounds()
    if isinstance(bx, Box):
        return bx
    if isinstance(bx, str):
        try:
            hit = world.marks.boxes[bx]
        except (KeyError, TypeError):
            hit = None
        if hit is None:
            raise ValueError(f"未定义的区域锚点 {bx!r}")
        return hit
    if isinstance(bx, (tuple, list)) and len(bx) == 2:
        return box(V(*bx[0]), V(*bx[1]))
    raise ValueError(f"bx 只接受 Box / 区域名 / (lo, hi)，收到 {bx!r}")


# ============================================================ 相机

class Camera:
    """最普通的针孔相机：位置 + 朝向 + 视场角。

    ``eye`` 可以给浮点坐标（站在两格之间）—— 这很重要，
    整数位置意味着眼睛永远在格子的角上。
    """

    def __init__(self, eye, look_at=None, yaw: float = 0.0, pitch: float = 0.0,
                 fov: float = 70.0, width: int = 960, height: int = 540,
                 near: float = 0.06) -> None:
        self.eye = (float(eye[0]), float(eye[1]), float(eye[2]))
        if look_at is not None:
            d = _sub((float(look_at[0]), float(look_at[1]), float(look_at[2])),
                     self.eye)
            if _dot(d, d) < 1e-9:
                raise ValueError("look_at 和 eye 重合了，定不出朝向")
        else:
            cy, sy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
            cp, sp = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
            d = (-sy * cp, -sp, cy * cp)     # yaw=0 朝 +z，pitch 向下为正
        self.forward = _norm(d)

        r = _cross(self.forward, (0.0, 1.0, 0.0))
        if _dot(r, r) < 1e-9:                # 正上/正下看时没有唯一的右方向
            r = (1.0, 0.0, 0.0)
        self.right = _norm(r)
        self.up = _cross(self.right, self.forward)

        self.width = max(1, int(width))
        self.height = max(1, int(height))
        self.near = float(near)
        self.fov = float(fov)
        # 焦距（像素）：水平视场角决定
        self.f = (self.width / 2.0) / math.tan(math.radians(fov) / 2.0)

    def project(self, p) -> Optional[Tuple[float, float, float]]:
        """世界点 -> ``(屏 x, 屏 y, 深度)``；落在近平面之后就返回 ``None``。"""
        d = _sub(p, self.eye)
        z = _dot(d, self.forward)
        if z <= self.near:
            return None
        return (self.width / 2.0 + _dot(d, self.right) / z * self.f,
                self.height / 2.0 - _dot(d, self.up) / z * self.f,
                z)

    def facing(self, center, normal) -> bool:
        """这个面是否朝向相机（背面剔除）。"""
        return _dot(normal, _sub(center, self.eye)) < 0.0

    def visible(self, p, radius: float = 1.5) -> bool:
        """粗筛：点是否落在视锥的大致范围里，省掉屏幕外的投影开销。"""
        d = _sub(p, self.eye)
        z = _dot(d, self.forward)
        if z < -radius:
            return False
        lim = max(z, 0.0) * math.tan(math.radians(self.fov) / 2.0) * 2.0 + radius
        return (abs(_dot(d, self.right)) <= lim
                and abs(_dot(d, self.up)) <= lim)

    def __repr__(self) -> str:  # noqa: D105
        fx, fy, fz = self.forward
        return (f"Camera(eye=({self.eye[0]:.1f},{self.eye[1]:.1f},{self.eye[2]:.1f}), "
                f"dir=({fx:.2f},{fy:.2f},{fz:.2f}), fov={self.fov:g}, "
                f"{self.width}x{self.height})")


# ============================================================ 渲染器

class CameraView:
    """``w.camera`` —— 透视渲染入口（挂在 World 上，惰性构造）。"""

    def __init__(self, world) -> None:
        self.w = world
        # **和 `w.image` 共用同一张覆盖表** —— 用户想的是"给这个世界的材质换个色"，
        # 而不是"只给等距渲染换色"。所以 `w.image.color(...)` 设一次，
        # 透视渲染也跟着变（反过来也一样）。
        self.palette: Dict[str, RGB] = world.image.palette

    def color(self, name: str, rgb) -> "CameraView":
        """覆盖某个材质的颜色（链式）。**和 `w.image` 共用**，设一次两边都生效。"""
        self.palette[name] = tuple(int(x) for x in rgb)   # type: ignore[assignment]
        return self

    def colors(self, mapping: Dict[str, tuple]) -> "CameraView":
        for k, v in mapping.items():
            self.color(k, v)
        return self

    def shot(self, out: str, eye, look_at=None, yaw: float = 0.0,
             pitch: float = 0.0, fov: float = 70.0, width: int = 960,
             height: int = 540, bx=None, max_dist: float = 140.0,
             bg: RGB = SKY_TOP, horizon: RGB = SKY_HORIZON) -> str:
        """拍一张。返回写出的路径。

        | 参数 | 说明 |
        |---|---|
        | `eye` | 眼睛位置，**可给浮点**（`(2.5, 66.6, 5.5)` 站在两格之间） |
        | `look_at` | 看向的点；与 `yaw`/`pitch` 二选一 |
        | `yaw` / `pitch` | 朝向角（`yaw` 俯视顺时针，`pitch` **向下为正**） |
        | `fov` | 水平视场角，游戏常用 70 |
        | `width` / `height` | 出图尺寸 |
        | `bx` | 限制遍历范围（Box / 区域名），默认全世界 |
        | `max_dist` | 超过这个距离的方块不画（内部拍摄用不到远景） |
        """
        cam = Camera(eye, look_at=look_at, yaw=yaw, pitch=pitch, fov=fov,
                     width=width, height=height)
        rng = _resolve_box(self.w, bx)
        if rng is None:
            raise ValueError("空世界，无法渲染")

        ex, ey, ez = cam.eye
        near2 = max_dist * max_dist
        faces: List[tuple] = []
        culled = 0

        for pos in rng:
            blk = self.w.get(pos)
            if blk.is_air:
                continue
            cx, cy, cz = pos.x + 0.5, pos.y + 0.5, pos.z + 0.5
            if not cam.visible((cx, cy, cz), 1.5):
                continue
            if (cx - ex) ** 2 + (cy - ey) ** 2 + (cz - ez) ** 2 > near2:
                continue

            sh = shape_of(blk, self.w, pos)
            whole = (sh == FULL)
            col = color_of(blk, self.palette)
            org = (pos.x + sh[0], pos.y + sh[4], pos.z + sh[1])
            scl = (sh[2] - sh[0], sh[5] - sh[4], sh[3] - sh[1])

            for normal, verts in _FACES:
                # 邻居挡住就跳过。只对整格判定；子格（栏杆/半砖/楼梯）照画，
                # 多画几个面在室内反而更正确。
                if whole and _blocked(self.w, pos, normal):
                    continue

                pts = [(org[0] + v[0] * scl[0],
                        org[1] + v[1] * scl[1],
                        org[2] + v[2] * scl[2]) for v in verts]
                # 面中心（对角顶点取中点即可）
                mx = (pts[0][0] + pts[2][0]) * 0.5
                my = (pts[0][1] + pts[2][1]) * 0.5
                mz = (pts[0][2] + pts[2][2]) * 0.5
                if not cam.facing((mx, my, mz), normal):
                    continue

                scr = []
                for p in pts:
                    pr = cam.project(p)
                    if pr is None:            # 跨过近平面 -> 整面丢弃
                        scr = None
                        break
                    scr.append((pr[0], pr[1]))
                if scr is None:
                    culled += 1
                    continue

                k = FACE_SHADE[normal]
                if blk.name in CLOUD_KINDS:   # 云是漫反射的，侧面不该压太暗
                    k = 1.0 if normal == (0, 1, 0) else max(k, 0.82)
                faces.append(((mx - ex) ** 2 + (my - ey) ** 2 + (mz - ez) ** 2,
                              scr,
                              tuple(min(255, int(c * k)) for c in col)))

        if not faces:
            raise ValueError(
                "这个视角看不到任何方块 —— 检查 eye 是不是被方块包住了，"
                "或者朝向反了（yaw=0 朝 +z，即南）、max_dist 太小")

        faces.sort(key=lambda f: -f[0])       # 画家算法：远的先画
        cv = Canvas(cam.width, cam.height, bg, horizon)
        for _, scr, rgb in faces:
            cv.quad(scr, rgb)
        return cv.save(out)

    #: `render` 是 `shot` 的别名，和 `w.image.render` 手感一致
    def render(self, out: str, **kw) -> str:
        return self.shot(out, **kw)


class CameraMixin:
    """挂在 World 上：`w.camera`。"""

    def _init_camera(self) -> None:
        self._camera = None

    @property
    def camera(self) -> CameraView:
        """第一人称透视渲染（室内 / 人视角，见 `camera.py`）。"""
        if self._camera is None:
            self._camera = CameraView(self)
        return self._camera
