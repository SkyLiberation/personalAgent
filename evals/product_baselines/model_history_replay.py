"""Offline native-history projection of the five complete failed MiniMax stages."""
from __future__ import annotations

import argparse
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

from openai.types.chat import ChatCompletion
from pydantic import BaseModel, ValidationError

from personal_agent.application.conversation.citations import CitableInput
from personal_agent.application.conversation.history_compaction import HistoryCompactor
from personal_agent.application.conversation.journal import FileInteractionJournal
from personal_agent.application.conversation.model_history import (
    decision_input_indices, input_identity, project_model_history,
)
from personal_agent.application.conversation.models import DecisionFeedback, InteractionTrace, ModelDecisionRecord
from personal_agent.capabilities.contracts.model import ModelActionDefinition, ModelCapacityRefused, ModelToolExchange, StructuredModelRequest
from personal_agent.infra.structured_model import OpenAIModelClient
from personal_agent.infra.model_capacity import check_model_capacity
from personal_agent.kernel.config import Settings

from .longds_materials import json_bytes, seal


SOURCE = Path('.tmp/minimax-longds-e2e-20261023/l2-prefix-17')


def load(path: Path):
    return json.loads(path.read_bytes())


def materialize_stage(adapter, original, trace):
    messages = [dict(item) for item in original['messages']]
    content = messages[-1]['content']
    values, _ = json.JSONDecoder().raw_decode(content[len('Typed execution inputs:\n'):])
    visible = tuple(CitableInput.model_validate(item) for item in values)
    history, remaining = project_model_history(trace, visible)
    messages[-1]['content'] = 'Typed execution inputs:\n' + json.dumps(
        [item.model_dump(mode='json') for item in remaining], ensure_ascii=False)
    # These declarations are consumed only by the SDK boundary. The exact
    # original wire names, descriptions and complete schemas are preserved.
    definitions = tuple(ModelActionDefinition(name=tool['function']['name'], kind='tool',
        target_name=tool['function']['name'], description=tool['function']['description'],
        input_schema=tool['function']['parameters']) for tool in original['tools'])
    request = StructuredModelRequest(operation='agent_interaction_turn', version='native-history-stage-v1',
        messages=messages, model_history=history, output_type=BaseModel,
        context_projection_ref='offline:native-history:actual-full-stage', kind='tool_calling',
        action_definitions=definitions, action_choice=original['tool_choice'],
        max_tokens=original['max_completion_tokens'], reasoning_effort=original.get('reasoning_effort'),
        extra_body=original.get('extra_body'))
    return request, adapter._chat_kwargs(request), visible


def run(output: Path):
    output.mkdir(parents=True, exist_ok=False)
    (output/'replay-source.py').write_bytes(Path(__file__).read_bytes())
    try:
        settings = Settings.from_env()
        adapter = OpenAIModelClient(settings.structured)
        request0 = load(SOURCE/'turn-01.request.json')
        snapshots = sorted((SOURCE/'server-data/interaction_runs'/request0['interaction_run_ref']).glob('*.json'))
        original_trace = InteractionTrace.model_validate_json(snapshots[-1].read_bytes())
        # Original request identities establish chronological stages; filesystem
        # mtimes can change when the sealed corpus is copied or restored.
        identities = ('987a6768a1cc4066b52202b898129fb7', 'b1d62d3ae6d64264b84e9d93dc5dd7e8',
                      '0d3de348c08e400aa0ca3c803b72bf3f', 'f359e675c6624d5c8805796999816339',
                      '66dba489abce4db082684647ffbe5daf')
        files = [SOURCE/'sdk'/f'{identity}.candidate.response.json' for identity in identities]
        records = []
        stages = []
        sources = [snapshots[-1], *Path('src/personal_agent/application/conversation').glob('*.py'),
                   Path('src/personal_agent/infra/structured_model.py'),
                   Path('src/personal_agent/infra/model_capacity.py'),
                   Path('src/personal_agent/capabilities/contracts/model.py')]
        final_request = None
        for turn, file in enumerate(files, 1):
            source_request = file.with_name(file.name.replace('.response.', '.request.'))
            original = load(source_request)
            trace = original_trace.model_copy(update={'model_decisions': tuple(records)})
            request, kwargs, visible = materialize_stage(adapter, original, trace)
            check_model_capacity(operation=request.operation, provider_host=settings.structured.capacity.provider_host,
                model=settings.structured.model, kwargs=kwargs, capacity=settings.structured.capacity)
            if kwargs['tools'] != original['tools']:
                raise ValueError('完整工具声明发生范围外变化')
            if len(request.model_history) != turn-1:
                raise ValueError('没有恢复全部已结算的原生交换')
            for exchange, prior in zip(request.model_history, records, strict=True):
                if exchange.assistant != prior.assistant:
                    raise ValueError('原始assistant字段被改写')
            (output/f'stage-{turn:02}.request.json').write_bytes(json_bytes(kwargs))
            stages.append({'turn':turn, 'original_roles':[m['role'] for m in original['messages']],
                'candidate_roles':[m['role'] for m in kwargs['messages']],
                'complete_exchanges':len(request.model_history), 'full_schema_preserved':True})
            response = ChatCompletion.model_validate(load(file)['response'])
            assistant = adapter._assistant_message(response.choices[0].message, response)
            if assistant.payload != load(file)['response']['choices'][0]['message']:
                raise ValueError('SDK边界未保留完整原始assistant字段')
            feedback = next((item for item in original_trace.inputs
                             if isinstance(item, DecisionFeedback) and item.decision_turn == turn), None)
            records.append(ModelDecisionRecord(turn_index=turn, input_start=len(visible), assistant=assistant,
                blocked_by=input_identity(feedback) if feedback else None))
            sources.extend([file,source_request])
            final_request = request
        if len(stages) != 5 or final_request is None:
            raise ValueError('原轨迹完整决策阶段数量不符')
        trace = original_trace.model_copy(update={'revision':1,'model_decisions':tuple(records[:-1])})
        journal = FileInteractionJournal(output/'journal')
        journal.put(trace)
        recovered = FileInteractionJournal(output/'journal').get(trace.interaction_run_ref)
        source_request = files[-1].with_name(files[-1].name.replace('.response.','.request.'))
        _, restored, _ = materialize_stage(adapter, load(source_request), recovered)
        if restored != load(output/'stage-05.request.json'):
            raise ValueError('新Journal实例恢复后的请求发生变化')
        mismatch = final_request.model_history[0].model_copy(update={'assistant':
            final_request.model_history[0].assistant.model_copy(update={'provider_host':'invalid.example'})})
        try:
            adapter._chat_kwargs(replace(final_request,model_history=(mismatch,*final_request.model_history[1:])))
        except ModelCapacityRefused:
            pass
        else:
            raise ValueError('跨Provider续接未拒绝')
        exchange = final_request.model_history[-1]
        try:
            ModelToolExchange(assistant=exchange.assistant, results=exchange.results[:-1])
        except ValidationError:
            pass
        else:
            raise ValueError('缺失配对工具结果未拒绝')
        choices = [(index,input_identity(item)) for index,item in enumerate(original_trace.inputs)
                   if input_identity(item) is not None]
        protected_index = decision_input_indices(trace,records[1])[0]
        groups = HistoryCompactor._atomic_groups(trace,[item for item in choices if item[0] != protected_index])
        selected = {index for group in groups for index,_ in group}
        if selected & set(decision_input_indices(trace,records[1])):
            raise ValueError('原子选择仍拆开真实并行工具调用集合')
        report = {'evidence_class':'offline_full_actual_native_history_stages','stages':stages,
            'passed_stages':5,'planned_stages':5,'journal_recovery_same_request':True,
            'provider_mismatch_rejected':True,'missing_result_rejected':True,
            'parallel_group_atomic_selection':True,'new_model_calls':0,'new_tool_executions':0,
            'original_python_errors_preserved':True,'parameter_reliability_proven':False,
            'limitations':['协议物化与SDK边界，不是生产E2E或模型语义修复。',
                           '真实控制分支及完整摘要激活另行覆盖；本组未调用摘要模型。']}
        (output/'source-hashes.json').write_bytes(json_bytes({str(p):sha256(p.read_bytes()).hexdigest() for p in sources}))
        (output/'report.json').write_bytes(json_bytes(report))
        print('actual native-history stages 5/5; paid calls 0; tool executions 0')
    except Exception as error:
        (output/'failure.json').write_bytes(json_bytes({'type':type(error).__name__,'message':str(error)}))
        raise
    finally:
        seal(output)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    run(parser.parse_args().output)
