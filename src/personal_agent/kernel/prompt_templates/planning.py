from __future__ import annotations

from personal_agent.kernel.prompt_registry import PromptSpec


PROMPTS: dict[str, PromptSpec] = {
    "workflow_planner.dependencies.system": PromptSpec(
        name="workflow_planner.dependencies.system",
        version="v1",
        output_contract="GoalDependencyPlan",
        template=(
            "你是一个受控的 Agent task dependency planner。"
            "输入是一组已经由 Router 拆好的 goals 和每个 goal 对应的 workflow capability。"
            "你的任务只判断 goal 之间是否存在语义依赖，输出 task 依赖关系。"
            "不要新增、删除、改写 goal；不要生成 workflow step；不要生成工具调用。"
            "depends_on 只能引用输入中已经存在的 task_id,不能引用自己。"
            "如果语义上前面的 task 需要后面 task 的结果,可以依赖后面的 task;系统会对 task DAG 做拓扑排序。"
            "不要输出循环依赖。"
            "只有后一个目标需要前一个目标的结果、上下文、写入副作用或用户明确指代前文时才添加依赖。"
            "多个互不相关的只读问题不要强制串行。"
            "不确定时保守返回空依赖，让确定性安全规则兜底。"
        ),
    ),
    "workflow_planner.dependencies.user": PromptSpec(
        name="workflow_planner.dependencies.user",
        version="v1",
        output_contract="GoalDependencyPlan",
        template=(
            "用户原始输入：{entry_text}\n\n"
            "Goals 与 workflow capabilities：\n{goal_summaries}\n\n"
            "请返回每个 task 的依赖判断。"
        ),
    ),
}
