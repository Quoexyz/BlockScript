# BlockScript

# 本项目还处于早期阶段，存在奇怪的BUG和缺少一些功能，暂时不会上传全部代码

> A structured Minecraft building DSL designed for language models, with spatial primitives, reusable components, validation, ASCII rendering, and schematic export.

BlockScript is a Python-based building DSL for generating Minecraft structures programmatically.

Instead of asking a language model to produce thousands of raw block placements, BlockScript gives it a structured spatial language: **frames, grids, components, stages, transforms, queries, regions, validation, and (textual) rendering**.


See examples: 
[EXAMPLE](https://github.com/Quoexyz/BlockScript/tree/main/demo)


![EXAMPLE-PICTURE](./demo/cloud_pavilion.png)

---

## ✨ Why BlockScript?
GPT6-Astra生成的Minecraft建筑非常不错，但是太贵了，我需要更便宜的

BlockScript支持纯文本模型通过ASCII渲染提供一定的空间理解，也将支持渲染图输入多模态模型（非常适合Deepseek4.1Flash）

BlockScript提供预制的建筑和检查工具，节省时间和试错成本
## 🗺️ Roadmap

Potential future directions include:
* richer architectural primitives
* improved spatial queries
* more powerful component composition
* better LLM-oriented error messages
* incremental build / repair workflows
* richer textual visualization
* additional schematic formats
* multimodal build feedback
* agent-based iterative construction

---

## 📄 License

MIT

---

## 💡 Concept

> **Minecraft is a voxel world.
> BlockScript is a language for describing how to build one.**

BlockScript is designed around a simple idea:

**Give language models spatial tools instead of asking them to memorize coordinates.**
