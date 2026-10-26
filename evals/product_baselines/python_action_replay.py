"""回放 LongDS 完整真实参数阶段；只计协议结果，不执行模型选择的工具。"""
from __future__ import annotations

import argparse
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from time import monotonic
from urllib.parse import urlparse

from pydantic import BaseModel

from personal_agent.application.conversation.citations import materialize_citation_context
from personal_agent.application.conversation.model_actions import decode_model_action_invocations
from personal_agent.application.conversation.model_history import input_identity, project_model_history
from personal_agent.application.conversation.models import InteractionTrace, ModelDecisionRecord
from personal_agent.application.conversation.service import ConversationService
from personal_agent.application.python_execution.models import ExecutePythonArgs
from personal_agent.capabilities.contracts.model import ModelActionDefinition, StructuredModelRequest, StructuredOutputFailure
from personal_agent.infra.model_capacity import check_model_capacity
from personal_agent.infra.structured_model import OpenAIModelClient, _ProviderCompletion
from personal_agent.kernel.config import Settings

from .longds_materials import json_bytes, seal

SOURCE = Path('.tmp/minimax-native-history-e2e-20261023/l2-prefix-17')
IDENTITY = 'ab3f94abe6ca4526b00617aa6cf7305c'


def load(path: Path):
    return json.loads(path.read_bytes())


def captured_definitions(wire):
    definitions = []
    for item in wire['tools']:
        tool = item['function']
        name = tool['name']
        kind = ('working_plan' if name == 'control_working_plan' else
                'finalize' if name == 'control_prepare_final' else
                'agent' if name.startswith('agent_') else 'tool')
        definitions.append(ModelActionDefinition(name=name, kind=kind,
            target_name=name.split('_', 1)[1], description=tool['description'],
            input_schema=tool['parameters']))
    return tuple(definitions)


def run(output: Path, *, group: str, definitions_path: Path | None = None):
    output.mkdir(parents=True, exist_ok=False)
    (output/'runner-source.py').write_bytes(Path(__file__).read_bytes())
    original_file = SOURCE/'sdk'/f'{IDENTITY}.candidate.request.json'
    wire = load(original_file)
    original = captured_definitions(wire)
    definitions = (tuple(ModelActionDefinition.model_validate(row) for row in load(definitions_path))
                   if definitions_path is not None else original)
    messages = wire['messages']
    if group == 'candidate':
        from personal_agent.kernel.prompts import get_prompt
        messages = [dict(row) for row in messages]
        old = '全部原生动作只提交 arguments 对象，所有业务或控制字段均在该对象内；prepare_final 的 arguments 为空对象。'
        template = get_prompt('conversation.action').template
        new = template[template.index('全部原生动作'):template.index('调用名只能')]
        if messages[0]['content'].count(old) != 1:
            raise ValueError('完整真实阶段的原协议指令不能唯一定位')
        messages[0]['content'] = messages[0]['content'].replace(old, new)
    request0 = load(SOURCE/'turn-03.request.json')
    snapshots = sorted((SOURCE/'server-data/interaction_runs'/request0['interaction_run_ref']).glob('*.json'))
    trace = InteractionTrace.model_validate_json(snapshots[-1].read_bytes())
    if trace.accepted_tool_requests:
        raise ValueError('该回放不允许用新类型加载旧已接受请求')
    settings = Settings.from_env()
    if (settings.structured.model != 'MiniMax-M3.1-Flash'
            or settings.structured.extra_body != {'thinking': {'type': 'adaptive'}, 'reasoning_effort': 'low'}
            or settings.structured.timeout_seconds != 480):
            raise ValueError('预声明的模型、low 或超时配置发生变化')
    request = StructuredModelRequest(operation='agent_interaction_turn', version=f'code-agent-parameters-{group}',
        messages=messages, output_type=BaseModel, kind='tool_calling', action_definitions=definitions,
        action_choice=wire['tool_choice'], max_tokens=wire['max_completion_tokens'],
        reasoning_effort=wire.get('reasoning_effort'), extra_body=wire.get('extra_body'),
        context_projection_ref=f'offline:longds:turn3:{group}')
    started = monotonic()
    reports = []
    failure = None

    class MeteredAdapter(OpenAIModelClient):
        calls = 0
        known = 0
        unknown = 0

        def _create_chat_completion(self, client, operation, kwargs, *, before_send=None) -> _ProviderCompletion:
            capacity = check_model_capacity(operation=operation,
                provider_host=urlparse(self._config.base_url).hostname,
                model=self._resolved_model, kwargs=kwargs, capacity=self._config.capacity)
            if (self.calls >= 40 or self.unknown or monotonic()-started >= 21600
                    or self.known+capacity.estimated_input_tokens+capacity.output_reserve_tokens+8192 > 18500000):
                raise RuntimeError('在 HTTP 前触发本组预声明额度停止')
            self.calls += 1
            index = self.calls
            (output/f'call-{index:02}.request.json').write_bytes(json_bytes(kwargs))
            try:
                completion = super()._create_chat_completion(client, operation, kwargs, before_send=before_send)
            except Exception:
                self.unknown += 1
                raise
            payload = completion.payload
            (output/f'call-{index:02}.response.json').write_text(payload.model_dump_json(indent=2), encoding='utf8')
            usage = payload.usage
            if usage is None or any(getattr(usage, key) is None for key in ('prompt_tokens','completion_tokens','total_tokens')):
                self.unknown += 1
                raise RuntimeError('真实服务未返回完整用量')
            self.known += usage.total_tokens
            if any(choice.finish_reason == 'length' for choice in payload.choices):
                raise RuntimeError('真实服务响应截断；停止本组，不进入参数修复')
            return completion

    adapter = MeteredAdapter(settings.structured)
    try:
        kwargs = adapter._chat_kwargs(request)
        if group == 'baseline' and kwargs != wire:
            raise ValueError('baseline 未逐字保持完整实际请求')
        capacity = check_model_capacity(operation=request.operation,
            provider_host=urlparse(settings.structured.base_url).hostname,
            model=settings.structured.model, kwargs=kwargs, capacity=settings.structured.capacity)
        (output/'preflight.json').write_bytes(json_bytes({'source':str(original_file),
            'source_sha256':sha256(original_file.read_bytes()).hexdigest(), 'group':group,
            'planned_journeys':10, 'max_physical_requests':40, 'max_known_tokens':18500000,
            'max_wall_seconds':21600, 'estimated_input_tokens':capacity.estimated_input_tokens,
            'new_tool_executions':0, 'actual_full_stage':True}))
        (output/'definitions.json').write_bytes(json_bytes([x.model_dump(mode='json') for x in definitions]))
        (output/'ready.json').write_bytes(json_bytes({'ready':True, 'group':group}))
        print(f'{group}: full-stage preflight ready', flush=True)
        for index in range(1, 11):
            current = request
            stages = []
            passed = False
            for app_attempt in range(2):
                before = adapter.calls
                error = None
                try:
                    response = adapter.generate(current)
                except StructuredOutputFailure as exc:
                    if exc.response is None:
                        raise
                    response, error = exc.response, exc
                if error is None:
                    try:
                        decode_model_action_invocations(response.action_invocations, definitions,
                                                        reveal_invalid_action_field_names=True)
                        passed = True
                    except StructuredOutputFailure as exc:
                        error = exc
                calls = []
                for item in response.action_invocations:
                    detail = {'name':item.name, 'call_id':item.call_id}
                    if item.name == 'tool_execute_python' and passed:
                        payload = item.arguments if group == 'candidate' else item.arguments['arguments']
                        args = ExecutePythonArgs.model_validate(payload)
                        detail.update(code_chars=len(args.code or ''), inputs=len(args.input_files),
                                      code=args.code, input_files=[x.model_dump(mode='json') for x in args.input_files])
                    calls.append(detail)
                stages.append({'application_attempt':app_attempt+1, 'physical_requests':adapter.calls-before,
                    'sdk_retry_attempts':response.retry_attempts, 'passed':passed, 'calls':calls,
                    'reason_code':error.reason_code if error else None,
                    'field_paths':list(error.field_paths) if error else []})
                (output/f'journey-{index:02}-attempt-{app_attempt+1}.json').write_bytes(json_bytes(stages[-1]))
                if passed or app_attempt == 1:
                    break
                feedback = ConversationService._provider_action_feedback(error, response).model_copy(update={'decision_turn':1})
                record = ModelDecisionRecord(turn_index=1, input_start=0,
                    assistant=response.assistant_message, protocol_exchanges=response.protocol_exchanges,
                    blocked_by=input_identity(feedback))
                branch = trace.model_copy(update={'model_decisions':(record,), 'inputs':(feedback,),
                                                'history_compaction':None})
                exchanges, remaining = project_model_history(branch, materialize_citation_context((feedback,)))
                if remaining:
                    raise ValueError('真实拒绝未成为按原调用 ID 配对的原生 tool 结果')
                current = replace(request, model_history=exchanges)
            reports.append({'index':index, 'passed':passed, 'stages':stages})
            (output/'running.json').write_bytes(json_bytes({'group':group, 'completed':len(reports),
                'passed':sum(row['passed'] for row in reports), 'physical_requests':adapter.calls,
                'known_tokens':adapter.known, 'unknown_usage_attempts':adapter.unknown}))
            print(f'{group} journey {index}/10: {"pass" if passed else "fail"}; calls={adapter.calls}; tokens={adapter.known}', flush=True)
            if group == 'candidate' and not passed:
                break
    except Exception as error:
        failure = {'type':type(error).__name__, 'message':str(error)}
    finally:
        report = {'evidence_class':'offline_complete_actual_parameter_stage', 'group':group,
            'planned_journeys':10, 'completed_journeys':len(reports), 'unexecuted_journeys':10-len(reports),
            'passed':sum(row['passed'] for row in reports), 'journeys':reports, 'failure':failure,
            'physical_requests':adapter.calls, 'known_tokens':adapter.known, 'unknown_usage_attempts':adapter.unknown,
            'new_tool_executions':0, 'release_eligible':False, 'wall_seconds':monotonic()-started}
        (output/'report.json').write_bytes(json_bytes(report))
        seal(output)
        print(json.dumps({k:v for k,v in report.items() if k != 'journeys'}, ensure_ascii=False), flush=True)
    if failure:
        raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--group', choices=('baseline','candidate'), required=True)
    parser.add_argument('--definitions', type=Path)
    args = parser.parse_args()
    if (args.group == 'candidate') != (args.definitions is not None):
        parser.error('候选必须指定正式定义链导出的完整 definitions')
    run(args.output, group=args.group, definitions_path=args.definitions)
