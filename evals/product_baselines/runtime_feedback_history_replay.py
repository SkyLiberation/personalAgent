"""Replay sealed conversation stages through the real history and SDK projections."""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

from pydantic import BaseModel

from personal_agent.application.conversation.citations import CitableInput, materialize_citation_context, render_citable_input
from personal_agent.application.conversation.context_materialization import materialize_interaction_inputs
from personal_agent.application.conversation.model_history import prior_analysis_turns, project_conversation_history
from personal_agent.application.conversation.models import ActionObservation, InteractionTrace, SubmittedFinal
from personal_agent.application.conversation.verification_admission import INTERACTION_VERIFICATION_CAPABILITY
from personal_agent.application.conversation.verification_admission import observed_receipts
from personal_agent.capabilities.contracts.model import (
    ModelActionDefinition, StructuredModelRequest, sealed_context_projection_ref,
)
from personal_agent.infra.structured_model import OpenAIModelClient
from personal_agent.kernel.config import Settings
from personal_agent.kernel.prompts import create_prompt_catalog

from .longds_materials import json_bytes, seal, verify_seal


def load(path: Path):
    return json.loads(path.read_bytes())


def replay(source: Path, output: Path) -> None:
    verify_seal(source)
    output.mkdir(parents=True, exist_ok=False)
    (output / 'replay-source.py').write_bytes(Path(__file__).read_bytes())
    hashes = {str(path): sha256(path.read_bytes()).hexdigest()
              for path in Path('src/personal_agent').rglob('*.py')}
    hashes[str(Path(__file__))] = sha256(Path(__file__).read_bytes()).hexdigest()
    (output / 'source-hashes.json').write_bytes(json_bytes(hashes))
    prompts = create_prompt_catalog('zh')
    create_prompt_catalog('en')
    adapter = OpenAIModelClient(Settings.from_env().structured)
    previous, stages = [], []
    try:
        for file in sorted(source.glob('turn-*.trace.json')):
            original_trace = load(file)
            legacy_checkpoint = original_trace.get('history_compaction')
            if legacy_checkpoint is not None and 'sources' not in legacy_checkpoint:
                # Historical derived views belong to the sealed old implementation.
                # Replay the canonical facts; never silently accept the old checkpoint in production.
                original_trace['history_compaction'] = None
            trace = InteractionTrace.model_validate(original_trace)
            if trace.history_compaction is not None:
                raise ValueError('本用例只接收未激活当前压缩视图的完整阶段')
            for index, decision in enumerate(trace.model_decisions):
                if decision.operation != 'agent_interaction_turn' or decision.turn_index is None:
                    continue
                original = load(source / 'server-data/interaction_runs' / trace.interaction_run_ref
                                / 'model_invocations' / decision.invocation_id / 'request.json')
                prefix = trace.model_copy(update={
                    'inputs': trace.inputs[:decision.input_start],
                    'model_decisions': trace.model_decisions[:index],
                    'goal_operations': tuple(op for op in trace.goal_operations
                                             if op.decision_turn < decision.turn_index),
                    'final_message': None,
                })
                ancestors = prior_analysis_turns(prefix, previous)
                last_submission = next((i for i in range(len(prefix.inputs) - 1, -1, -1)
                                        if isinstance(prefix.inputs[i], SubmittedFinal)), None)
                decision_inputs = tuple(item for i, item in enumerate(prefix.inputs)
                                        if not isinstance(item, SubmittedFinal) or i == last_submission)
                visible = materialize_citation_context(materialize_interaction_inputs(decision_inputs))
                history, remaining = project_conversation_history(prefix, ancestors, visible, prompts=prompts)
                messages = [dict(message) for message in original['messages']]
                execution = next((i for i, message in enumerate(messages)
                                  if (message.get('content') or '').startswith('## 执行输入')), None)
                if execution is not None:
                    messages[execution]['content'] = prompts.render('conversation.execution_inputs',
                        inputs_json='\n\n'.join(render_citable_input(item, prompts=prompts) for item in remaining))
                elif remaining:
                    raise ValueError('真实请求缺少必要执行材料区')
                request = StructuredModelRequest(operation=original['operation'],
                    version=prompts.get('conversation.action').version, messages=messages,
                    output_type=BaseModel, kind=original['kind'], model_history=history,
                    action_definitions=tuple(ModelActionDefinition.model_validate(item)
                                             for item in original['action_definitions']),
                    action_choice=original['action_choice'], max_tokens=original['max_tokens'],
                    temperature=original['temperature'], reasoning_effort=original['reasoning_effort'],
                    extra_body=original['extra_body'],
                    context_projection_ref=sealed_context_projection_ref(purpose='actual_feedback_history',
                        messages=messages, model_history=history))
                wire = adapter._chat_kwargs(request)
                locations, assistant_positions = [], []
                for position, message in enumerate(wire['messages']):
                    if message['role'] == 'assistant':
                        assistant_positions.append(position)
                    if message['role'] in {'system', 'tool'}:
                        content = message.get('content') or ''
                        try:
                            value = json.loads(content)
                        except ValueError:
                            continue
                        observation = value.get('observation', {}) if isinstance(value, dict) else {}
                        if observation.get('capability_id') == INTERACTION_VERIFICATION_CAPABILITY:
                            locations.append((observation['action_id'], position, observation))
                expected = []
                originals = []
                for run in (*ancestors, prefix):
                    for record in run.model_decisions:
                        if record.turn_index is not None and record.consumed and record.assistant is not None:
                            originals.extend(exchange.assistant.payload for exchange in record.protocol_exchanges)
                            originals.append(record.assistant.payload)
                    expected.extend(item for item in run.inputs if isinstance(item, ActionObservation)
                                    and item.capability_id == INTERACTION_VERIFICATION_CAPABILITY)
                actual_assistants = [wire['messages'][i] for i in assistant_positions]
                # Original user-facing answers are also in messages, between user turns.
                cursor = 0
                for assistant in originals:
                    cursor = next(i for i in range(cursor, len(actual_assistants))
                                  if actual_assistants[i] == assistant) + 1
                if Counter(item.action_id for item in expected) != Counter(item[0] for item in locations):
                    raise ValueError('核验回执缺失、重复或出现未来回执')
                for item, (_, position, projected) in zip(expected, locations, strict=True):
                    rendered = load_rendered_observation(item, prompts)
                    if projected != rendered:
                        raise ValueError('回执原文投影发生改写')
                    if position == 0 or wire['messages'][position - 1]['role'] not in {'assistant', 'tool'}:
                        raise ValueError('判决没有紧接真实决定或对应工具结果')
                    receipt, = observed_receipts((item,),
                        capability_names=frozenset({INTERACTION_VERIFICATION_CAPABILITY}))
                    caller = wire['messages'][max(i for i in assistant_positions if i < position)]
                    calls = caller.get('tool_calls') or []
                    if calls:
                        arguments = [json.loads(call['function']['arguments']) for call in calls]
                        drafts = [args.get('objective', args.get('message')) for args in arguments]
                        # retain_goal returns the existing objective in its real tool result.
                        if any(call['function']['name'] == 'retain_goal' for call in calls):
                            drafts.extend(op.goal.objective for run in (*ancestors, prefix)
                                          for op in run.goal_operations
                                          if op.call_id in {call['id'] for call in calls})
                    else:
                        drafts = [caller.get('content')]
                    if receipt.verified_draft not in drafts:
                        raise ValueError('核验反馈被绑定到其他目标或回答')
                for exchange in history:
                    ids = exchange.assistant.call_ids
                    if ids != tuple(result.call_id for result in exchange.results):
                        raise ValueError('原始工具调用与结果配对失效')
                if any(isinstance(item.observation, ActionObservation)
                       and item.observation.capability_id == INTERACTION_VERIFICATION_CAPABILITY
                       for item in remaining):
                    raise ValueError('已结束核验仍被散放在集中材料区')
                target = output / f'{file.stem}-main-{decision.turn_index:02}.request.json'
                target.write_bytes(json_bytes(wire))
                stages.append({'user_turn': len(previous) + 1, 'main_turn': decision.turn_index,
                    'original_invocation_id': decision.invocation_id, 'verifications': len(expected),
                    'runtime_feedback_messages': sum(len(item.runtime_feedback) for item in history),
                    'complete_history': True, 'chronological_feedback': True,
                    'original_assistants_preserved': True, 'tool_pairing': True})
            previous.append(trace)
        if not stages:
            raise ValueError('没有真实主决策阶段')
        report = {'evidence_class': 'offline_actual_history_projection', 'stages': stages,
            'passed_stages': len(stages), 'source': str(source), 'new_model_calls': 0,
            'new_tool_executions': 0, 'semantic_convergence_verified': False,
            'limitations': ['仅验收真实阶段历史保留与SDK序列化，未调用模型或摘要，不是新产品E2E。']}
        (output / 'report.json').write_bytes(json_bytes(report))
        print(f'真实历史阶段 {len(stages)}/{len(stages)}；新增模型调用 0')
    except Exception as error:
        (output / 'failure.json').write_bytes(json_bytes({'type': type(error).__name__, 'message': str(error)}))
        raise
    finally:
        seal(output)


def load_rendered_observation(item, prompts):
    return json.loads(render_citable_input(CitableInput(observation=item), prompts=prompts))['observation']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    replay(args.source, args.output)
