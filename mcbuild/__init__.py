"""mcbuild —— 让大语言模型像使用 three.js 一样构建 Minecraft 建筑。
坐标约定：+X 东、+Z 南、+Y 上（与 Minecraft 一致）。
Frame 内部轴写作 u / v / w，朝向写 +u/-u/+v/-v/+w/-w 或 front/back/left/right/up/down。
"""

from . import anvil, det, registry
from .block import (AIR, Block, BlockStateError, Fam, classify, make,
                    mirror_block, rotate_block)
from .camera import Camera, CameraView
from .compare import Compare, Diff
from .component import ComponentMixin, Instance
from .frame import Frame
from .grid import Grid
from .image import Image
from .marks import MarkLayer
from .ops import OpsMixin
from .palette import FAMILIES, family_map, retexture
from .preview import Preview, PreviewMixin
from .shape import Brush, Shape
from .stage import Stage, StageMixin
from .vec import Box, V, box, rot_y
from .world import World

__all__ = [
    "World", "Frame", "Block", "AIR", "V", "Box", "box", "rot_y",
    "make", "classify", "Fam", "BlockStateError", "rotate_block",
    "mirror_block", "OpsMixin", "MarkLayer",
    "Grid", "Instance", "ComponentMixin", "Compare", "Diff",
    "Stage", "StageMixin", "Image", "Preview", "PreviewMixin",
    "Shape", "Brush", "FAMILIES", "family_map", "retexture",
    "registry", "Camera", "CameraView",
    "anvil", "det",
]

__version__ = "0.4.0"
