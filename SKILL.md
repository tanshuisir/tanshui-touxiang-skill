---
name: tanshui-touxiang-skill
description: 将真人照片转换为人物头像插图，保留辨识特征，采用参考库艺术配色与必需的局部渐变。默认先出小尺寸预览，经用户对话确认后再生成高清版。
---

# 碳水头像

默认先走快速预览：看照片与一张风格图，记下3–5项人物特征，调用一次，整理尺寸，立即展示实际PNG。默认 **HD-025线条造型 / flat大面＋局部渐变 / expressive艺术配色**；自动选一套参考库衍生色组，首版请求与交付均为 **512×512、quality low**，保持1:1比例。突出脸型、发型、眉眼关系与神态，减少微小装饰，仍保留艺术配色和必需局部渐变。用户明确指定的规格优先。

**展示预览后结束本轮，等待用户通过对话确认；收到“OK，生成高清版”等明确指示后才另行生成高清。** 仅提出修改时继续小尺寸预览，不自动升级。高清沿用原照片、原风格、人物特征及已认可内容，将已确认预览作为第三张输入；默认请求1024×1024、quality high，交付1000×1000 PNG，不将512预览简单放大充当高清。

本 Skill 依赖已配置的 `gen-img`。`<gen-img-dir>` 默认是 `$CODEX_HOME/skills/gen-img`（未设置 `CODEX_HOME` 时为 `~/.codex/skills/gen-img`），也可通过环境变量 `GEN_IMG_SKILL_DIR` 指定。仓库不包含网关凭据或 `gen-img` 本体；安装与依赖说明见 [README.md](README.md)。

## 快速流程（默认）

1. 实际查看用户照片和 `assets/finished/025.png`；本轮已看过就复用观察。选3–5项最有辨识力的可见特征，包含脸型/下颌或眉眼/鼻口关系，再结合发型、表情与配饰。用短句记录表情视线和头肩方向，不猜遮挡处或人物身份。
2. 读取全局 `<gen-img-dir>/SKILL.md`（本轮已读则复用），从当前项目工作区运行下面的一次命令。替换照片路径及观察文字；不需要先写JSON或阅读脚本源码。

```bash
python3 "<skill-dir>/scripts/run_avatar.py" \
  --photo "<absolute-user-photo>" \
  --feature "照片可见的脸型与下颌特征" \
  --feature "照片可见的发型剪影" \
  --feature "照片可见的眉眼或鼻口关系" \
  --expression "照片表情与视线" \
  --pose "照片头肩方向" \
  --clothing "照片衣领与关键配饰"
```

3. 等待同一进程完成；工具单次等待30–60秒，仍运行就继续等，不重新提交。`result.json` 中 `status: completed` 且有实际 `delivery` 路径时，立即用 `![头像](成品绝对路径)` 展示。默认不额外查看结果、制作对照拼版/128缩略图、填写自检JSON或自动重画。

预览交付时简短注明“预览版，确认后可生成高清版”，不在本轮继续调用。用户确认后，复用保存的brief与对应预览，不重复分析照片：

```bash
python3 "<skill-dir>/scripts/run_avatar.py" \
  --brief "<preview-output>/brief.json" --stage final \
  --approved-preview "<preview-output>/avatar.png"
```

`stage` 与自检用的 `workflow` 独立。保存的brief固定本次选中的 `art_palette`、`color_roles` 与 `gradient`，升级时不重新随机配色。阶段默认尺寸与质量不写死为显式字段，因此上述final调用采用高清默认值；已有brief若显式写了 `size`、`render_size` 或 `quality`，这些字段仍优先，升级时须按本次高清要求更新，保留人物和画风字段。用户一开始就明确要求直接高清时可用final，不额外强制预览。

快速流程只读本文件与全局gen-img规则；不默认检索照片、读取全部画风资料、查询模型列表、派子任务、做环境预检或重复读取参考图。短观察直接进入短提示词，不重复展开成逐项证据表。只有用户要求详细自检时才走下述review流程。

执行器把准备、网关调用和尺寸整理串成一次本地运行，保存brief、请求、上游原图、交付图与各阶段耗时。输出默认在当前工作区 `outputs/avatars/<时间-随机>/`；完成记录在该目录的 `result.json`。非空目录拒绝覆盖。`--brief <json>` 兼容已有brief；完整可选字段见 [references/prompt-template.md](references/prompt-template.md)，仅需要自定义时读取。

## 画风与人物边界

照片决定脸型、五官关系、发型剪影、神态、衣型及配饰形状；**肤色、发色、服装色与背景色全部按艺术配色重组，不受照片原色约束**。肤面可以是黄、白、粉紫或青，不固定为肉色；背景、主线和服饰也不固定为薄荷绿。照片观察里出现的“棕发、白衣”等颜色词不是保色指令，复用旧brief时去掉过时的natural保色要求。只有本次用户明确要求自然肤发时才选natural。

默认画法为平顺深色轮廓、简化实心眉眼、短鼻口线、平涂圆腮红、有限色族，以及少量脸侧硬边暗面和下颌颈影。第二张图提供线条造型，颜色以本次角色色方案为准；不复制参考人物的脸、发型结构、衣型或配饰形状。

**每张成品必须至少一处、通常1–2处清楚可见的二色连续渐变**，优先在头发、衣服或背景的封闭区域，写明区域、起止色和方向；不可见时转到背景。外缘锐利，渐变有可见面积与色差；硬切两块色、短亮线、抗锯齿和噪点都不能代替渐变。不对整脸作柔焦塑形。flat、bold、cartoon及双色等模式也必须执行此项；flat只表示主体大面平涂，不表示全图禁止渐变。

执行器从 [references/artistic-palettes.json](references/artistic-palettes.json) 本地选择一套完整色组：8套含黄肤、白肤、青肤和多种背景，源于高清参考采样与角色重分配；新增色与采样色分别记录。默认不读全库、不再联网取色。可用 `--palette <色组id>` 固定配色，或 `--palette reference` 采用选定参考的色彩关系；`color_roles` 可局部覆盖，`gradient` 可指定区域与端点。完整字段见参数文档。

保留年龄、可见不对称、表情含义与遮挡；选择已有的1–2项特征适度加强，其余简化。角度可以适当调整，头颈与五官透视保持合理，不统一成尖脸、大眼或幼态。暗形位于对应表面，通常不另描边；圆腮红与结构阴影区分形状和作用。不加写实皮肤、3D反光或背景悬浮投影。

用户指定其他画法时才读取 [references/finished-reference-index.md](references/finished-reference-index.md) 选一张独立参考，必要时查 [references/finished-style-guide.md](references/finished-style-guide.md) 与 [references/finished-palette-guide.md](references/finished-palette-guide.md)。支持flat、gradient、texture、bold、cartoon、duotone、glitch，均须配局部渐变；双色及偏色边使用expressive。69张高清参考保留原编号，051缺号。旧brief的 `palette_id` 对应另一套001–100，和 `hd_reference_id` 不能混用；跨版本对应见 [references/artwork-crosswalk.json](references/artwork-crosswalk.json)。默认任务无需遍历这些资料。

需要研究人物特征转译案例时才读 [references/yan-rujing-case.md](references/yan-rujing-case.md)。只有用户要求公众人物照片检索或补充对照案例时才读 [references/photo-comparison-method.md](references/photo-comparison-method.md) 和 [references/public-photo-catalog.json](references/public-photo-catalog.json)。检索到的相近造型不自动等于作者原照。

## 调用、失败与交付

执行器只调用全局 `<gen-img-dir>/scripts/run.py`，共用凭据、每会话模型缓存与精确排除 `gpt-image-2` 的逻辑，不另写网关请求。用户指定模型时原样传 `--model`，不擅自换型号；预览默认 `--quality low`，高清默认high，用户明确指定质量时保留。`gpt-image-2.5-flare` 与 `gpt-image-2.5-sunburst` 不受排除影响。

小尺寸与low是发给上游的实际请求，不先默认生成高清再缩小冒称节省资源。模型是否支持、是否执行参数以实际结果为准；若不支持，停止并说明限制，不自动换模型、回退高清或追加收费尝试。若上游忽略小尺寸返回更大原图，须注明此情况，可交付缩小预览，但不能据此宣称节省生成资源或固定比例的token。普通预览继续使用短提示词和已有观察，不增加默认详细自检。

遵守当前工具的网络和审批规则；本会话已证实沙箱网络不通时，第一次有效调用就按工具要求申请提权，省去已知会失败的探测。不修改审批策略，也不把审批前的等待记成模型生成时间。

每次阶段调用默认只发一次图片请求；预览完成不自动触发高清。失败、超时、中断或状态不明时查本次 `render/result.json`，不要自动重试、换模型或扩大成多轮收费生成。已完成上游调用但尺寸整理失败时保留原图与具体原因，不重新生图。用户提出修改后再做有针对性的编辑。

尺寸整理仅把更大的正方形等比缩至目标，交付PNG并保留原图；已有目标尺寸则不缩放。只允许去掉完全透明外缘，不拉伸、补框、擅自裁切人物或放大不足分辨率。实际文件尺寸才是交付依据。只展示头像，不默认输出色卡、标题、编号或样机；不把调用成功说成人物自检通过。

## 详细自检（仅显式要求时）

用户要求“逐项自检/对照检查/检查并修正”时，在brief设置 `workflow: "review"`，读取 [references/quality-workflow.md](references/quality-workflow.md)。此模式保留逐项 `identity_plan`、完整提示词、画风约束、对照图与视觉观察记录。执行器仍只生成一次；后续自检由Agent按该文档进行。只有此模式允许针对明确失败项自动追加最多一轮修正，状态不明不追加。自检不代替用户对预览的确认，修订保持本次stage和规格，不自动升级高清。

快速模式默认 `workflow: "fast"`，`max_automatic_corrections: 0`；旧版曾要求的默认自检不再应用于普通出图。不要为了通过自检改变用户选择的画法，也不输出无依据的相似度分数。
