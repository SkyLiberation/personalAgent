"""General Python file execution contract, without task-specific analysis."""

from personal_agent.kernel.prompt_registry import PromptSpec


PROMPTS = {
    "python_execution.description": PromptSpec(
        name="python_execution.description",
        version='v5-artifact-id-inputs-md1',
        owner="python_execution",
        output_contract="ExecutePythonArgs -> PythonToolResult",
        template="""

## 执行方式
执行你提交的Python代码，返回输出和执行状态。每次独立执行，不保留变量；用print输出结果，末尾表达式不自动返回。

## 输入文件
sys.argv[1]是只读输入目录，每个input_files项对应目录下的name；省略input_files表示没有输入文件。复用已有程序时，将原件绑定为输入文件，由代码读取或用runpy.run_path(..., run_name="__main__")运行；sys.argv[1]仍保留输入目录。

## 环境与结果边界
使用固定镜像中的标准库及已安装库，禁网、不可安装依赖。返回实际进程状态、退出码、诊断及程序、输入清单、stdout、stderr原件引用，预览有界，需更多内容时读取原件。未知终态须先核对原执行；成功只表示程序运行，分析方法和后续动作由你判断。""",
    ),
    **{
        f"python_execution.parameter.{name}": PromptSpec(
            name=f"python_execution.parameter.{name}",
            version="v4-artifact-id-inputs",
            owner="python_execution",
            output_contract="ExecutePythonArgs field description",
            template=description,
        )
        for name, description in {
            "code": (
                "本次执行的完整Python源码，按文件运行；用print产生输出。最多128 KiB。"
            ),
            "input_files": (
                "可选的只读输入文件列表，省略默认[]。每项提供name和当前可读文件的resource_id，"
                "代码从sys.argv[1]目录按name读取；不会自动发现文件。最多32项、合计64 MiB。"
            ),
            "input_name": (
                "该Artifact在只读输入目录中的平面文件名，须与代码使用的名字对应。"
                "1—64字符，只含ASCII字母、数字、下划线、连字符和点；"
                "禁止路径、末尾点、大小写重名、Windows设备名及program.py、input_manifest.json。"
            ),
            "input_resource_id": (
                "材料或成功工具结果中resource_ref.resource_id的字符串值。"
                "Runtime恢复完整引用，按原字节只读挂载；不要传完整对象或宿主路径。"
            ),
        }.items()
    },
}
