"""Two Chinese user turns through HTTP, real models, Python and both verifiers."""
from __future__ import annotations

import argparse
import ast
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
import os
import operator
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tomllib
from time import monotonic, sleep
from uuid import uuid4

from dotenv import load_dotenv
import httpx

from personal_agent.adapters.web.routes.conversation import ConversationTurnRequest, ConversationTurnResponse
from personal_agent.application.conversation.models import ActionObservation, ConversationMessage, InteractionTrace
from personal_agent.application.python_execution.models import PythonExecutionAuthorization
from personal_agent.infra.python_execution.deployment import PythonExecutionDeploymentConfig
from personal_agent.kernel.config import Settings
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal

from evals.e2e_quality.evidence_catalog import VERIFICATION_CONTEXT_OUTCOME
from .longds_materials import json_bytes, seal, verify_seal
from .retrieval_capture_process import ActualWebProcess
from .run_longds import _configuration, _environment, _source_identity, _usage


ROOT = Path(__file__).resolve().parents[2]
PYTHON_IMAGE = 'sha256:510b3b843826cf0bb0684f73e33171ef96735856d2f6569c7a235a2426678755'
QUESTIONS = ('请使用 Python 计算 37×43，报告结果并简要说明计算方法。',
             '请将上轮计算结果再加 17，报告新的数值。')


def arithmetic(node: ast.AST, bindings: dict[str, int] | None = None) -> int:
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return node.value
    if isinstance(node, ast.Name) and bindings is not None and node.id in bindings:
        return bindings[node.id]
    if isinstance(node, ast.BinOp) and type(node.op) in (ast.Add, ast.Sub, ast.Mult):
        operation = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul}[type(node.op)]
        return operation(arithmetic(node.left, bindings), arithmetic(node.right, bindings))
    raise ValueError('Fixed arithmetic outcome cannot be verified from this expression')


def assert_user_result(result: ConversationTurnResponse, trace: InteractionTrace, number: int) -> None:
    """Check explicit numeric claims and the requested method, not number occurrence."""
    expected = (1591, 1608)[number - 1]
    assert result.disposition == 'answer'
    text = result.message.content.replace('**', '').replace('`', '').replace(',', '')
    numeric = r'[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?'
    matches = re.finditer(rf'(?:结果|数值|答案)\s*(?:为|是|[:：])?\s*({numeric}(?:\s*[×+*=-]\s*{numeric})*)(?![\w.])', text)
    claims = [match.group(1) for match in matches
              if not re.search(r'(?:上一轮|上轮)(?:的)?(?:计算)?\s*$', text[:match.start()])]
    assert claims, 'No explicit result claim that this fixed outcome check can verify'
    for claim in claims:
        values = [arithmetic(ast.parse(part.replace('×', '*').strip(), mode='eval').body) for part in claim.split('=')]
        assert all(value == expected for value in values), f'Conflicting result claim: {claim}'
    assert not re.search(rf'{expected}[^。\n]*?(?:不是|不等于|并非)', text), 'Result is negated'
    assert not re.search(rf'(?:不是|不等于|并非)\s*{expected}', text), 'Result is negated'
    if number == 1:
        methods = []
        for block in re.findall(r'```(?:python)?\s*\n(.*?)```', result.message.content, re.DOTALL):
            try:
                statements = ast.parse(block).body
            except SyntaxError:
                # Untagged stdout is user-facing data, not necessarily Python.
                continue
            bindings = {}
            for statement in statements:
                if (isinstance(statement, ast.Assign) and len(statement.targets) == 1
                        and isinstance(statement.targets[0], ast.Name)):
                    variable = statement.targets[0].id
                    try:
                        bindings[variable] = arithmetic(statement.value, bindings)
                    except ValueError:
                        bindings.pop(variable, None)
                for node in ast.walk(statement):
                    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
                        try:
                            operands = {arithmetic(node.left, bindings), arithmetic(node.right, bindings)}
                        except ValueError:
                            continue
                        if operands == {37, 43}:
                            methods.append(arithmetic(node, bindings))
        assert methods and all(value == expected for value in methods), 'Python calculation method missing'
        python_results = [item for item in trace.inputs if isinstance(item, ActionObservation)
            and item.capability_id == 'execute_python' and item.status == 'succeeded']
        assert python_results and any(str(expected) in json.dumps(item.payload) for item in python_results)


def assert_feature_flags(trace: InteractionTrace, expected_flags: dict[str, bool]) -> None:
    """Protect actual deployment selection and distinguish absence from a pass."""
    from personal_agent.application.conversation.verification_admission import observed_receipts
    assert trace.feature_flags_binding.model_dump() == expected_flags, 'Run feature flags differ from the selected configuration'
    receipts = observed_receipts(trace.inputs, capability_names=frozenset({'verify_interaction_draft'}))
    for key, kind in (('goal_verification', 'goal'), ('answer_verification', 'answer')):
        present = any(receipt.checked_kind == kind for receipt in receipts)
        assert present == expected_flags[key], f'{key}: expected {expected_flags[key]}, observed {present}'
    if not expected_flags['goal_verification']:
        assert trace.goal_operations and all(operation.verification_ref is None for operation in trace.goal_operations)


def audit_existing(source: Path, output: Path) -> None:
    """Qualify the outcome check on sealed actual deliveries and explicit counterfactuals."""
    verify_seal(source)
    output.mkdir(parents=True, exist_ok=False)
    (output / 'runner.py').write_bytes(Path(__file__).read_bytes())
    rows = []
    audited_turns = []
    try:
        for number in (1, 2):
            if not (source / f'turn-{number:02}.response.json').exists():
                continue
            result = ConversationTurnResponse.model_validate_json((source / f'turn-{number:02}.response.json').read_bytes())
            trace = InteractionTrace.model_validate_json((source / f'turn-{number:02}.trace.json').read_bytes())
            candidates = [('actual', result.message.content, True),
                ('conflicting_result', result.message.content + '\n正确答案是1600。', False),
                ('negated_result', result.message.content + f'\n结果不是{(1591, 1608)[number - 1]}。', False),
                ('decimal_result', result.message.content.replace(str((1591, 1608)[number - 1]),
                    str((1591, 1608)[number - 1]) + '.5'), False),
                ('negative_result', result.message.content + f'\n正确答案是-{(1591, 1608)[number - 1]}。', False)]
            if number == 1:
                candidates.append(('missing_method', re.sub(r'```.*?```', '', result.message.content, flags=re.DOTALL), False))
            for label, content, expected in candidates:
                candidate = result.model_copy(update={'message': result.message.model_copy(update={'content': content})})
                try:
                    assert_user_result(candidate, trace, number)
                    passed = True
                except (AssertionError, ValueError, SyntaxError):
                    passed = False
                assert passed == expected, f'Outcome qualification failed: turn {number} {label}'
                rows.append({'user_turn': number, 'kind': label, 'content': content,
                             'expected_passed': expected, 'actual_passed': passed})
            audited_turns.append(number)
        assert audited_turns, 'No actual completed deliveries to qualify'
        (output / 'report.json').write_bytes(json_bytes({'source': str(source), 'rows': rows,
            'passed_checks': len(rows), 'audited_turns': audited_turns,
            'actual_deliveries_passed': len(audited_turns), 'new_model_calls': 0,
            'scope': 'fixed_arithmetic_outcome_qualification'}))
        print(f'封存用户结果与错误反事实检查 {len(rows)}/{len(rows)}；模型调用 0')
    except Exception as error:
        (output / 'failure.json').write_bytes(json_bytes({'type': type(error).__name__, 'message': str(error)}))
        raise
    finally:
        seal(output)


def run(output: Path, *, feature_flags: Path | None = None, continue_source: Path | None = None):
    load_dotenv(ROOT / '.env')
    flag_source = (feature_flags or ROOT / 'config/feature_flags.toml').resolve()
    flag_bytes = flag_source.read_bytes()
    expected_flags = tomllib.loads(flag_bytes.decode('utf-8'))['features']
    if feature_flags is not None:
        os.environ['PERSONAL_AGENT_FEATURE_FLAGS_CONFIG'] = str(flag_source)
    os.environ.update({
        'PERSONAL_AGENT_PROMPT_LANGUAGE': 'zh',
        'PERSONAL_AGENT_ANSWER_RESULT': '{"writer":"direct"}',
        'PERSONAL_AGENT_INTERACTION_MAX_MODEL_TURNS': '40',
        'PERSONAL_AGENT_INTERACTION_MAX_TOTAL_TOKENS': '10000000',
        'PERSONAL_AGENT_E2E_TRACE_DIR': str(output / 'e2e'),
        'PERSONAL_AGENT_PRODUCT_EVIDENCE_DIR': str(output / 'product'),
    })
    settings = Settings.from_env()
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / 'runner.py').write_bytes(Path(__file__).read_bytes())
    (output / 'feature_flags.toml').write_bytes(flag_bytes)
    _source_identity(output)
    (output / 'configuration.json').write_bytes(json_bytes(_configuration(settings)))
    (output / 'outcome-contract.json').write_bytes(json_bytes(asdict(VERIFICATION_CONTEXT_OUTCOME)))
    hashes = {str(path): sha256(path.read_bytes()).hexdigest() for path in (ROOT / 'src/personal_agent').rglob('*.py')}
    principal = AuthenticatedPrincipal(tenant_id='verification-context-' + uuid4().hex, user_id='analyst')
    conversation_id = 'verification-context-' + uuid4().hex
    authorization = PythonExecutionAuthorization(authorized_principal=principal, conversation_id=conversation_id,
        expires_at=datetime.now(UTC) + timedelta(minutes=20), max_total_tokens=500000,
        max_execution_seconds=1200, image_id=PYTHON_IMAGE)
    completed_turns, prior_tokens, prior_elapsed = 0, 0, 0.0
    messages, rows = [], []
    if continue_source is not None:
        verify_seal(continue_source)
        for name, digest in hashes.items():
            archived = continue_source / 'source-snapshot' / Path(name).relative_to(ROOT)
            if not archived.exists() or sha256(archived.read_bytes()).hexdigest() != digest:
                raise ValueError('Continuation requires unchanged production source')
        source_report = json.loads((continue_source / 'report.json').read_bytes())
        if source_report['feature_flags'] != expected_flags:
            raise ValueError('Continuation cannot change feature flags')
        prior_tokens, prior_elapsed = source_report['known_tokens'], source_report['elapsed_seconds']
        authorization = PythonExecutionDeploymentConfig.model_validate_json(
            (continue_source / 'python-deployment.json').read_bytes()).authorization
        principal, conversation_id = authorization.authorized_principal, authorization.conversation_id
        previous_request = ConversationTurnRequest.model_validate_json((continue_source / 'turn-01.request.json').read_bytes())
        previous_response = ConversationTurnResponse.model_validate_json((continue_source / 'turn-01.response.json').read_bytes())
        previous_trace = InteractionTrace.model_validate_json((continue_source / 'turn-01.trace.json').read_bytes())
        assert_user_result(previous_response, previous_trace, 1)
        assert_feature_flags(previous_trace, expected_flags)
        if (continue_source / 'turn-02.request.json').exists():
            raise ValueError('This continuation accepts exactly one completed user turn')
        shutil.copytree(continue_source / 'server-data', output / 'server-data')
        for file in continue_source.glob('turn-01.*'):
            shutil.copyfile(file, output / file.name)
        messages = [*previous_request.messages, previous_response.message]
        rows = [{'user_turn': 1, 'expected': 1591, 'user_result_passed': True,
                 'run_ref': previous_trace.interaction_run_ref, 'source': str(continue_source)}]
        completed_turns = 1
    deployment = PythonExecutionDeploymentConfig(authorization=authorization,
        endpoint='npipe:////./pipe/dockerDesktopLinuxEngine')
    authorization_file = output / 'python-deployment.json'
    authorization_file.write_text(deployment.model_dump_json(indent=2), encoding='utf-8')
    api_key = secrets.token_urlsafe(32)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = _environment(settings, output, principal=principal, api_key=api_key, port=port,
                       authorization_file=authorization_file)
    process, actual = None, None
    started = monotonic()
    failure = None
    try:
        with (output / 'server.log').open('wb') as log:
            process = subprocess.Popen([sys.executable, '-B', '-m', 'evals.product_baselines.retrieval_acceptance_server'],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            with httpx.Client(base_url=f'http://127.0.0.1:{port}',
                              headers={'Authorization': 'Bearer ' + api_key}) as client:
                deadline = monotonic() + 45
                while monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError('Formal web process exited before readiness')
                    try:
                        if client.get('/api/health', timeout=1).status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    sleep(0.1)
                else:
                    raise TimeoutError('Formal web process readiness timed out')
                actual = ActualWebProcess(process, output / 'server-process.json')
                print('正式 HTTP 入口已就绪；开始两轮真实用户任务', flush=True)
                for number, (question, expected) in enumerate(zip(QUESTIONS[completed_turns:],
                        (1591, 1608)[completed_turns:], strict=True), completed_turns + 1):
                    if prior_elapsed + monotonic() - started >= 1200 or prior_tokens + _usage(output / 'sdk')[1] >= 500000:
                        raise RuntimeError('Declared task budget exhausted')
                    messages.append(ConversationMessage(role='user', content=question))
                    request = ConversationTurnRequest(conversation_id=conversation_id,
                        interaction_run_ref='irun_' + uuid4().hex, messages=list(messages), interaction_mode='auto')
                    prefix = output / f'turn-{number:02}'
                    prefix.with_suffix('.request.json').write_bytes(json_bytes(request.model_dump(mode='json')))
                    response = client.post('/api/conversation/turn', json=request.model_dump(mode='json'),
                                           timeout=max(1, 1200 - prior_elapsed - (monotonic() - started)))
                    prefix.with_suffix('.response.json').write_bytes(response.content)
                    prefix.with_suffix('.http.json').write_bytes(json_bytes({'status_code': response.status_code}))
                    trace_response = client.get(f'/api/conversation/runs/{request.interaction_run_ref}', timeout=30)
                    prefix.with_suffix('.trace.json').write_bytes(trace_response.content)
                    response.raise_for_status()
                    trace_response.raise_for_status()
                    result = ConversationTurnResponse.model_validate_json(response.content)
                    trace = InteractionTrace.model_validate_json(trace_response.content)
                    assert_user_result(result, trace, number)
                    assert_feature_flags(trace, expected_flags)
                    rows.append({'user_turn': number, 'expected': expected, 'user_result_passed': True,
                                 'run_ref': request.interaction_run_ref})
                    messages.append(result.message)
                    print(f'第 {number} 轮正常交付；数值 {expected}；累计用量 {_usage(output / "sdk")}', flush=True)
    except Exception as error:
        failure = {'type': type(error).__name__, 'message': str(error)}
        raise
    finally:
        if actual is not None:
            try:
                actual.stop(deadline=monotonic() + 15)
            finally:
                actual.close()
        elif process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=15)
        physical, tokens, unknown = _usage(output / 'sdk')
        drift = [name for name, digest in hashes.items() if sha256(Path(name).read_bytes()).hexdigest() != digest]
        fully_verified = all(expected_flags.values())
        report = {'evidence_class': 'product_e2e' if fully_verified else 'unverified_flow_capture',
                  'feature_flags': expected_flags, 'case_id': 'VERIFICATION-CONTEXT-001',
                  'planned_user_turns': 2, 'passed_user_turns': len(rows), 'rows': rows,
                  'failure': failure, 'physical_requests': physical, 'known_tokens': tokens,
                  'continued_source': str(continue_source) if continue_source else None,
                  'preceding_known_tokens': prior_tokens, 'preceding_elapsed_seconds': prior_elapsed,
                  'unknown_usage': unknown, 'source_drift': drift,
                  'actual_process_stopped': process is None or process.poll() is not None,
                  'elapsed_seconds': monotonic() - started, 'release_eligible': False}
        (output / 'report.json').write_bytes(json_bytes(report))
        seal(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--audit-source', type=Path)
    parser.add_argument('--feature-flags', type=Path)
    parser.add_argument('--continue-source', type=Path)
    args = parser.parse_args()
    if args.audit_source is not None:
        audit_existing(args.audit_source, args.output)
    else:
        run(args.output, feature_flags=args.feature_flags, continue_source=args.continue_source)
