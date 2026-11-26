# Skill-Use-Bench

`SF03_t1_merge_unordered` 使用公开原题、五份随附 PDF、`pdftk-server` 技能和上游评分器。适配器从固定 Git 提交读取原始字节，记录输入哈希。双方使用同一 Linux 工具链和 `STRUCTURED_*` 模型配置，分别在独立工作区执行。

## 运行和评分

在 Linux 或 WSL2 中执行对照。本 Agent 使用宿主的 `bwrap`、Bash 和 PDFtk。DeepSeek 一侧及确定性评分使用下列镜像。`--harness-sdk` 可指向单独的 Python SDK 源码检出。 [DeepSeek Harness 部署](../deepseek-harness-deployment.md)

```powershell
git clone --filter=blob:none --no-checkout --depth 1 https://github.com/JinyiHan99/Skill-Use-Bench.git .tmp/skill-use-bench-upstream
git -C .tmp/skill-use-bench-upstream fetch --depth 1 origin 1a80e93479e1a9f5ce4be2e27550edaf7f9d6ffc
docker build -t personal-agent-skill-use:local -f evals/Skill-Use-Bench/Dockerfile evals/Skill-Use-Bench
docker build -f evals/deepseek-runtime.Dockerfile --build-arg BASE_IMAGE=personal-agent-skill-use:local -t personal-agent-dsh-skill-use:local evals
python -m evals.Skill-Use-Bench.run --upstream .tmp/skill-use-bench-upstream --personal-skill --product-flags --output .tmp/skill-use-run
.\.venv\Scripts\python.exe -m evals.Skill-Use-Bench.grade .tmp/skill-use-run --output .tmp/skill-use-grade
```

基线对照省略 `--personal-skill`，并使用新的输出目录。`--product-flags` 使用项目配置的核验开关，省略时继承共享评测脚手架的覆盖。评分读取 `.env` 中的 `LONGDS_JUDGE_*`。官方 rubric 接收由双方原生调用和回执投影的轨迹。独立 PDF 检查同时调用上游验证函数并比较原文件与交付件的逐页文本、尺寸和旋转。原始轨迹、评分和实际交付件保存在各自的归档目录。

单独验证本 Agent 的作用域时，追加 `--agent personal-agent --personal-skill-scope project` 或 `--agent personal-agent --personal-skill-scope user`。`project` 同时安装同名的工程级和用户级技能，`user` 只安装用户级技能。评分会校验实际模型请求里的目录以及完整正文回执的来源。

[用例、证据与结果](../../docs/problems/Skill-Use-Bench/SF03_t1_merge_unordered.md)
