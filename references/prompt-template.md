# 头像参数与可选详细计划

普通出图使用 `scripts/run_avatar.py --photo <absolute-photo>`，无需先手写特征/表情/姿态、单独查看照片/025或写JSON。默认low质量，一次编码底稿生成四张1024×1024正方形留白胸像及2048×2048拼图；`--variants 1` 只出单图。按 [连续编排](fast-orchestration.md) 一次启动、等待及批量看图后快速自检交付。同对话已加载且无变更的gen-img规则和025复用。下面的短brief用于已有文件、重复调用或自定义参数：

```json
{
  "photo": "/absolute/path/person-photo.jpg",
  "identity_source": "photo"
}
```

```bash
python3 "<skill-dir>/scripts/run_avatar.py" --brief "<workspace>/brief.json"
```

runner的 `--photo` 快捷路线默认 `identity_source: "photo"`；直接调用build_prompt处理旧brief时缺省仍为observations，照片直传JSON须显式写photo。photo路线以照片为人物事实源，由生图模型直接识别并保留脸型/下颌、五官关系、发型、神态、视线、头肩和可见衣饰；不表示主模型已观察或已通过自检。此路线无需identity_features、expression或pose。已有手写特征/brief路线继续兼容：其identity_features至少3项，通常3–5项，须基于真实看图，至少包含脸型或五官关系，并有expression和pose；不只靠发色衣服，不填未观察事实。

发型观察只写整体体积、长短、分缝、刘海方向及关键遮挡，不罗列每缕发丝或每个发卷。默认提示词将相邻小发束合并为少量大色块，保留发型类别与辨识轮廓；高清沿用预览的简化程度，不补回碎发或细碎高光。仅在用户明确要求更细致发型时，通过 `user_notes` 说明本次例外。

眼睛观察仅记眼距、眼宽、上眼睑倾斜/开合、视线和眉眼关系，不把照片眼白、虹膜颜色或反光写成必须复刻的特征。眼睛统一用短上眼睑连接向下的单色实心椭圆或圆角楔形，沿用库内选定主线色；不画包围眼白的杏仁形外框、眼白、独立虹膜/瞳孔层、反光点或镂空高光、睫毛及细致下眼睑。照片只决定眼距、眼宽、上眼睑倾斜与开合、视线和左右差异，并保留与眉毛的关系；闭眼/笑眼可用短弧线，不强行把所有人画成困倦半睁眼。此眼睛画法适用于全部模式、fast/review与预览/高清；旧brief、特征转译、所选参考或已确认旧预览含写实眼部细节时，以本规则重画眼睛，其余已认可内容继续保留。该规则由构建器统一注入并记录在 `review_spec.style_lock.eye_style`，无需新增brief字段；`identity_plan`、`stylization` 或 `user_notes` 中冲突的旧眼部画法不生效。

## 自定义字段

| 字段 | 默认与用途 |
|---|---|
| `identity_source` | runner --photo快捷路线默认photo；直接build_prompt处理未设置此字段的旧brief仍默认observations。photo由生图模型读取照片，review_spec.plan_source为photo_requirements；requirement是保留要求，不是主模型的photo_evidence。已有手写观察路线保留 |
| `variants` | CLI默认4，一次编码底稿、本地共用蒙版四配色；1保留单图路线。直接build_prompt或run API未设时仍兼容旧单图默认 |
| `variant_plans` | 执行器冻结的四套完整同源配色，执行single-source-colorways-v1，每版记录对应原作编号与路径；符合新策略时验证复用，旧跨图混搭方案自动迁移并记录；不要手写伪造来源 |
| `colorway_reference_id` | 单图本次新选完整原作编号；CLI为 --variants 1 --colorway-reference 55。优先于旧冻结选择，保存后清除临时字段。 |
| `source_colorway_id` | 选定某版后冻结其完整原作方案，单图高清仍沿用该来源；旧art_palette和随机肤色/背景规则不得覆盖 |
| `stage` | preview默认low，final默认high；两阶段每版1024×1024正方形胸像，四配色拼图2048×2048。final仍需对话确认或用户一开始明确要求高清 |
| `approved_preview` | final阶段可用的已确认预览路径；经预览升级时传入，作为原照片与风格图之后的第三张输入。CLI用 `--approved-preview` |
| `workflow` | `fast`：短提示词、一次调用、不透明交付及一次快速成品检查（含统一眼睛与背景）。`review`：仅用于用户明确要求的详细自检 |
| `hd_reference_id` | 25；高清编号保留原名，51缺号 |
| `palette_id` | 旧版001–100编号，仅兼容旧brief；不得与高清编号同时使用 |
| `mode` | 构建器/已有brief缺省auto，采用所选参考主模式；快捷照片CLI缺省flat。支持flat、gradient、texture、bold、cartoon、duotone、glitch |
| `color_mode` | 所有模式仅expressive；natural会拆散同源方案，停止说明。 |
| `art_palette` | 兼容完整配色选择器/旧别名，不提供独立角色色；新单图建议source_colorway_id或--colorway-reference。 |
| `skin_template_id` | 由完整同源方案派生，不独立选择；旧值不符时整套迁移并记录。 |
| `background_template_id` | 由同一原作完整方案派生，不独立替换；旧值不符时整套迁移。 |
| `line_reference_id` | 所有模式随完整原作配色；CLI兼容--line-reference也选择整套方案，未入库则停止。 |
| `line_family` | 按mode选择用线分类；可为rounded-monoline、bold-graphic、fine-structured、open-duotone、offset-accent。CLI用 `--line-family`，组织规则来自line-library.json |
| `stylization` | 从已观察特征中选1–2项适度加强，其余概括；不要求逐度复刻角度 |
| `shadow_plan` | 少量脸侧硬边暗面、下颌颈影及必要接触暗部，不另描边、不加背景投影 |
| `framing` | 默认composition.py留白胸像：头高40%–48%、顶空12%–16%、肩胸可见；旧紧凑构图迁移。本次自定义直接brief须设framing_policy: custom，补充也可用--notes |
| `color_roles` | 由完整同源方案派生；旧独立覆盖整体迁移，不能拼接其他原作或库外色。 |
| `gradient` | 所有交付每张必需，普通头像尺寸下两端颜色均有可辨面积、连续过渡且色彩差异清楚。头发只是一个位置，可用衣服或归入clothing的服饰色块。全部路线本地按可见填色分布映射，核对最终RGB及128×128缩略图的端点覆盖、过渡面积和颜色跨度，不只数插值步数。单图和四图均使用同原作同角色实际完整端色与方向，多个可见部位的已采样渐变一并保留；覆盖不足仅可用同原作同角色gradient_options，无选项停止，不造色、独立设计或跨角色搬端点。 |
| `user_notes` | 额外要求；CLI用 `--notes` |
| `size_policy` | 默认square，旧native迁移square。CLI按本次--size决定是否explicit，旧尺寸不继承 |
| `size` | square每版固定1024x1024；四配色拼图2048x2048。explicit为本次单版交付尺寸，CLI用本次--size覆盖，拼图宽高各为单版两倍 |
| `render_size` | square固定1024x1024，始终向gen-img传--size；explicit默认与size相同，可用--render-size指定更大方形 |
| `model` | 不填则由全局gen-img自动选择；填写则原样传递，由全局目录与精确排除逻辑校验，不静默换型 |
| `quality` | preview默认low，final默认high；保留用户显式值，不为提速偷偷降低指定质量 |

人物照片是第一张输入，只决定人物结构与神态；一张独立风格头像是第二张，默认使用 `assets/finished/025.png`。造型参考与配色来源可以分开；四配色的每一版必须整套对应同一入库原作，不能因造型参考为025便把025线色或腮红强塞进其余三版。肤色不绑定照片原色，也不能挪用原作发色。只有改选风格时才查索引，不用拼版作模型参考。

单图、四配色及选版高清的模型输出均为 `avatar-master-prompt.txt` 指定的技术编码底稿，不直接使用成品角色色或渐变。本地按source-colorways.json中已核对的完整原作逐版填色，肤色、肤影、背景、发衣、腮红、细节、线色与渐变同源；四版共用一套角色ID和线条透明度蒙版，仅线色随各版方案变化。肤色/背景可重复，不能为求互异改色。用 `--colorway-references 25 55 16 47` 可指定四张目录内原作。完整输出、选版与本地重填见[四配色](four-colors.md)。

每版外轮廓、五官、发内与衣饰结构统一使用该版 `line_plan.primary_hex`；绘制方式按库中分类和部位规则执行。阴影、头发填色与辅助亮线不当作主线；当前辅助线色仅存档、不绘制，也无启用参数。四配色保持各自原作的线色与背景配对；单图也沿用完整原作的线色与背景配对；`line_reference_id`、`line_family` 与配色一起保存，高清不随机变更。原图精确取样及69张索引见 [line-design-guide.md](line-design-guide.md)。旧brief显式outline若未入库需明确改选参考，不能让模型猜一个相近色继续执行。

`flat`表示主体以平涂大面组织，所有主模式、预览/高清和每张单图仍须至少一处肉眼清晰的主体渐变。两端颜色、连续过渡与足够面积在普通头像显示尺寸下均可辨，头发只是一个案例，衣服或服饰也可保留自身角色的原作渐变。全部路线仅读缓存的完整原作计划，在可见填色分布内映射，并检查最终RGB及128×128缩略图的端点覆盖、过渡面积和颜色跨度，不以很多插值步数冒充效果。渐变外缘锐利；微弱同色漂移、仅细边着色、硬切两块色、噪点、短亮线和抗锯齿不算渐变，也不给全脸刷写实柔焦。像素检查不证明分区语义，仍需一次快速视觉核对。缺少合用同源渐变时明确停止，不把无明显渐变的图片作为合格头像交付，不新增生图请求。`references/artistic-palettes.json` 仅为历史档案及选择器别名，所有模式不使用它拼接，统一使用完整同源目录；历史背景渐变数据可保留，但新成品纯色背景规则优先。完整同源目录的所有角色规则优先于艺术色组、旧brief和旧预览。已记录的旧同源渐变按 `visible-source-gradients-v2` 补齐原作完整端色，保留原作编号及其余角色色；仅迁移与已知旧目录精确一致的计划，篡改色或来源不符仍拒绝，当前合规冻结方案精确复用。 选中的完整方案与迁移理由写入请求；保存的brief固定本次 `skin_template_id`、`background_template_id`、`art_palette`、`source_colorway_id`、`line_reference_id`、`line_family`、`color_roles` 与 `gradient`，高清沿用此方案，不重新随机配色。

预览和高清背景都必须是满幅不透明单一纯色，无背景渐变、纹理、图案或阴影，与头发和衣服的大面积角色色形成明显色相/冷暖及明度反差。构建器派生 `generation-request.json.background_plan`，保留原背景、调整理由和规划范围；所有模式背景不合适时改选整套原作，不独立换底或计算新颜色；旧背景渐变也随整套方案迁移，不搬到服装重造端点。非HEX角色无法自动计算反差，实际画面仍须确认。

明确传--background opaque与--size 1024x1024，保留原图，默认交付固定方形RGB PNG。正方形原图必要时等比缩小；默认square下足够大的长方形原图等比适配到计划纯色方形画布，底边对齐，保留全图，不裁脸、拉伸或放大，不额外生图。尺寸不足停止。单图透明区合成计划纯色，全透明空图拒绝交付。四配色原始编码底稿必须不透明，透明则停止；先用白色编码底完成square适配，再解码并填入四套成品颜色。记录实际宽高和操作；尺寸正确不证明人物比例或背景纯色合格，仍做一次快速对照。

展示预览后结束本轮，说明“预览版，确认后可生成高清版”。用户只提出修改时继续预览；收到明确确认并要求高清的对话指示后另行运行：

```bash
python3 "<skill-dir>/scripts/run_avatar.py" \
  --brief "<preview-output>/brief.json" --select-variant 2 --stage final \
  --approved-preview "<preview-output>/variants/variant-02.png"
```

选择已有第几版只展示对应 `variant_files`，不发请求。某版高清用上例；四版一起高清用 `--variants 4` 并批准其中一张单图，不能上传拼图作为一名人物。单图路线用其原有 `avatar.png`。重新生成final不承诺与preview逐像素同线。

stage与workflow独立。保存brief冻结四套计划、颜色模板、主线和渐变，并记录square及upper-body-v1。高清high质量重新生成每版1024×1024胸像，四配色拼图2048×2048，不放大预览。CLI读旧brief清除旧尺寸和紧凑大头构图；仅本次明确其他方形尺寸时传--size，可选--render-size须同时有--size。图3保留认可的人物处理与配色，旧大头特写按新胸像规则迁移。用户明确quality保留。

每阶段默认只提交一次quality与--size 1024x1024，不因尺寸调整追加请求或探测多个尺寸；继续使用短提示词和preview上传副本。参数不支持时停止，不自动换型。实际速度据实测说明，本地缩图或离线测试不能证明端到端≤90秒。

## 仅显式review模式使用的计划

用户要求逐项自检时设置 `workflow: "review"`，才读取 [quality-workflow.md](quality-workflow.md)。每项主特征对应一项 `identity_plan`，格式：

```json
{
  "workflow": "review",
  "identity_plan": [
    {
      "feature_index": 1,
      "photo_evidence": "照片两颊饱满，下颌宽、下巴圆",
      "render_as": "保留圆脸剪影与下颌宽度，略加强面颊体积",
      "emphasis": "emphasize",
      "do_not_change": "不削尖下巴，不把成人画幼态"
    }
  ]
}
```

上例只展示一项，实际覆盖全部features。编号从1开始，不重复；emphasis为preserve或emphasize，最多两项加强。`stylization` 与计划保持一致。fast模式无需写此字段；已有brief提供时仍校验并保留画法与边界。

全部模式和阶段以 `avatar-master-prompt.txt` 模板构建实际提交的提示词，将人物要求保留在一次区域编码底稿请求中，单图与四图均在本地按完整同源方案填入颜色及渐变。`avatar-fast-prompt.txt` 和详细 `avatar-prompt.txt` 仅保留作计划材料，不绕过本地颜色与渐变校验。请求文件保留可选review_spec用于手动检查，但fast的enabled为false、自动修正预算为0。review预算为1，执行器本身始终只调用一次。

需要只准备而不提交时，继续使用：

```bash
python3 "<skill-dir>/scripts/build_prompt.py" --brief "<brief.json>" --out-dir "<全新请求目录>"
```

该命令只准备提示词和gen-img argv，prepared不是生图成功。默认将1024x1024与1:1写入提示词和--size，explicit用本次方形尺寸。实际PNG宽高才是交付依据，不能把请求参数当成成功证明。

## 上传副本与耗时记录

仅preview制作上传副本：照片最长边≤1024、独立风格参考≤512。原始输入保留，final继续使用原照片、原风格参考和批准预览；已有更小输入不放大。请求记录实际上传副本及其准备耗时。压缩上传可减少文件体积，是否降低API延迟需实测，不能据此保证提速。

目标是收到照片至实际展示≤90秒，属于优化目标，尚不能保证。不要以强制超时、后台转交或本地缩图冒称完成加速。

`run_avatar.py` 的结果分别记录preparation、gateway_process、delivery与total秒数，并引用上游api_seconds。四配色另记录 `local_recolor_seconds`，默认交付读取 `delivery`，各版路径读取 `variant_files`；`variants` 是数量4。gateway_overhead为网关进程时长减API时长，包含启动、选型和保存等；它不是纯网络时间。上游headers/body不能直接拆成服务器生成与纯下载。

这些计时从脚本真正启动开始，不包含Agent看图、组织调用、工具审批或调度等待。结合结果UTC时间戳与会话工具时间线才可核对用户体感总耗时。44秒脚本运行不能证明端到端已达标。不要据一次快样本、离线测试、压缩上传或较短提示词承诺固定秒数；headers/body也不直接代表纯生成/下载。
