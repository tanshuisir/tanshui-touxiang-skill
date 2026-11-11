# 头像参数与计划

普通请求从项目工作区运行：

```bash
python3 "<skill-dir>/scripts/run_avatar.py" --photo "/absolute/path/person-photo.jpg"
```

默认一次生成区域编码底稿、本地同几何四配色；单图加`--variants 1`。无需先手写特征表。照片作为人物事实输入，TS-025作为独立画法参考；调用完成后仍需实际看照片与成品。当前配色只用70套TS模板，随机规则见[source-colors.md](source-colors.md)，输出和选版见[four-colors.md](four-colors.md)。

最短brief：

```json
{
  "photo": "/absolute/path/person-photo.jpg",
  "identity_source": "photo"
}
```

```bash
python3 "<skill-dir>/scripts/run_avatar.py" --brief "<workspace>/brief.json"
```

`--photo`快捷路线默认`identity_source: photo`。直接构建旧brief时缺省仍可为`observations`；手写观察须至少3项真实特征，含脸型/五官关系，并有表情和姿态，不能写未观察事实。`photo`路线是模型读取照片，不表示主模型已看过或已自检。

## 常用参数

| 参数/字段 | 当前含义 |
|---|---|
| `--variants 1` / `4` | 单图或四配色，均只生成一张编码底稿 |
| `--colorway-reference 55` | 单图完整采用TS-055方案 |
| `--colorway-references 25 55 16 47` | 显式四套当前TS来源；示例不能作为固定默认 |
| `--random-colors` | 对已有brief明确重新抽色，非高清的默认行为 |
| `--reference 25` / `hd_reference_id` | 当前TS-025造型参考；兼容字段名不代表其他素材 |
| `--line-reference` | 兼容整套方案选择，不只借线色 |
| `--line-family` | 用线组织分类，不改变本版角色色 |
| `--stage preview` / `final` | 默认preview/low；明确高清用final/high |
| `--approved-preview` | 已批准单图路径，不传四宫格作为一个人物 |
| `--select-variant 2` | 冻结已有第2版的完整计划，供明确高清调用 |
| `--feature` | 基于实际观察的特征，可重复；不能只写颜色 |
| `--expression` / `--pose` | 照片神态、视线与头肩/肢体关系 |
| `--clothing` | 实际衣层、领袖、肩带、纹样和饰物 |
| `--stylization` | 最多1–2项适度加强，其他关系保留 |
| `--notes` | 本次明确补充，不能绕过编码或来源校验 |
| `--color-mode expressive` | 唯一支持的完整同源模式，natural冲突时停止 |
| `--model` | 交全局gen-img校验和精确过滤，不静默换型 |
| `--quality` | 显式值保留，默认按stage；不私降质量提速 |
| `--size` / `--render-size` | 本次明确的方形规格；默认每版1024×1024 |
| `--out-dir` | 当前项目内的新输出目录，不覆盖前版 |

`source_colorway_id`、`variant_plans`、`palette_selection`、`line_plan`、`garment_plan`、`object_plan`、角色色和渐变由脚本生成及校验，不手写伪造来源。每版完整计划只绑定同一个当前模板；高清冻结复用，不能独立改肤色或背景。过期brief不是重新带入被移除素材的入口。

## 实际编码与画法

`semantic-props-v3`保留外衣、内搭、领袖、纹样、配饰、帽饰等独立角色，并增加道具主面、不同材料次面和舌头。技术色是区域ID，不是成品颜色，不能交付。衣褶只用细疏结构线，不画`clothing_shadow`实心褶皱。道具不同材料分色，舌面非墨色，详见[object-details.md](object-details.md)。

人物以照片保留脸型、五官间距、发型剪影、神态、视线和真实衣饰。全头发内默认0–2线、最多3线；眼睛为本版主线色的可读实心形；嘴按照片与明确指令选择口线、简化唇形或露齿，不用写实眼白或唇纹。下颌有合理硬边颈影、腮红干净轻淡，衣层与遮挡后重现的部件连续。完整规范见[style-guide.md](style-guide.md)。

本地按同一模板的精确HEX和同角色渐变填色。背景铺满、不透明、单色，身体衣服贴底。默认留白胸像目标头高40%–48%、顶空12%–16%、下巴55%–64%、肩宽65%–80%；抬臂等完整动作可以适当拉远。1000×1000模板为参考显示图，不改变默认成品规格。

## 预览、选版与高清

选已有第几版只展示`variant_files`，不提交生图。明确要求某版高清：

```bash
python3 "<skill-dir>/scripts/run_avatar.py"   --brief "<preview-output>/brief.json" --select-variant 2 --stage final   --approved-preview "<preview-output>/variants/variant-02.png"
```

四版一起高清使用`--variants 4`，批准其中一张单图；重新生成不承诺与预览逐像素同线。需要同像素时复用已有蒙版本地填色，不能称重新生成高清。

只准备而不提交：

```bash
python3 "<skill-dir>/scripts/build_prompt.py"   --brief "<brief.json>" --out-dir "<new-request-dir>"
```

`prepared`不是图片生成成功。每阶段仅一次请求，模型或编码失败、请求未知时停止并保留记录，不自动重试或回退。详细人工计划仅在明确review时使用[quality-workflow.md](quality-workflow.md)。
