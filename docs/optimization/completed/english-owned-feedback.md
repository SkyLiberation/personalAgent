# 英文工程提示与动态反馈

**已按预声明用例补齐当前生产可达清单中的英文工程指令和反馈，并通过真实读取回放与英文正式入口验证。** 关闭的是语言覆盖缺口；task2 完整正确性、工具参数兼容和 Graphiti 输出模式分别判断，不由本次通过代替。

## 问题与采用方案

原英文 Catalog 覆盖模板和 Schema 元数据，却遗漏了 `read_artifact` 的中文默认说明，以及部分内联生成指令、工具错误、参数校验、核验拒绝和恢复反馈。真实 task2 请求已证明这些文字会进入模型；只扫描首个 system 或模板目录不能证明全部动态输入已本地化。

继续使用原有实例 `PromptCatalog` 和具名版本化双语资源。工程说明由实际产生它的 Application、工具或 Adapter 选择语言；纯协作者显式接收 Catalog，类级 Pydantic 校验通过既有 `ValidationInfo.context` 接收同一 typed 实例。默认中文保持，不增加全局语言状态、机器翻译或递归 payload 转换。

Runtime 继续拥有权限、执行、预算和恢复事实；语言资源不改变 Schema、错误分类、校验条件、重试或完成判断。原用户、来源、历史、代码、程序输出及已保存业务文字保持原样。Capture 在构造时选择或接收 Catalog，并注入自己创建的默认 URL provider，不由 Runtime 事后修改已有依赖。

源版本、变量及注册规则由 [Prompt 规范](../../../src/personal_agent/kernel/prompt_templates/AGENTS.md)拥有；当前装配由[架构正文](../../architecture/cross-cutting.md#2-模型调用的实际组合)拥有。采用的是既有显式语言资源机制，外部源码与本工程适用边界见[整体语言规格](../to_verify/prompt-language-selection.md#4-外部依据与采用范围)。

## 已验证范围与接入

预声明的 `LANG-OWNED-1/2/3` 覆盖原轨迹完整读取阶段、现行可达清单、当前实际构造与全部资源调用；`LANG-ENTRY-1` 从正式 Web 入口提出英文原 CSV 前两行／列名请求，经 MiMo Flash thinking enabled 和生产工具取得正确答案，实际调用 `read_artifact`，SDK 中工程提示为英文。仍为 direct/none 的局部用户结果，不是完整发布证据。

原有中文资源、被迁移文字的中文构造、机器 Schema、源文、坐标和续读事实的对照通过。独立审查发现并修正了 Catalog 模板变量冲突、公开 get_note／Capture413 遗漏及结构化输出校验反馈遗漏。模板、实际实参绑定和真实消费边界分别检查；静态检查不冒充模型理解或业务正确性。

决定性证据和实际费用统一由[验证记录](../to_verify/verify_results/prompt-language-mimo.md#英文动态提示与反馈补齐)拥有。先行规格封存在 `.tmp/english-completion-20261027/approved-spec.md`，代码与真实入口原件在 `.tmp/ec27/`，未覆盖写旧封存。

## 失败尝试与保留边界

早期仅翻译模板与工具元数据，遗漏了默认值和动态工具返回；已用生产者／消费者清单和全请求审计替代该覆盖主张。一次静态对照只渲染 PromptSpec，未检查 Catalog 方法参数绑定，漏掉模板变量 `name` 的冲突；已采用职责明确的变量名并核对真实调用实参，没有改 Catalog API 掩盖问题。

完整 task2 的两次原始失败继续保留。最新参数错误请求没有中文，且模型记录已经识别对象要求；不能用本次语言补齐宣称参数恢复成功。MiMo Schema 方言与 Graphiti 输出模式的独立缺口见验证记录，本次没有放宽准入或静默修正错误参数。

后续新的真实 E2E 或其完整真实阶段输入再次出现同类工程提示漏译时，按 EVD 重开本问题并加入该真实用例。用户、来源和既有业务材料含中文本身不是重开条件；新职责或新增 Schema 的语言资源继续遵守 Prompt 规范。
