"""程序化构建共用的**确定性**工具 —— 让"同样的代码永远得到同样的结果"。

**所有伪随机必须走这里。** 绝不能用 Python 的 `hash()` —— 字符串哈希受
`PYTHONHASHSEED` 随机化，换个进程就全变了。对程序化生成来说这是致命的：
生成的坐标/尺寸/形状每次重建都不一样，而且**不会报错**，只是图每次都不一样。

两个坑（都是实测踩出来的，值得单独记下来）
------------------------------------------
**① 雪崩性不达标会毁掉整个分布。**
第一版用的是"异或 + 乘常数"的简易 FNV 变体。实测 2000 次采样里 **97% 落在
十分位的最后四格** —— 结果生成的半径几乎全一样（外环十四个岛全是 24）。
下面的 splitmix64 混洗雪崩性合格（十分位直方图 187–211）。

**② 形状扰动要用低阶谐波，不要用噪声。**
`wobble()` 刻意拿四阶低频正弦叠加：只用一两个谐波，轮廓还是"压扁的圆"，
一眼能看出是程序生成的；而**在 1 格分辨率的体素里，高阶噪声只会碎成锯齿**。

    from mcbuild.det import unit, in_range, wobble

    r = in_range(seed, 20, 44, i)              # 第 i 个岛的半径
    k = wobble(seed, theta, amp=0.14)          # 圆周上的形状扰动系数
"""

from __future__ import annotations

import math

M64 = 0xFFFFFFFFFFFFFFFF
TAU = 6.283185307179586


def hash64(seed: int, *vals: int) -> int:
    """把任意整数序列混成一个 64 位整数（splitmix64 变体）。"""
    h = (int(seed) & M64) + 0x9E3779B97F4A7C15
    for v in vals:
        h = (h ^ (int(v) & M64)) & M64
        h = (h * 0xBF58476D1CE4E5B9) & M64
        h ^= h >> 27
        h = (h * 0x94D049BB133111EB) & M64
        h ^= h >> 31
    return h


def unit(seed: int, *vals: int) -> float:
    """[0, 1) 的确定性伪随机数（取高 53 位，正好是 double 的有效精度）。"""
    return (hash64(seed, *vals) >> 11) / float(1 << 53)


def in_range(seed: int, lo: int, hi: int, *vals: int) -> int:
    """[lo, hi] 闭区间内的确定性整数。"""
    if hi <= lo:
        return int(lo)
    span = hi - lo
    return int(lo) + min(span, int(unit(seed, *vals) * (span + 1)))


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def profile_at(points, t: float) -> float:
    """分段线性插值。`points` 是 ``[(t, scale), ...]``，按 t 升序。

    典型用法是描述一块有机体的**纵剖面**：t=0 是顶面，t=1 是底部尖端。
    """
    if t <= points[0][0]:
        return points[0][1]
    if t >= points[-1][0]:
        return points[-1][1]
    for (t0, v0), (t1, v1) in zip(points, points[1:]):
        if t0 <= t <= t1:
            return lerp(v0, v1, (t - t0) / (t1 - t0))
    return points[-1][1]


def wobble(seed: int, theta: float, amp: float = 0.14, k: int = 3) -> float:
    """圆周上的确定性形状扰动（低频，四个谐波叠加）。

    只用一两个谐波的话轮廓还是"压扁的圆"，一眼就能看出是程序生成的。
    四个不同阶的谐波叠起来才有"这块是被撕下来的"那种不规则感。

    刻意用低阶正弦而不是噪声 —— 1 格分辨率的体素里，高阶噪声只会碎成锯齿。
    """
    p1 = unit(seed, 1) * TAU
    p2 = unit(seed, 2) * TAU
    p3 = unit(seed, 3) * TAU
    p4 = unit(seed, 4) * TAU
    return 1.0 + amp * (
        0.40 * math.sin(k * theta + p1)
        + 0.29 * math.sin((k + 2) * theta + p2)
        + 0.20 * math.sin((k + 4) * theta + p3)
        + 0.11 * math.sin((k + 6) * theta + p4))
