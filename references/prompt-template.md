# 头像参数与可选详细计划

普通出图使用 `scripts/run_avatar.py --photo ... --feature ... --expression ... --pose ...`，默认生成小尺寸预览，无需先读本文件或写JSON。下面的短brief适用于已有文件、可重复调用或自定义参数：

```json
{
  "photo": "/absolute/path/person-photo.jpg",
  "identity_features": ["照片可见的脸型与下颌", "照片可见的发型剪影", "照片可见的眉眼或鼻口关系"],
  "expression": "照片表情与视线",
  "pose": "照片头肩方向",
  "clothing": "照片衣领与关键配饰"
}
```

```bash
python3 "<skill-dir>/scripts/run_avatar.py" --brief "<workspace>/brief.json"
```

`identity_features` 至少3项，通常3–5项短句，必须基于实际看图。至少包含一项可见脸型或五官关系，不仅靠衣服发色。`expression` 与 `pose` 必填。省略的参数由默认值补齐，不额外询问。

## 自定义字段

| 字段 | 默认与用途 |
|---|---|
| `stage` | 默认preview：请求/交付512x512，quality low；final：请求1024x1024、交付1000x1000，quality high。final仅在用户对话确认预览并要求高清，或一开始明确要求直接高清时调用 |
| `approved_preview` | final阶段可用的已确认预览路径；经预览升级时传入，作为原照片与风格图之后的第三张输入。CLI用 `--approved-preview` |
| `workflow` | `fast`：短提示词、一次调用、尺寸整理后直接交付。`review`：仅用于用户明确要求的详细自检 |
| `hd_reference_id` | 25；高清编号保留原名，51缺号 |
| `palette_id` | 旧版001–100编号，仅兼容旧brief；不得与高清编号同时使用 |
| `mode` | 构建器/已有brief缺省auto，采用所选参考主模式；快捷照片CLI缺省flat。支持flat、gradient、texture、bold、cartoon、duotone、glitch |
| `color_mode` | 默认expressive：肤面、头发、服装和背景艺术重配色；只有本次用户明确要求自然肤发时才用natural。duotone/glitch要求expressive |
| `art_palette` | 默认auto，本地从8套参考库衍生色组选一套；也可传色组id固定，或reference采用选定参考的同源色彩关系。CLI用 `--palette` |
| `stylization` | 从已观察特征中选1–2项适度加强，其余概括；不要求逐度复刻角度 |
| `shadow_plan` | 少量脸侧硬边暗面、下颌颈影及必要接触暗部，不另描边、不加背景投影 |
| `framing` | 单人头肩、头顶留白、肩部可延伸到下缘，省略手机、手和原背景 |
| `color_roles` | 可选非空字符串值对象，按background、outline、skin_base、hair、clothing等覆盖对应角色，其余角色沿用色组；不按采样顺序硬套 |
| `gradient` | 每张必需，默认由色组提供；对象包含region（hair/clothing/background）、from/to（不同HEX）及direction，不可用纯平涂代替 |
| `user_notes` | 额外要求；CLI用 `--notes` |
| `size` | preview默认512x512，final默认1000x1000；显式值优先 |
| `render_size` | 预览默认与交付相同；1000x1000交付默认请求1024x1024；必须为正方形且不小于交付，显式值优先 |
| `model` | 不填则由全局gen-img自动选择；填写则原样传递，由全局目录与精确排除逻辑校验，不静默换型 |
| `quality` | preview默认low，final默认high；保留用户显式值，不为提速偷偷降低指定质量 |

人物照片是第一张输入，只决定人物结构与神态；一张独立风格头像是第二张，默认使用 `assets/finished/025.png`。线条造型参考与配色方案可以分开，颜色以下发角色色与渐变端点为准。肤色可以黄、白、青或粉紫，不绑定原照肉色/棕发/衣色。只有改选风格时才查索引，不用拼版作参考。

`flat`表示主体以平涂大面组织，仍必须局部渐变；所有主模式都至少一处，预览也不例外。渐变应在可见色块内连续过渡，外缘锐利，不把两块硬切色、噪点或短亮线当作渐变，不给全脸刷写实柔焦。`references/artistic-palettes.json` 区分原图采样与本Skill新增设计色，不冒充作者源工程色板。选中的完整方案写入 `generation-request.json.color_plan`；保存的brief固定本次 `art_palette`、`color_roles` 与 `gradient`，高清沿用此方案，不重新随机配色。

执行器调用全局gen-img，保留模型原图，按实际返回文件等比缩成真实目标PNG。失败或未知状态不重试；尺寸不符也不重新生图。调用和尺寸成功不等于已通过人物评审。默认直接展示 `result.json` 中的 `delivery`。

展示预览后结束本轮，说明“预览版，确认后可生成高清版”。用户只提出修改时继续预览；收到明确确认并要求高清的对话指示后另行运行：

```bash
python3 "<skill-dir>/scripts/run_avatar.py" \
  --brief "<preview-output>/brief.json" --stage final \
  --approved-preview "<preview-output>/avatar.png"
```

第三张图锁定已认可的构图、人物处理与配色；第一张仍决定人物特征，第二张仍提供画风。高清须重新请求足够分辨率，不简单放大预览。`stage` 与 `workflow` 相互独立，自检通过不代替用户确认。阶段默认尺寸/质量不写死为显式字段；旧brief显式写有 `size`、`render_size` 或 `quality` 时，final仍保留，须按本次高清要求更新这些字段，人物、风格及已固定配色继续复用。

512x512与low会实际发给上游，具体模型支持与执行情况以结果为准。不支持时停止并说明，不自动改规格、换模型或追加尝试。若返回更大原图，可缩小供预览，但须注明上游未执行小尺寸请求，不能宣称已节省生图资源或固定比例的token。

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

fast使用 `avatar-fast-prompt.txt`，review使用详细 `avatar-prompt.txt`。请求文件保留可选review_spec用于手动检查，但fast的enabled为false、自动修正预算为0。review预算为1，执行器本身始终只调用一次。

需要只准备而不提交时，继续使用：

```bash
python3 "<skill-dir>/scripts/build_prompt.py" --brief "<brief.json>" --out-dir "<全新请求目录>"
```

该命令仅输出提示词与gen-img argv，`prepared`不是生图成功。`${size}`为请求尺寸，`${delivery_size}`为交付尺寸；执行器及finalizer以文件真实尺寸为准，不拉伸或擅自裁切，不放大低分辨率图。

## 耗时记录

`run_avatar.py` 的结果分别记录preparation、gateway_process、delivery与total秒数，并引用上游api_seconds。gateway_overhead为网关进程时长减API时长，包含启动、选型和保存等；它不是纯网络时间。上游headers/body不能直接拆成服务器生成与纯下载。

这些计时从脚本真正启动开始，不包含Agent看图、组织调用、工具审批或调度等待。结合结果UTC时间戳与会话工具时间线才可核对用户体感总耗时。不要据一次离线测试或较短提示词承诺固定秒数。
