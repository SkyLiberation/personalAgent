# json_object：整数被输出为字符串

核对：2026-11-03。来源：本次用户报告与下列官方资料；未取得本工程该失败的实际请求、原始响应和校验轨迹。本文记录处理方法，不表示已在生产实现或取得 E2E 验收。

## 1. 识别问题与适用条件

**只能使用 `json_object`，且目标是内部字段最终为整数时，可在读取模型输出的边界进行字段级无损转换，再执行严格校验。**

识别信号：字段声明为整数，模型却返回数字字符串，本地严格整数校验拒绝。下例仅说明失败形状，不是归档的原始响应：

```json
{"count": "3"}
```

`json_object` 约束 JSON 格式，不保证字段满足 Schema；上例与 `{"count": 3}` 都是合法 JSON。因此，不能由类型声明或 Prompt 推定服务方保证整数类型。无法使用 Structured Outputs 时，官方建议在应用侧校验并按需重试。[OpenAI 官方说明](https://developers.openai.com/api/docs/guides/structured-outputs#json-mode)

采用转换前确认三个条件：字段表达数值而非保留原貌的编号；读取契约明确接受整数及指定的十进制整数字符串；原始输出的 JSON 类型本身不是验收目标。若契约要求原始输出必须为整数，保留严格拒绝与反馈重试，不把转换后的对象算作模型原始输出合规。

## 2. 处理方法：字段级无损转换后严格校验

先核对实际出站模式、原始字段类型、本地校验配置和字段的真实消费者，确认首次失败发生在表示读取，而非模型选错数量。

在现有模型输出读取边界，对已明确允许的整数位执行转换：只接受约定的十进制整数写法，不经过浮点数、不截断、不补单位、不猜缺值；随后严格校验类型、范围、枚举及适用的跨字段条件。内部字段保持 `int`，保留原始响应以便追溯此次表示转换。

下面给出一项明确的输入策略：整数字符串采用 `-?(0|[1-9][0-9]*)`；示例中的 `count` 表示非负数量，其范围仍由字段业务契约决定。

| 原始值 | 该示例的处理结果 |
| --- | --- |
| `3`、`"3"`、`"0"` | 接受，内部为整数 |
| `"03"`、`" 3 "`、`"+3"` | 不符合约定写法，拒绝 |
| `"3.0"`、`"3.2"`、`"3个"`、`"三"` | 拒绝，不推断或截断 |
| `3.0`、`true`、`null`、字段缺失 | 严格校验拒绝，不转成数量或补默认值 |
| `-1`、`"-1"` | 非负范围校验拒绝，不自动改成 `0` |

Pydantic 的普通 `int` 默认可以解析数字字符串，但宽松转换还接受布尔值及部分浮点数。要只开放上述写法，可使用字段前置校验器完成解析，再保持严格整数校验；前置校验器返回的值仍会接受后续类型检查。[严格模式](https://docs.pydantic.dev/latest/concepts/strict_mode/)、[转换规则](https://docs.pydantic.dev/latest/concepts/conversion_table/)、[前置校验器](https://docs.pydantic.dev/latest/concepts/validators/#field-validators)

以下为 Pydantic v2 的说明示例，不是本工程已落地的生产实现：

```python
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DecisionOutput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    count: int = Field(ge=0)

    @field_validator("count", mode="before")
    @classmethod
    def parse_count(cls, value: object) -> object:
        if isinstance(value, str) and re.fullmatch(r"-?(0|[1-9][0-9]*)", value):
            return int(value)
        return value


decision = DecisionOutput.model_validate_json('{"count": "3"}')
```

转换规则由字段读取契约拥有，放在形成有效内部决定之前；已经形成的提议继续按原准入规则接受或拒绝。Admission 不承担修复业务载荷的职责，不在消费方散落强制转换，也不新增递归遍历整个 JSON 的数字修复器。只给确有需要的字段开放该规则，编号、引用与版本等字符串不因外观像数字而转换。

不符合读取规则或业务约束时，沿现有协议反馈具体字段、实际值、期望类型与范围，并执行既有有界恢复；不能用默认值或默认成功掩盖失败。转换不会纠正模型选错的数值，也不能证明整体决策正确。

## 3. 工程采用与验证边界

本文的方法也适用于本地严格校验前的原生工具参数读取，但前提仍是字段契约显式允许。Toolathlon 的采用位置和真实轨迹由[主循环读取契约](../context/runtime-feedback.md#显式允许的整数表示)维护。生产采用前，需取得原失败调用的实际请求、原始输出与首个校验错误，确认真实消费者及当前读取契约；先更新唯一设计中允许的外部表示、转换责任和失败行为，再实施。若现行协议只接受原生整数，不能绕过它直接放宽校验。

后续验收消费真实阶段产物，核对原失败字符串能否无损读为整数、原整数是否保持，以及上表拒绝输入是否仍被拒绝；同时确认后续业务实际消费的是整数，数值错误没有被表示转换遮蔽。用户结果与适用证据仍按[变更证据要求](../devSpec/change-evidence.md#12-按实际影响选择证据)验收，不把官方资料或本文示例算作本工程运行证据。

本文的归纳依据为服务方格式保证、本地解析规则及用户确认采用的处理方向；尚无本工程该用例的成功率、延迟、成本或 E2E 改善结论。排障入口见 [LLM 决策排障 skill](../../.agents/skills/troubleshoot-llm-decisions/SKILL.md)。
