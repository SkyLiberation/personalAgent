"""消费完整真实文件阶段，验证读取、搜索、检查及不可变草稿的 ID 交接。"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from pathlib import Path
import shutil

from personal_agent.application.artifacts.service import ArtifactService
from personal_agent.application.conversation.artifact_sources import input_resource_refs
from personal_agent.application.conversation.citations import materialize_citation_context
from personal_agent.application.conversation.journal import FileInteractionJournal
from personal_agent.application.conversation.models import ArtifactSourceInput, InteractionTrace, ToolCallProposal
from personal_agent.application.conversation.service import ConversationService
from personal_agent.application.conversation.tool_requests import WriteArtifactArgs
from personal_agent.governance.registry import ToolExecutor
from personal_agent.infra.artifact_ripgrep import RipgrepArtifactSearch
from personal_agent.kernel.config import Settings
from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.contracts.scope import ExecutionScope
from personal_agent.tools.inspect_artifact import build_inspect_artifact_tool
from personal_agent.tools.write_artifact import build_write_artifact_tool

from evals.product_baselines.artifact_reference_replay import SOURCE, load
from evals.product_baselines.longds_materials import json_bytes, seal, verify_seal


def run(prepared: Path, output: Path):
    verify_seal(SOURCE)
    verify_seal(prepared/'candidate')
    output.mkdir(parents=True, exist_ok=False)
    (output/'runner-source.py').write_bytes(Path(__file__).read_bytes())
    for folder in ('uploads', 'generated_artifacts'):
        shutil.copytree(SOURCE/'server-data'/folder, output/'data'/folder)
    artifacts = ArtifactService(Settings(data_dir=output/'data'))
    trace = InteractionTrace.model_validate_json((prepared/'feedback-trace.json').read_bytes())
    inputs = tuple(ArtifactSourceInput.model_validate(row) for row in load(prepared/'declaration/inputs.json'))
    trace = trace.model_copy(update={'revision':1, 'inputs':inputs, 'execution_order':(), 'concurrent_batches':(),
        'run_deadline_at':datetime.now(UTC)+timedelta(hours=1)})
    journal = FileInteractionJournal(output/'data/interaction_runs')
    journal.put(trace)
    conversation = ConversationService(None, artifact_port=artifacts, artifact_search=RipgrepArtifactSearch(), journal=journal)
    principal = trace.principal
    refs = input_resource_refs(inputs)
    selected = refs[0]
    context = (trace.conversation_id, trace.interaction_run_ref, principal, principal, 'offline_artifact_id')
    observations = []
    for number, (tool, args) in enumerate((
        ('read_artifact', {'resource_id':selected.resource_id, 'limit':1}),
        ('search_action_output', {'resource_id':selected.resource_id, 'keyword':'show_id'}),
    ), 1):
        action = ToolCallProposal(action_id=f'file-id-{number}', tool_name=tool, arguments=args)
        feedback = conversation._admit(action, run_ref=trace.interaction_run_ref, committed_action_ids=(), committed_inputs=inputs)
        if feedback is not None:
            raise ValueError(feedback.model_dump_json())
        observed = conversation._execute_one(action, context).interaction_input
        if observed.status != 'succeeded':
            raise ValueError(observed.model_dump_json())
        observations.append(observed)
    continuation = observations[0].payload['next_read']
    assert continuation['resource_id'] == selected.resource_id and 'resource_ref' not in continuation
    next_read = conversation._execute_one(ToolCallProposal(action_id='file-id-next', tool_name='read_artifact', arguments=continuation), context).interaction_input
    assert next_read.status == 'succeeded' and next_read.payload['lines'][0]['line'] == 2
    cited = materialize_citation_context((*inputs, *observations))
    assert cited[-1].executed_query.resource_id == selected.resource_id
    registry = ToolExecutor()
    registry.register(build_inspect_artifact_tool(artifacts))
    registry.register(build_write_artifact_tool(artifacts))
    scope = ExecutionScope(principal=principal, execution_id=trace.interaction_run_ref, thread_id=trace.conversation_id, task_id='file-id-inspect')
    inspected = registry.invoke_interaction('inspect_artifact', {'resource_id':selected.resource_id},
        execution_scope=scope, tool_call_id=scope.task_id, allowed_resource_refs=refs, source_platform='offline_artifact_id')
    assert inspected['ok']
    # Use the candidate model's actual source; this journey does not execute it
    # or claim semantic correctness. Its bytes are the draft being handed over.
    report = load(prepared/'candidate/report.json')
    code = next(call['arguments']['code'] for journey in report['journeys'] for stage in journey['stages']
                for call in stage['calls'] if call['name'] == 'tool_execute_python')
    created = None
    receipts = []
    for label, request in (
        ('create', {'operation':'create', 'filename':'analysis.py', 'content_type':'text/x-python', 'content':code}),
        ('patch', None),
    ):
        if label == 'patch':
            request = {'operation':'patch', 'base_resource_id':created.resource_id,
                       'edits':[{'range':{'start':{'line':1,'column':1},'end':{'line':1,'column':1}},'new_text':'# artifact ID binding\n'}]}
        args = WriteArtifactArgs.model_validate({'request':request})
        call_id = f'file-id-{label}'
        action_scope = scope.model_copy(update={'task_id':call_id})
        accepted = journal.accept_tool_request(execution_scope=action_scope, action_id=call_id, arguments=args, plan_step_id=None)
        result = registry.invoke_interaction('write_artifact', args.model_dump(mode='json'), execution_scope=action_scope,
            tool_call_id=call_id, allowed_resource_refs=refs, accepted_request_digest=accepted.request_digest,
            source_platform='offline_artifact_id')
        assert result['ok'], result
        ref = ResourceRef.model_validate(result['data']['resource_ref'])
        recovered = artifacts.recover_draft(execution_scope=action_scope, tool_call_id=call_id, request=args.request, allowed_resource_refs=refs)
        assert recovered.resource_ref == ref
        if label == 'create':
            created = ref
            refs = (*refs, ref)
        else:
            assert ref != created
            assert artifacts.read_text(ref, principal=principal, owner=principal) == '# artifact ID binding\n'+code
            assert artifacts.read_text(created, principal=principal, owner=principal) == code
        receipts.append(result)
    rejected = []
    for label, current in (
        ('unknown', tuple(ref for ref in refs if ref.resource_id != selected.resource_id)),
        ('ambiguous_version', (selected, selected.model_copy(update={'revision':2}))),
        ('cross_principal', (selected.model_copy(update={'owner':principal.model_copy(update={'user_id':'other'})}),)),
        ('metadata_version_mismatch', (selected.model_copy(update={'revision':2}),)),
    ):
        refused = registry.invoke_interaction('inspect_artifact', {'resource_id':selected.resource_id},
            execution_scope=scope, tool_call_id=f'file-id-refuse-{label}', allowed_resource_refs=current,
            source_platform='offline_artifact_id')
        if refused['ok'] or refused.get('data') is not None:
            raise ValueError(f'{label}: rejected file produced a successful result')
        rejected.append({'case':label, 'result':refused})
    unknown = conversation._admit(ToolCallProposal(action_id='file-id-unknown', tool_name='read_artifact', arguments={'resource_id':'art_unknown'}),
        run_ref=trace.interaction_run_ref, committed_action_ids=(), committed_inputs=inputs)
    assert unknown is not None and unknown.reason_code == 'artifact_reference_invalid'
    (output/'report.json').write_bytes(json_bytes({'evidence_class':'offline_actual_artifact_handoff', 'source':str(SOURCE),
        'actual_initial_files':len(inputs), 'read_search_inspect_succeeded':True, 'next_read_id_and_coordinates_preserved':True,
        'search_citation_binding_preserved':True, 'draft_original_bytes_and_recovery_preserved':True, 'refusals':rejected,
        'new_model_calls':0, 'new_container_executions':0, 'release_eligible':False,
        'observations':[item.model_dump(mode='json') for item in observations], 'draft_receipts':receipts}))
    seal(output)
    print('actual file ID handoff passed: read/search/inspect/create/patch/recovery and scope/version refusal')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.prepared, args.output)
