"""Replay complete sealed stages through verification and main-context projections."""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

from pydantic import BaseModel, ValidationError

from personal_agent.application.conversation.citations import materialize_citation_context, render_citable_input
from personal_agent.application.conversation.context_materialization import materialize_interaction_inputs
from personal_agent.application.conversation.model_history import prior_analysis_turns, project_conversation_history
from personal_agent.application.conversation.goal_maintenance import current_analysis_goal
from personal_agent.application.conversation.models import ActionObservation, InteractionTrace, SubmittedFinal
from personal_agent.application.conversation.verification_admission import (
    INTERACTION_VERIFICATION_CAPABILITY, observed_receipts,
)
from personal_agent.application.conversation.verification_context import build_verification_context
from personal_agent.capabilities.contracts.model import (
    ModelActionDefinition, ModelRuntimeFeedback, StructuredModelRequest, sealed_context_projection_ref,
)
from personal_agent.capabilities.contracts.verification_prompt import task_verification_criteria, verification_messages
from personal_agent.infra.structured_model import OpenAIModelClient
from personal_agent.kernel.config import Settings
from personal_agent.kernel.contracts.derivation import canonical_digest
from personal_agent.kernel.prompts import create_prompt_catalog

from .longds_materials import json_bytes, seal, verify_seal


def load(path):
    return json.loads(path.read_bytes())


def request_at(source, trace, record):
    return load(source / 'server-data/interaction_runs' / trace.interaction_run_ref
                / 'model_invocations' / record.invocation_id / 'request.json')


def verification_stage(trace, index, previous, prompts, *, historical: bool):
    record = trace.model_decisions[index]
    main = next(item for item in reversed(trace.model_decisions[:index]) if item.turn_index is not None)
    matches = []
    for observation in trace.inputs[record.input_start:]:
        receipts = observed_receipts((observation,), capability_names=frozenset({INTERACTION_VERIFICATION_CAPABILITY}))
        if not receipts:
            continue
        receipt = receipts[0]
        if record.operation != f'interaction_{receipt.checked_kind}_verification':
            continue
        goal = receipt.checked_kind == 'goal'
        call_id = observation.action_id.rsplit(':', 1)[-1] if goal else None
        if goal and (main.assistant is None or call_id not in main.assistant.call_ids):
            continue
        prefix = trace.model_copy(update={
            'inputs': trace.inputs[:record.input_start], 'final_message': None,
            'model_decisions': trace.model_decisions[:index + 1],
            'usage': trace.usage.model_copy(update={'model_turns': main.turn_index}),
            'goal_operations': tuple(op for op in trace.goal_operations
                if op.decision_turn < main.turn_index or (not goal and op.decision_turn == main.turn_index)),
        })
        if not goal:
            pending = next((item for item in reversed(prefix.inputs) if isinstance(item, SubmittedFinal)), None)
            if pending is None or pending.final.message != receipt.verified_draft:
                continue
        context = build_verification_context(trace=prefix, history=previous,
            draft=receipt.verified_draft, kind=receipt.checked_kind,
            goal_call_id=call_id)
        criteria = task_verification_criteria(receipt.checked_kind, prompts=prompts)
        arguments = {'draft': receipt.verified_draft,
            'success_criteria': [item.criterion for item in criteria], 'task_context': context.model_dump(mode='json')}
        if historical:
            # Reconstruct only the old serialized shape to bind the immutable source call.
            # The new model input still uses the complete current typed context below.
            for turn in arguments['task_context']['turns']:
                for event in turn['events']:
                    event.pop('verified_goal', None)
            old_goal = current_analysis_goal(prefix, previous)
            arguments['task_context']['active_goal'] = old_goal.goal.objective if old_goal else None
        if observation.execution_request_digest == canonical_digest({
                'tool_name': INTERACTION_VERIFICATION_CAPABILITY, 'arguments': arguments}):
            matches.append(context)
    if len(matches) != 1:
        raise ValueError(f'Actual verification stage has {len(matches)} matching canonical submissions')
    return matches[0]


def check_verification(context, prompts):
    original = context.model_dump_json()
    messages = verification_messages(context, task_verification_criteria(context.kind, prompts=prompts), prompts=prompts)
    position, passed, failed = 1, 0, 0
    for turn in context.turns:
        assert messages[position] == {'role': 'user', 'content': prompts.render(
            'interaction_verification.history.user_turn', number=turn.user_turn, question=turn.question)}
        position += 1
        if context.kind == 'goal' and turn is context.turns[-1]:
            assert messages[position]['role'] == 'system'
            assert (context.active_goal or prompts.get('interaction_verification.history.no_goal').template) in messages[position]['content']
            position += 1
        if turn.summary is not None:
            assert turn.summary in messages[position]['content']
            position += 1
        shown_goal = None
        for event in turn.events:
            if context.kind == 'answer' and event.verified_goal is not None:
                goal = event.verified_goal
                if goal.receipt_id != shown_goal:
                    goal_message = messages[position]
                    assert goal_message['role'] == 'system' and goal.verified_draft in goal_message['content']
                    assert goal.receipt_id in goal_message['content'] and goal.draft_digest in goal_message['content']
                    shown_goal = goal.receipt_id
                    position += 1
            submission = messages[position]
            assert submission['role'] == 'user' and event.content in submission['content']
            assert event.submission_id in submission['content']
            if event.verified_goal is not None:
                assert event.verified_goal.receipt_id in submission['content']
            position += 1
            if event.verdict is None:
                continue
            judgment = messages[position]
            assert judgment['role'] == 'system' and event.submission_id in judgment['content']
            receipt = event.verdict
            if receipt.verdict == 'passed':
                passed += 1
                assert receipt.receipt_id in judgment['content'] and receipt.draft_digest in judgment['content']
                assert 'criterion_results' not in judgment['content'] and 'verified_draft' not in judgment['content']
            else:
                failed += 1
                expected = receipt.model_dump_json(include={'verdict', 'criterion_results', 'revision_feedback'})
                assert expected in judgment['content']
            position += 1
    assert position == len(messages) and messages[-1]['role'] == 'user'
    assert original == context.model_dump_json()
    if context.kind == 'answer' and context.turns[-1].events[-1].disposition == 'answer':
        invalid = context.model_dump(mode='json')
        invalid['turns'][-1]['events'][-1]['verified_goal'] = None
        try:
            type(context).model_validate(invalid)
        except ValidationError:
            pass
        else:
            raise AssertionError('Current normal answer accepted without its verified goal')
    return messages, passed, failed


def check_goal_bindings(context, sources):
    """Compare projected snapshots with source operation facts at each real submission."""
    references = []
    if context.kind != 'answer':
        return references
    for turn, trace in zip(context.turns, sources, strict=True):
        for event in turn.events:
            locations = [i for i, item in enumerate(trace.inputs) if isinstance(item, SubmittedFinal)
                         and f'{trace.interaction_run_ref}:{item.action_id}' == event.submission_id]
            if not locations:
                assert event.submission_id.endswith(':delivered')
                main_turn = trace.usage.model_turns
            else:
                assert len(locations) == 1
                main_turn = max(record.turn_index for record in trace.model_decisions
                    if record.turn_index is not None and record.input_start <= locations[0])
            operations = [op for op in trace.goal_operations
                          if op.operation != 'read' and op.decision_turn <= main_turn]
            if not operations:
                assert event.verified_goal is None
                continue
            operation = operations[-1]
            assert operation.verification_ref is not None
            observed = tuple(item for item in trace.inputs if isinstance(item, ActionObservation)
                             and item.action_id == operation.verification_ref.action_id)
            expected = observed_receipts(observed, capability_names=frozenset({INTERACTION_VERIFICATION_CAPABILITY}))[0]
            assert event.verified_goal == expected
            assert expected.verified_draft == operation.goal.objective
            references.append({'user_turn': turn.user_turn, 'submission_id': event.submission_id,
                               'goal_revision': operation.goal_ref.revision, 'goal_receipt_id': expected.receipt_id})
    return references


def check_main(source, trace, index, previous, prompts, adapter):
    record = trace.model_decisions[index]
    original = request_at(source, trace, record)
    prefix = trace.model_copy(update={'inputs': trace.inputs[:record.input_start],
        'model_decisions': trace.model_decisions[:index], 'final_message': None,
        'goal_operations': tuple(op for op in trace.goal_operations if op.decision_turn < record.turn_index)})
    before = prefix.model_dump_json()
    ancestors = prior_analysis_turns(prefix, previous)
    latest = next((i for i in range(len(prefix.inputs) - 1, -1, -1)
                   if isinstance(prefix.inputs[i], SubmittedFinal)), None)
    inputs = tuple(item for i, item in enumerate(prefix.inputs) if not isinstance(item, SubmittedFinal) or i == latest)
    visible = materialize_citation_context(materialize_interaction_inputs(inputs))
    history, remaining = project_conversation_history(prefix, ancestors, visible, prompts=prompts)
    messages = [dict(item) for item in original['messages']]
    execution = next((i for i, item in enumerate(messages)
                      if (item.get('content') or '').startswith('## 执行输入')), None)
    if execution is not None:
        messages[execution]['content'] = prompts.render('conversation.execution_inputs',
            inputs_json='\n\n'.join(render_citable_input(item, prompts=prompts) for item in remaining))
    elif remaining:
        raise ValueError('Actual request omitted execution materials')
    request = StructuredModelRequest(operation=original['operation'], version=prompts.get('conversation.action').version,
        messages=messages, model_history=history, output_type=BaseModel, kind=original['kind'],
        action_definitions=tuple(ModelActionDefinition.model_validate(item) for item in original['action_definitions']),
        action_choice=original['action_choice'], max_tokens=original['max_tokens'], temperature=original['temperature'],
        reasoning_effort=original['reasoning_effort'], extra_body=original['extra_body'],
        context_projection_ref=sealed_context_projection_ref(purpose='actual_verification_presentation',
            messages=messages, model_history=history))
    wire = adapter._chat_kwargs(request)
    expected = [item for run in (*ancestors, prefix) for item in run.inputs
                if isinstance(item, ActionObservation) and item.capability_id == INTERACTION_VERIFICATION_CAPABILITY]
    actual = []
    for message in wire['messages']:
        if message['role'] not in {'system', 'tool'}:
            continue
        try:
            observation = json.loads(message.get('content') or '').get('observation', {})
        except (ValueError, AttributeError):
            continue
        if observation.get('capability_id') == INTERACTION_VERIFICATION_CAPABILITY:
            actual.append(observation)
    assert Counter(item.action_id for item in expected) == Counter(item['action_id'] for item in actual)
    for item, projected in zip(expected, actual, strict=True):
        receipt = observed_receipts((item,), capability_names=frozenset({INTERACTION_VERIFICATION_CAPABILITY}))[0]
        if receipt.verdict == 'passed':
            assert projected['payload']['data'] == receipt.model_dump(mode='json',
                include={'checked_kind', 'verdict', 'receipt_id', 'draft_digest'})
            assert projected['status'] == item.status and not projected.get('payload', {}).get('verified_draft')
        else:
            assert projected['payload'] == item.payload
    for exchange in history:
        if not isinstance(exchange, ModelRuntimeFeedback):
            assert set(exchange.assistant.call_ids) == {result.call_id for result in exchange.results}
    assert before == prefix.model_dump_json()
    return wire


def replay(source: Path, output: Path, user_turns: int, expect_current_wire: bool = False,
           verification_only_turn: int | None = None):
    verify_seal(source)
    output.mkdir(parents=True, exist_ok=False)
    (output / 'runner.py').write_bytes(Path(__file__).read_bytes())
    hashes = {str(path): sha256(path.read_bytes()).hexdigest() for path in Path('src/personal_agent').rglob('*.py')}
    (output / 'source-hashes.json').write_bytes(json_bytes(hashes))
    stages, previous = [], []
    adapter = OpenAIModelClient(Settings.from_env().openai)
    catalogs = {language: create_prompt_catalog(language) for language in ('zh', 'en')}
    try:
        for number, file in enumerate(sorted(source.glob('turn-*.trace.json'))[:user_turns], 1):
            trace = InteractionTrace.model_validate_json(file.read_bytes())
            if verification_only_turn is not None and number != verification_only_turn:
                previous.append(trace)
                continue
            if trace.verification_history_compactions or (trace.history_compaction is not None and verification_only_turn is None):
                raise ValueError('This fixed case consumes complete uncompressed stages only')
            for index, record in enumerate(trace.model_decisions):
                operation = record.operation
                if operation not in {'agent_interaction_turn', 'interaction_goal_verification', 'interaction_answer_verification'}:
                    continue
                if operation == 'agent_interaction_turn' and record.turn_index is None:
                    continue
                if operation == 'agent_interaction_turn' and verification_only_turn is not None:
                    continue
                context = (verification_stage(trace, index, tuple(previous), catalogs['zh'], historical=not expect_current_wire)
                           if operation != 'agent_interaction_turn' else None)
                for language, prompts in catalogs.items():
                    row = {'user_turn': len(previous) + 1, 'operation': operation,
                           'invocation_id': record.invocation_id, 'language': language}
                    if context is not None:
                        messages, passed, failed = check_verification(context, prompts)
                        row.update(passed_history=passed, failed_history=failed)
                        row['goal_bindings'] = check_goal_bindings(context, (*previous, trace))
                        original = request_at(source, trace, record)
                        if expect_current_wire and language == 'zh':
                            assert messages == original['messages']
                        value = {'messages': messages}
                    else:
                        value = check_main(source, trace, index, tuple(previous), prompts, adapter)
                    (output / f'{file.stem}-{record.invocation_id}-{language}.json').write_bytes(json_bytes(value))
                    stages.append(row)
            previous.append(trace)
        assert len(previous) == user_turns and stages
        report = {'evidence_class': 'offline_complete_actual_stage_projection', 'source': str(source),
                  'user_turns': user_turns, 'passed_stages': len(stages), 'stages': stages,
                  'new_model_calls': 0, 'canonical_facts_unchanged': True}
        (output / 'report.json').write_bytes(json_bytes(report))
        print(f'完整真实阶段投影 {len(stages)}/{len(stages)}；用户轮次 {user_turns}；新增模型调用 0')
    except Exception as error:
        (output / 'failure.json').write_bytes(json_bytes({'type': type(error).__name__, 'message': str(error)}))
        raise
    finally:
        seal(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--user-turns', type=int, default=3)
    parser.add_argument('--expect-current-wire', action='store_true')
    parser.add_argument('--verification-only-turn', type=int)
    args = parser.parse_args()
    replay(args.source, args.output, args.user_turns, args.expect_current_wire, args.verification_only_turn)
