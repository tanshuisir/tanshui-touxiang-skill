# 一次启动、连续等待、一次看图

普通照片转换默认四配色，使用此编排；同对话已加载且无变更时复用，不每次重读。首次未加载全局gen-img规则时先读一次；已知需要网络提权时，在下方exec_command按当前工具规则加入必要审批参数，不先试已知失败的沙箱请求。模型、审批和工作区规则不变。

替换照片、当前项目与已安装Skill的绝对路径（通常为 `${CODEX_HOME:-$HOME/.codex}/skills/tanshui-touxiang-skill`；JavaScript字符串本身不展开这些环境变量）。用户补充可直接加--notes；单图要求加 `--variants 1`；指定四张完整原作可加 `--colorway-references 25 55 16 47`；已有brief或确认后的final仅替换taskArgs，不另起编排。默认不要求先单独view照片/025，不编写未观察的特征。025仍由执行器作为风格输入上传。单图、四配色及选版高清均只启动一次编码底稿模型请求，随后本地蒙版精确填色；单图一套计划，四配色四套。默认请求1024×1024的1:1留白胸像底稿，按square规则适配后本地解码、共用蒙版换色及2×2拼接；每版1024×1024、拼图2048×2048，不拆成四次生图。四配色原始编码底稿必须不透明；单图可先将透明背景边缘合成技术白底，全透明空图拒绝。适配用白色编码底，最终四配色每版按一张已核对、背景明亮非白原作的整套角色色填入；肤面/肤影须同原作精确值，单图同样使用一张原作完整方案，不独立选择角色色，线色随对应原作，线条几何不变；不放大、不裁切、不拉伸。

```javascript
// @exec: {"yield_time_ms": 1000, "max_output_tokens": 2500}
const taskPhoto = "/absolute/path/photo.png";
const taskWorkspace = "/absolute/path/current-project";
const taskSkillDir = "/absolute/path/tanshui-touxiang-skill";
const taskArgs = [
  "python3", taskSkillDir + "/scripts/run_avatar.py",
  "--photo", taskPhoto
];
const shellQuote = value => "'" + value.replace(/'/g, "'\\''") + "'";
const taskTimings = {orchestration_started_at: Date.now(), process_result_received_at: null, review_images_ready_at: null};
let taskProcess = await tools.exec_command({
  cmd: taskArgs.map(shellQuote).join(" "),
  workdir: taskWorkspace,
  yield_time_ms: 1000,
  max_output_tokens: 1800
});
let taskLog = taskProcess.output || "";
while (taskProcess.session_id) {
  taskProcess = await tools.write_stdin({
    session_id: taskProcess.session_id,
    chars: "",
    yield_time_ms: 30000,
    max_output_tokens: 1800
  });
  taskLog += "\n" + (taskProcess.output || "");
}
taskTimings.process_result_received_at = Date.now();
let taskSummary;
for (const line of taskLog.trim().split(/\r?\n/).reverse()) {
  try {
    const item = JSON.parse(line);
    if (item && item.result_file && item.status) {
      taskSummary = item;
      break;
    }
  } catch (_) {}
}
if (!taskSummary) {
  text({status: "unresolved", output: taskLog.slice(-1800), orchestration_timing: taskTimings});
  exit();
}
text(taskSummary);
if (taskSummary.status !== "completed" || !taskSummary.review_assets) {
  text({orchestration_timing: taskTimings});
  exit();
}
const taskRoles = ["photo", "output", "style_reference"];
const taskImages = await Promise.allSettled(taskRoles.map(role =>
  tools.view_image({path: taskSummary.review_assets[role]})
));
taskTimings.review_images_ready_at = Date.now();
for (let index = 0; index < taskImages.length; index++) {
  const item = taskImages[index];
  text(taskRoles[index]);
  if (item.status === "fulfilled") image(item.value.image_url);
  else text({status: "view_failed", role: taskRoles[index]});
}
text({orchestration_timing: {
  ...taskTimings,
  execution_to_images_seconds: (taskTimings.review_images_ready_at - taskTimings.orchestration_started_at) / 1000,
  scope: "same exec: process launch to image-tool completion; excludes earlier model work and later visual review/reply; not end-to-end"
}});
```

`functions.exec` 若返回 `Script running with cell ID ...`，只用 `functions.wait` 等待该cell（每次不超过60秒）；上面代码仍在等待同一进程，不另用write_stdin轮询，也不重新运行代码。新用户输入或中断后先检查本次结果，不能直接重启收费请求。

成功返回时，三图已一批实际展示给主模型。立即用同一次视觉对照核对每版实际1024×1024、四配色拼图2048×2048，以及头高40%–48%、顶空12%–16%、两侧留白和肩胸可见；再核对照片人物特征、神态、统一实心眼形、各版与其来源原作的整套角色色，逐版确认普通头像尺寸下渐变两端颜色均有可辨面积、中间连续过渡且保留原作完整色彩差异，再核对四版同一线条几何和轮廓、明亮非白不透明纯色底，最终单图和拼图无编码白底、白边或白色拼缝；不要把肤色或背景必须互异当作目标，也不跨图混搭色；不要再单独读JSON、轮流看三图、额外做拼版/缩略图或长篇分析。用summary.delivery的绝对路径展示实际成品，不猜测固定avatar.png路径；四配色指向variants/avatar-four-colors.png，各版单图路径由summary.variant_files提供，summary.variants是数量4。注明预览版，结束本轮。渐变可以在头发、衣服或归入衣服角色的服饰上，同源多个可见部位的已采样渐变一并保留。全部路线均已本地检查原尺寸及128×128缩略图的最终RGB覆盖、过渡面积和跨度，但不能用这些指标代替本次人物与角色语义核对；微弱同色漂移、细边亮线、硬切色和抗锯齿不算渐变。发现明确偏离时简述问题，不称通过；fast不自动补画。

图片查看失败不等于自检通过。只针对缺失材料补看，不重生图片。失败或状态不明时按SKILL.md查原请求结果；此编排只有一个启动生图入口。解码失败或没有满足可见性要求的同源渐变时说明问题并保留底稿，不把无明显渐变的图片作为合格头像交付，不交付技术编码色、不自动再画；选择某一已生成版直接展示对应单图，只有明确要求高清才提交final。

orchestration_timing的三个Date.now()时间点分别为exec内发起进程前、收到最终进程结果、三图工具全部返回。execution_to_images_seconds只覆盖同exec内启动至图像工具完成，不含此前模型处理和此后快检/回复，不能当端到端耗时。

目标是照片收到至实际展示尽量短，≤90秒尚未证明稳定达成；四配色的本地处理也要计入，不承诺与单图同耗时。taskSummary中的脚本耗时不包含启动前、工具审批、主模型视觉对照及展示；不以循环等待、强制90秒超时或换格式声称达到目标。不修改宿主模型或推理强度。
