# 碳水头像 Skill

将真人照片转换为正方形留白胸像插图，保留人物的脸型、发型剪影、五官关系、神态与关键衣饰。默认只请求一次区域编码底稿，再用本地蒙版填出四套完整原作配色，交付同线稿的四配色拼图；也支持单图。

仓库与 Skill 名称为 `tanshui-touxiang-skill`，在 Codex 中显示为“碳水头像”，通过 `$tanshui-touxiang-skill` 调用。

## 工作方式

| 阶段 | 模型请求 | 默认交付 |
|---|---|---|
| 预览 | 一次编辑，`quality low`、`size 1024x1024` | 四张 1024×1024 单图与一张 2048×2048 的 2×2 拼图，等待对话确认 |
| 高清 | 沿用原照片、风格参考和已确认单张预览，一次编辑，`quality high` | 重新绘制后按同一配色规则交付；每版仍为 1024×1024 |

编码底稿中的技术色只表示皮肤、头发、衣服等区域，不直接交付。单图与四图均由本地程序解码、精确填色；四版共用同一套角色区域与线条透明度蒙版，五官、轮廓和姿态一致，线色随各自的完整原作方案变化。

构图默认拉远到胸部中段，头高约占画布 40%–48%，发顶上方留白 12%–16%，保留颈、肩和上胸。这些比例是本 Skill 的构图目标。上游未返回方形时，仅对足够大的图片等比适配并保留全图，不裁脸、拉伸或放大；尺寸不足则停止。最终 PNG 为不透明 RGB，背景铺满整张画布。

选择已有某一版直接展示该单图，不发新请求。确认并明确要求高清后才进入高清阶段；高清重新生成，不放大预览，也不承诺与预览逐像素同线。用户一开始明确要求直接高清时可以直接进入该阶段。

每个阶段仅提交一次图片请求；失败、超时、状态不明、分区或颜色校验不可靠时保留记录并停止，不自动重试或换模型。目标为收到照片到展示 **90 秒以内，尚未证明稳定达成**；脚本计时不含调用前处理、审批及最终看图展示，本地处理也须计入实际耗时。

## 画风与配色

- 默认以 HD-025 提供造型参考：平顺轮廓、简化五官、实心短眉、短鼻口线、圆腮红及少量脸侧硬边暗面和下颌颈影。照片决定人物结构与衣饰形状，不复制参考人物。
- 保留年龄、不对称、表情和遮挡，可适度加强已有的 1–2 项辨识特征，不统一成幼态脸。
- 眼睛统一为短上眼睑连接向下的单色实心椭圆或圆角楔形，不画眼白、虹膜分层、高光或睫毛；保留人物眼距、倾斜与视线，闭眼可用短弧线。
- 发型执行 `silhouette-first-v3`：先保留整体剪影、体积、分缝和遮挡，全头发内默认 0–2 条必要结构线，最多 3 条；省略密集发丝、重复卷线和分条高光。
- 单图与四图统一执行 `single-source-colorways-v1`：每版从[完整原作配色目录](references/source-colorways.json)选择一张已核对原作，肤面、肤影、背景、发衣、腮红、细节、线色及渐变整套沿用该原作的实际采样。不得跨原作拼配或独立改角色色；单图默认 HD-025，四图默认 HD-025、HD-055、HD-016、HD-047。
- 肤面和硬边肤影必须精确来自 69 张原作中的同一原作、同一角色；无可靠肤影时复用肤面。全部路线均由本地蒙版填色，不新增皮肤色、高光或皮肤渐变。
- 背景为明亮、非白、不透明的单一纯色，无渐变、纹理、图案、阴影或白色拼缝。完整方案须满足背景加权亮度 ≥150/255，并排除亮度 ≥235 且 RGB 通道跨度 ≤48 的白色系；不合规的显式或已冻结方案停止，不静默改色。这些阈值是本 Skill 新增规则。
- 成品至少一处肉眼清晰的二色连续渐变，位于头发、衣服或属于衣服角色的服饰，使用对应原作同角色的完整端色与方向。`visible-source-gradients-v2` 检查最终 RGB 及 128×128 缩略图中的端色覆盖、连续过渡和色彩跨度；无合用的同源选项时停止，不造色或跨角色搬用端点。
- 只支持 `expressive` 完整同源配色；`natural` 会破坏整套来源，明确拒绝。旧混搭 brief 会迁移并记录，合规冻结方案继续复用；更多边界见[色库与来源](references/source-colors.md)。

像素与来源校验不能证明人物相似、角色分区或画面合格。生成后仍在同一次快速看图中对照照片、成品及造型参考；详细逐项自检仅在用户明确要求时启用。

## 参考插画

以下是参考库中署名 **776／七七六** 的插画，**不是本 Skill 生成的效果展示**。来源与素材范围见 [素材来源说明](ASSET_SOURCES.md)。

| HD-025 | HD-008 | HD-055 |
|---|---|---|
| ![776 参考插画 HD-025](assets/finished/025.png) | ![776 参考插画 HD-008](assets/finished/008.png) | ![776 参考插画 HD-055](assets/finished/055.png) |

## 安装与依赖

需要 **Python 3.10 或更高版本、Pillow，以及已配置的外部 `gen-img` Skill**。本仓库不包含 `gen-img` 本体、网关账号、API 密钥或其他凭据，由使用者自行安装和配置。

默认安装目录为 `${CODEX_HOME:-$HOME/.codex}/skills/tanshui-touxiang-skill`：

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
git clone https://github.com/tanshuisir/tanshui-touxiang-skill.git \
  "${CODEX_HOME:-$HOME/.codex}/skills/tanshui-touxiang-skill"
python3 -m pip install Pillow
```

目标目录已存在时先保留旧版本，再选择安装位置。执行器默认在 `$CODEX_HOME/skills/gen-img` 查找依赖；未设置 `CODEX_HOME` 时使用 `~/.codex/skills/gen-img`。其他位置可通过环境变量指定：

```bash
export GEN_IMG_SKILL_DIR="/你的安装路径/gen-img"
```

照片、风格参考与提示词会由该工具发送到已配置的生图服务。所有调用从自己的项目工作区发起，输出保存在项目内，不在 Skill 安装目录运行生成命令。

## 在 Codex 中使用

上传照片后提出：

> 使用 $tanshui-touxiang-skill，把这张照片转为头像插图，先出四配色预览，保留人物特点。

认可其中一版后回复：

> 选第 2 版，沿用人物特点与整套配色，生成高清版。

只需要单图时明确说“只出一张”；需要详细检查时说“请逐项对照检查人物特征与画风”。详细 `review` 不代替用户对预览的确认，也不自动升级高清。

## 命令行使用

```bash
AVATAR_SKILL="${CODEX_HOME:-$HOME/.codex}/skills/tanshui-touxiang-skill"
mkdir -p "$HOME/avatar-project"
cd "$HOME/avatar-project"
python3 "$AVATAR_SKILL/scripts/run_avatar.py" --photo "/绝对路径/人物照片.jpg"
```

照片直接交给生图模型提取人物特征，无须事先手写特征表。用户补充可用 `--notes`；手写观察仍可用，但不得填入未观察的照片事实。

单图及指定完整原作配色：

```bash
python3 "$AVATAR_SKILL/scripts/run_avatar.py" \
  --photo "/绝对路径/人物照片.jpg" --variants 1 --colorway-reference 55
```

四图可用 `--colorway-references 25 55 16 47` 指定四套完整原作。默认结果位于项目的 `outputs/avatars/<时间-随机>/`；实际交付路径读取 `result.json.delivery`，各版单图读取 `variant_files`，不要猜测固定路径。`brief.json` 保存人物输入、整套方案、来源编号和迁移记录。

用户确认后，选择第 2 版生成高清：

```bash
python3 "$AVATAR_SKILL/scripts/run_avatar.py" \
  --brief "/绝对路径/预览目录/brief.json" --select-variant 2 --stage final \
  --approved-preview "/绝对路径/预览目录/variants/variant-02.png"
```

四版一起高清时使用 `--variants 4`，批准预览仍传其中一张单图；不要将拼图当作一个人物输入。单图预览的高清则复用其 brief 与 `avatar.png`，不加 `--select-variant`。

| 常用参数 | 用途 |
|---|---|
| `--reference 25` | 选择造型参考，默认 HD-025；不独立替换其他角色色 |
| `--variants 1` | 只交付一张头像，仍走编码底稿及本地填色 |
| `--colorway-reference 55` | 为单图选择一套已入库完整原作配色 |
| `--colorway-references 25 55 16 47` | 为四图指定四套完整原作配色 |
| `--mode flat` | 主表现模式；另有 gradient、texture、bold、cartoon、duotone、glitch |
| `--model <型号>` | 交由全局 gen-img 校验和调用，不静默换型 |
| `--quality <质量>` | 覆盖阶段默认质量，具体支持情况由后端决定 |
| `--notes "补充要求"` | 记录人物、衣饰或构图等要求 |
| `--out-dir <新目录>` | 指定输出目录，拒绝覆盖非空目录 |

`flat` 仍要求人物局部渐变。复用旧 brief 时，CLI 会清除旧尺寸并迁移到默认方形胸像；只有本次用户明确指定其他方形尺寸才使用 `--size`，可选 `--render-size` 须同时有 `--size`。更多参数见[参数文档](references/prompt-template.md)，同线稿及选版流程见[四配色文档](references/four-colors.md)。只准备提示词时可使用 `scripts/build_prompt.py`，不提交生图。

## 模型约束

生图和编辑只通过全局 `gen-img` 执行，共用其模型过滤逻辑。当前偏好**精确排除 `gpt-image-2`**，不是按前缀过滤：`gpt-image-2.5-flare` 和 `gpt-image-2.5-sunburst` 不受此项排除影响，仍需出现在所用服务的可用目录中。指定型号不可用、被排除或没有其他可用型号时停止，不绕过偏好。

## 目录与测试

```text
.
├── SKILL.md                    Skill 入口与默认工作流
├── agents/openai.yaml          Codex 显示名称与默认提示
├── scripts/                    提示词、单次执行、精确填色、交付和可选自检
├── references/                 画风、整套配色、角色取样与来源资料
├── assets/finished/            69 张高清参考及总览，HD-051 缺号
├── assets/portraits/           早期拼版裁出的 100 张参考
├── assets/line-library/        分类线条研究素材
├── assets/cases/               有来源记录的照片研究资料
├── tests/                      不调用网关的离线测试
└── ASSET_SOURCES.md             第三方素材来源与范围
```

安装 Pillow 后，从 Skill 目录之外的项目工作区运行：

```bash
python3 -B -m unittest discover -s "$AVATAR_SKILL/tests" -p 'test_*.py'
```

测试使用本地合成图片和模拟网关，验证阶段切换、整套同源与精确肤色、禁白背景、方形构图、共享蒙版、渐变可见性和失败停止等行为；不调用生图服务，不证明新照片的生成相似度、实际角色语义或端到端耗时。

## 素材说明

仓库未收录使用者的私人输入照片、凭据或实际生图输出。参考插画、公开照片与衍生总览的来源及范围见 [ASSET_SOURCES.md](ASSET_SOURCES.md)。素材权益归各原权利人，本仓库没有为第三方素材授予 MIT 或其他新许可，也不声称原作者为本 Skill 背书。
