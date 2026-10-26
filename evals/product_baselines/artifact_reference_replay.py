"""完整真实 LongDS 文件引用失败阶段的连续参数回放；不执行生成的工具。"""
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
from personal_agent.capabilities.contracts.model import ModelActionDefinition, StructuredModelRequest, StructuredOutputFailure
from personal_agent.infra.model_capacity import check_model_capacity
from personal_agent.infra.structured_model import OpenAIModelClient, _ProviderCompletion
from personal_agent.kernel.config import Settings

from .longds_materials import json_bytes, seal

SOURCE = Path('.tmp/code-agent-tool-production-20261024/flow')
IDENTITY = 'de86ece1a4324e3faeab6fcbf7148f3a'


def load(path: Path):
    return json.loads(path.read_bytes())


def captured_definitions(wire):
    result = []
    for row in wire['tools']:
        item = row['function']
        name = item['name']
        kind = ('working_plan' if name == 'control_working_plan' else
                'finalize' if name == 'control_prepare_final' else
                'agent' if name.startswith('agent_') else 'tool')
        result.append(ModelActionDefinition(name=name, kind=kind, target_name=name.split('_', 1)[1],
            description=item['description'], input_schema=item['parameters'], strict=item.get('strict', True)))
    return tuple(result)


def run(output: Path, *, group: str, prepared: Path):
    output.mkdir(parents=True, exist_ok=False)
    (output/'runner-source.py').write_bytes(Path(__file__).read_bytes())
    source = SOURCE/'sdk'/f'{IDENTITY}.candidate.request.json'
    wire = load(source)
    definitions = captured_definitions(wire)
    messages = wire['messages']
    if group == 'candidate':
        definitions = tuple(ModelActionDefinition.model_validate(row) for row in load(prepared/'candidate-definitions.json'))
        old = (prepared/'old-file-context.txt').read_text(encoding='utf8')
        new = (prepared/'new-file-context.txt').read_text(encoding='utf8')
        messages = [dict(row) for row in messages]
        if messages[0]['content'].count(old) != 1:
            raise ValueError('完整实际输入的文件协议说明不能唯一定位')
        messages[0]['content'] = messages[0]['content'].replace(old, new)
    trace = InteractionTrace.model_validate_json((prepared/'feedback-trace.json').read_bytes())
    allowed = {ref.resource_id for ref in trace.input_artifact_refs}
    settings = Settings.from_env()
    if (settings.structured.model != wire['model'] or settings.structured.timeout_seconds != 480
            or settings.structured.extra_body != {'thinking': {'type': 'adaptive'}, 'reasoning_effort': 'low'}):
        raise ValueError('原模型、思考或超时配置不同')
    request = StructuredModelRequest(operation='agent_interaction_turn', version=f'artifact-id-{group}',
        messages=messages, output_type=BaseModel, kind='tool_calling', action_definitions=definitions,
        action_choice=wire['tool_choice'], max_tokens=wire['max_completion_tokens'],
        reasoning_effort=wire.get('reasoning_effort'), extra_body=wire.get('extra_body'),
        context_projection_ref=f'offline:longds:artifact-id:{group}')
    started = monotonic()
    reports, failure = [], None

    class MeteredAdapter(OpenAIModelClient):
        calls = known = unknown = 0

        def _create_chat_completion(self, client, operation, kwargs, *, before_send=None) -> _ProviderCompletion:
            capacity = check_model_capacity(operation=operation, provider_host=urlparse(self._config.base_url).hostname,
                model=self._resolved_model, kwargs=kwargs, capacity=self._config.capacity)
            if (self.calls >= 40 or self.unknown or monotonic()-started >= 3600
                    or self.known+capacity.estimated_input_tokens+capacity.output_reserve_tokens+8192 > 3000000):
                raise RuntimeError('HTTP前触发预声明停止线')
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
            if usage is None or any(getattr(usage, key) is None for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')):
                self.unknown += 1
                raise RuntimeError('服务方未提供完整用量')
            self.known += usage.total_tokens
            if any(choice.finish_reason == 'length' for choice in payload.choices):
                raise RuntimeError('响应截断；停止而不进入参数修复')
            return completion

    adapter = MeteredAdapter(settings.structured)
    try:
        kwargs = adapter._chat_kwargs(request)
        if group == 'baseline' and kwargs != wire:
            raise ValueError('baseline 与完整实际 SDK 请求不同')
        (output/'preflight.json').write_bytes(json_bytes({'source':str(source), 'source_sha256':sha256(source.read_bytes()).hexdigest(),
            'group':group, 'planned_journeys':10, 'max_physical_requests':40, 'max_known_tokens':3000000,
            'max_wall_seconds':3600, 'full_messages_retained':True, 'tool_execution':False}))
        (output/'definitions.json').write_bytes(json_bytes([item.model_dump(mode='json') for item in definitions]))
        for index in range(1, 11):
            current, stages, passed = request, [], False
            for attempt in range(2):
                before, error = adapter.calls, None
                try:
                    response = adapter.generate(current)
                except StructuredOutputFailure as exc:
                    if exc.response is None:
                        raise
                    response, error = exc.response, exc
                if error is None:
                    try:
                        decode_model_action_invocations(response.action_invocations, definitions, reveal_invalid_action_field_names=True)
                        passed = True
                    except StructuredOutputFailure as exc:
                        error = exc
                calls = []
                for call in response.action_invocations:
                    row = {'name':call.name, 'arguments':call.arguments}
                    if passed and call.name == 'tool_execute_python':
                        bindings = call.arguments.get('input_files', [])
                        ids = [item.get('resource_id') if group == 'candidate' else item['resource_ref']['resource_id'] for item in bindings]
                        row['all_input_ids_visible'] = all(value in allowed for value in ids)
                        if not row['all_input_ids_visible']:
                            raise ValueError('合法Python参数包含非当前可读文件')
                    calls.append(row)
                stage = {'application_attempt':attempt+1, 'physical_requests':adapter.calls-before,
                    'sdk_retry_attempts':response.retry_attempts, 'passed':passed, 'calls':calls,
                    'reason_code':error.reason_code if error else None, 'field_paths':list(error.field_paths) if error else []}
                stages.append(stage)
                (output/f'journey-{index:02}-attempt-{attempt+1}.json').write_bytes(json_bytes(stage))
                if passed or attempt == 1:
                    break
                feedback = ConversationService._provider_action_feedback(error, response).model_copy(update={'decision_turn':1})
                record = ModelDecisionRecord(turn_index=1, input_start=0, assistant=response.assistant_message,
                    protocol_exchanges=response.protocol_exchanges, blocked_by=input_identity(feedback))
                branch = trace.model_copy(update={'model_decisions':(record,), 'inputs':(feedback,), 'history_compaction':None})
                exchanges, remaining = project_model_history(branch, materialize_citation_context((feedback,)))
                if remaining:
                    raise ValueError('实际参数拒绝未按原生调用配对')
                current = replace(request, model_history=exchanges)
            reports.append({'index':index, 'passed':passed, 'stages':stages})
            (output/'running.json').write_bytes(json_bytes({'completed':len(reports), 'passed':sum(row['passed'] for row in reports),
                'physical_requests':adapter.calls, 'known_tokens':adapter.known, 'unknown_usage_attempts':adapter.unknown}))
            print(f'{group} {index}/10: {passed}; physical={adapter.calls}; tokens={adapter.known}', flush=True)
            if group == 'candidate' and not passed:
                break
    except Exception as error:
        failure = {'type':type(error).__name__, 'message':str(error)}
    finally:
        report = {'evidence_class':'offline_complete_actual_parameter_stage', 'release_eligible':False,
            'group':group, 'planned_journeys':10, 'completed_journeys':len(reports), 'unexecuted_journeys':10-len(reports),
            'passed':sum(row['passed'] for row in reports), 'journeys':reports, 'failure':failure,
            'physical_requests':adapter.calls, 'known_tokens':adapter.known, 'unknown_usage_attempts':adapter.unknown,
            'new_tool_executions':0, 'wall_seconds':monotonic()-started}
        (output/'report.json').write_bytes(json_bytes(report))
        seal(output)
        print(json.dumps({key:value for key,value in report.items() if key != 'journeys'}, ensure_ascii=False), flush=True)
    if failure:
        raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--group', choices=('baseline', 'candidate'), required=True)
    parser.add_argument('--prepared', type=Path, required=True)
    args = parser.parse_args()
    run(args.output, group=args.group, prepared=args.prepared)
