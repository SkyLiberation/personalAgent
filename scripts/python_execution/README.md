# 通用 Python 分析镜像

本目录只准备通用库环境，不含数据、解题程序或参考答案。Runtime 按显式 image ID 执行，不在任务中安装依赖或自动拉取镜像。许可、输入及执行协议由 [Python Spec](../../docs/optimization/to_verify/python-data-analysis-tool.md#35-longds-用例的条件适配)拥有。

从仓库根构建，并保存实际 image ID：

```powershell
docker build --iidfile .tmp/python-analysis-image-id.txt -t personal-agent-python-analysis:local scripts/python_execution
```

使用前在该确切镜像检查 pandas、NumPy 及其依赖版本，并封存检查结果。构建固定基础镜像、pandas 和 NumPy；传递依赖由本次构建解析，后续新构建必须重新记录完整版本及 image ID，不能把相同 tag 当作相同环境。当前 L0 的确切镜像和非 root／禁网／只读导入检查见[本轮 Spec](../../docs/optimization/to_verify/knowledge-decision-delivery.md#98-本轮执行计划与固定配置)。

`PythonExecutionDeploymentConfig` 的 `authorization` 绑定确切主体、对话、绝对到期、额度和该 image ID；`endpoint` 指向本地 Docker Engine。通过 `PERSONAL_AGENT_PYTHON_EXECUTION_CONFIG` 交由正式 Runtime 装配。该文件不包含模型凭据；执行容器只获得模型明确绑定的获准输入和原程序。
