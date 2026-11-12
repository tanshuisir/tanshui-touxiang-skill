# 素材与取色说明

当前运行参考库为 70 张已确认头像，统一编号 TS-001—TS-070，存放在 `assets/templates/001.png` 至 `070.png`。尺寸均为 1000×1000 RGB；这是参考素材的整理尺寸，不保证为模型原生高清。此版不包含早期参考图片、其裁片或对应的历史素材目录。

## 可核验的数据

- `references/finished-reference-library.json`：当前模板图片路径、尺寸和 SHA-256。
- `references/source-colorways.json` 与 `references/colorways/`：每套当前模板的完整角色色。
- `references/source-role-colors.json`：当前图片上的 HEX 与像素坐标。实测色、已有渐变与同套角色回退应分别标记。
- `references/line-library.json` 与 `references/garment-library.json`：当前模板的线色和衣饰信息。
- `references/confirmed-cases.json`：确认过的修正及其适用范围；确认单张成品不表示整张图的所有表现都成为通用规则。

色值应当对应当前 PNG 的实际像素，不沿用其他图片上的旧取色坐标或哈希。某个部位在模板里不存在时，采用已记录的同套回退，不将它描述为实测部位。背景有变化的模板应如实保留采样说明；默认生图仍执行纯色背景规则。

## 介绍中的照片对照

README 使用三列展示 3 组实际照片与当前确认头像，编号为 TS-003、TS-009、TS-052。上排照片从原始图片文件等比适配到方形画布，不裁去边缘；下排直接引用当前模板 PNG。页面不使用截图，不嵌入全部 70 张模板总览。

公开核验清单为 `docs/images/showcase-source-manifest.json`，其中 `readme_showcase` 记录当前展示顺序、照片校验值和对应模板；清单同时保留先前对照板的素材记录，不包含本机绝对路径、会话记录或凭据。示例仅用于展示转换效果；照片中的人物身份不是本 Skill 的识别功能。

## 其他配色参考

`assets/color-cards/` 和 `references/four-swatch-cards.json` 保留用户提供的 100 组四色卡。它们为 `reference_only`，不替换默认 70 套完整角色配色。色卡网站入口保存在 `references/custom-palette-sources.md`，仅在要求设计新配色时使用。

## 使用范围

本次发布整理的是 Skill、当前模板及其可核验信息，不构成对照片或其他素材权利的统一授权。各素材权利仍归相应权利人；仓库没有附加统一开源许可证。
