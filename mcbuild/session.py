"""会话与交互协议。

每轮回给模型固定四段：EXEC / RENDER / SUMMARY / LINT。
"""

from __future__ import annotations

from typing import List, Optional

from .lint import format_report, lint
from .vec import V, box


def report(world, exec_line: str = "", y: Optional[int] = None,
           render_box=None, show_diff: bool = True) -> str:
    """生成一整轮反馈文本。"""
    parts: List[str] = []

    parts.append("=== EXEC ===")
    parts.append(exec_line or f"ok: {len(world.ops_log)} ops, {len(world.cells)} cells written")

    parts.append("")
    parts.append("=== RENDER ===")
    d = world.dirty_box()
    if show_diff and d is not None:
        body = world.render.diff()
        parts.append(f"(diff, dirty {d.lo}..{d.hi})")
    else:
        yy = y
        if yy is None:
            b = world.bounds()
            yy = b.lo.y if b else 0
        body = world.render.slice(yy, render_box)
        parts.append(f"(slice y={yy})")
    parts.append(body)

    parts.append("")
    parts.append("=== SUMMARY ===")
    parts.append(world.render.summary())

    parts.append("")
    parts.append("=== LINT ===")
    parts.append(format_report(lint(world), world=world))

    return "\n".join(parts)


class Session:
    """多轮构建会话：快照、undo、自动存档、反馈生成。"""

    def __init__(self, world, autosave_path: Optional[str] = None) -> None:
        self.w = world
        self.autosave_path = autosave_path
        self.turn = 0

    def snapshot(self, tag: Optional[str] = None) -> None:
        """把当前状态设为基线（diff 从这里开始算）。"""
        self.w.checkpoint()

    def undo(self) -> bool:
        return self.w.undo()

    def redo(self) -> bool:
        return self.w.redo()

    def save(self, path: Optional[str] = None):
        path = path or self.autosave_path
        if path is None:
            raise ValueError("未指定存档路径")
        return self.w.export_json(path)

    def load(self, path: str):
        from .io import import_json
        return import_json(path, self.w)

    def step(self, exec_line: str = "", **kw) -> str:
        """执行一轮：产出反馈文本；如开启 autosave 则顺带落盘。"""
        self.turn += 1
        text = report(self.w, exec_line=exec_line, **kw)
        if self.autosave_path:
            self.save()
        return text

    def commit(self, exec_line: str = "", **kw) -> str:
        """产出反馈并把基线推进到当前状态。"""
        text = self.step(exec_line=exec_line, **kw)
        self.w.checkpoint()
        return text
