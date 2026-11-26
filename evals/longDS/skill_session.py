"""Introduce the same upstream Python workflow in the two LongDS entries."""

from pathlib import Path


SKILL_NAME = "longds-bench"
SKILL_ROOT = Path(__file__).resolve().parents[2] / "src/personal_agent/bundled_skills"
SKILL_REVISION = "94f36db517952a18345d08e5faf16be53b4d6c7f"


def first_question(question: str, *, data_directory: str, script_location: str, language: str) -> str:
    if language == "zh":
        return (
            f"请加载 {SKILL_NAME}，按其持久 Python 会话流程分析。每条用户消息只投递当前一轮，"
            "请直接回答本轮问题，并保留任务内核以便后续轮次继续使用。无需运行 Skill 中的题目清单、评分和整题结束步骤。"
            f"数据在 {data_directory}，脚本位置为 {script_location}。连接文件、PID 文件和临时文件请放在 /tmp。"
            "\n\n" + question
        )
    return (
        f"Load {SKILL_NAME} and follow its persistent Python session workflow. Each user message supplies "
        "the current turn. Answer that turn directly and keep its task kernel alive for later turns. "
        "The driver handles the task sequence, scoring, and final cleanup. "
        f"Data is in {data_directory}. Locate the script at {script_location}. "
        "Use /tmp for the connection file, PID file, and writable work.\n\n" + question
    )
