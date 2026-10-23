"""模型可见的检索实验及候选程序执行协议。"""

from personal_agent.kernel.prompt_registry import PromptSpec


PROMPTS = {
    "retrieval_experiment.description": PromptSpec(
        name="retrieval_experiment.description",
        version="v2-result-publication",
        owner="retrieval_experiment",
        output_contract="ExperimentToolArgs -> ExperimentToolResult",
        template="""在本任务许可的离线部署中执行开发实验、冻结确切结果或评测已冻结方案。组合只消费实际结果引用；candidate 消费本任务已保存的 program_ref 及可选 config_ref。返回真实状态、指标摘要和正式产物引用；失败或未知不等于完成。
receipt.result_refs 和 summaries.result_ref 指向业务结果 experiment.json，组合 input_result_refs 和冻结 selected_result_ref 使用这些引用。summary.publication 是该业务结果原件的只读内容，其中 raw_result_ref、rankings_ref、metrics_ref 等指向同次实验的子文件；子文件或已保存程序的存在不代表另一次执行。需要具体配置或正文时按对应引用读取。
候选程序固定以 python -I /inputs/program.py /inputs 启动，argv[1] 是只读输入目录。按 input_result_refs 的顺序提供 rankings_0.json、rankings_1.json 等，每份为 query_id → doc_id → 有限数值分数；queries.json 为 query_id → 原查询文本，corpus_ids.json 为合法文档 ID 数组，传 config_ref 时另有 config.json。仅可用 Python 标准库，禁网且不可安装依赖，输入不含评分标注。
stdout 只输出同型排名 JSON，覆盖全部当前查询，每查询至多本次 retrieve_k 个合法文档，允许空排名；不得附加指标、日志或完成自述。诊断写 stderr。失败回执中的 diagnostic_refs 指向实际执行事实及可用的有界输出，按需读取并结合 limitations 判断；日志不代表有效排名或评分结果。""",
    ),
}
