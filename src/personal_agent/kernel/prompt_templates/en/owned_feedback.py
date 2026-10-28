"""English mirrors of owned model instructions and execution feedback."""
from personal_agent.kernel.prompt_registry import PromptTranslation

TRANSLATIONS = {
    'research_policy_decision': PromptTranslation(
        source_version='2026-10-27.v1-md1', version='2026-10-27.v1-md1',
        template="""

## Task
You select the research agent's next strategy. You may propose a search_web query with greater information gain, or stop when evidence is sufficient or further budget spending is not worthwhile. Output only JSON, without explanatory prose.

## Output contract
Allowed actions: search_web, stop.
JSON schema: {{"action":"search_web|stop","query":"...","purpose":"...","event_id":"...","expected_gain":"official_confirmation|independent_source|disambiguation|personal_relevance|recency|stop","cost_level":"low|medium|high","reason":"..."}}.

## Constraints
Constraints: search_web queries must be specific and must not repeat executed queries; event_id must come from the event list or be empty. Do not spend budget filling low-value gaps.

## Current inputs
Topic: {topic}
Requirements: {instructions}
Research policy: {policy}
Initial query plan: {query_plan}
Executed queries: {query_history}
Remaining query budget: {remaining_queries}
Remaining exploration query budget: {remaining_exploration}
Remaining verification query budget: {remaining_verification}
Remaining tool-call budget: {remaining_tools}
Events: {events}
Evidence gaps: {gaps}
Suggested actions: {action_hints}""",
    ),
    'research_next_action': PromptTranslation(
        source_version='2026-10-27.v1-md1', version='2026-10-27.v1-md1',
        template="""

## Task and constraints
Select the next action in the research loop. Choose only one of the supplied candidates; do not invent a new action or query. Within the available budget, prioritize improving event credibility, especially by finding official or independent sources. Choose stop if no candidate is valuable.

## Output
Output only JSON: {{"candidate_id":"candidate_0","reason":"..."}} or {{"candidate_id":"stop","reason":"..."}}.

## Current inputs
Topic: {topic}
Requirements: {instructions}
Research policy: {policy}
Executed queries: {query_history}
Remaining query budget: {remaining_queries}
Remaining verification query budget: {remaining_verification}
Events: {events}
Candidates: {candidates}""",
    ),
    'research_satisfaction': PromptTranslation(
        source_version='2026-10-27.v1-md1', version='2026-10-27.v1-md1',
        template="""

## Task
Assess whether the current research has met the user's goal. Output JSON only, without Markdown.

## Output contract
JSON schema: {{"coverage_score":0.0,"confidence_score":0.0,"remaining_critical_gap_ids":["..."],"marginal_gain":0.0,"should_continue":true,"reason":"..."}}.

## Decision criteria
coverage_score measures whether enough candidate events cover the topic; confidence_score measures whether source support meets the user's credibility goal; marginal_gain measures the expected additional value of further search. remaining_critical_gap_ids may cite only supplied gap IDs that still prevent the goal from being met. Under a limited budget, set should_continue=false if further search would only repeat low-yield work.

## Current inputs
Topic: {topic}
Requirements: {instructions}
Target item count: {max_items}
Research policy: {policy}
Iterations: {iterations}/{max_queries}
Exploration queries: {exploration}/{max_exploration}
Verification queries: {verification}/{max_verification}
Tool calls: {tool_calls}/{max_tool_calls}
Consecutive low-yield rounds: {low_yield_rounds}
Executed queries: {query_history}
Events: {events}
Evidence gaps: {gaps}""",
    ),
    'research_request_understanding': PromptTranslation(
        source_version='2026-10-27.v1-md1', version='2026-10-27.v1-md1',
        template="""

## Task
Parse a research request into a normalized research run and an initial search strategy. Output JSON only, without Markdown or explanations.

## Output contract
JSON schema: {{"topic":"...","instructions":"...","max_items":1,"lookback_hours":24,"policy":{{"research_type":"technical_product_update|academic_research|company_financials|general_news","source_preference":["official","docs","github","paper","media"],"evidence_requirement":"official_or_multi_source|official_required|paper_or_primary_source|primary_financial_source_required|multi_source","ranking_objective":"confidence_first|personal_relevance_first|novelty_first|impact_first","verification_strictness":"low|medium|medium_high|high"}},"query_plan":[{{"query":"...","intent":"official|docs|repo|paper|technical|media|latest|financial_filing|transcript","priority":0.9}}]}}.

## Requirements
Requirements: topic contains only the research subject, without control instructions such as researching, maximum item counts, or high credibility. instructions retains credibility, source preferences, personal relevance, language, exclusions, and other constraints. policy sets evidence requirements and ranking objectives for the research type. max_items is 1 to 20; lookback_hours is 1 to 720; query_plan must fit the remaining query budget and cover evidence angles such as primary sources, repositories, documentation, papers, and media. Use defaults for unspecified values.

## Current inputs
Original topic/request: {topic}
Existing instructions: {instructions}
Default max_items: {max_items}
Default lookback hours: {lookback_hours}
Total query budget: {max_queries}
Initial exploration query budget: {max_exploration}
Evidence verification query budget: {max_verification}
Subscription seed queries: {seed_queries}""",
    ),
    'knowledge.consolidation.source': PromptTranslation(
        source_version='2026-10-27.v1-md1', version='2026-10-27.v1-md1',
        template="""

## Source {index}
{title}
{content}""",
    ),
    'knowledge.consolidation.draft': PromptTranslation(
        source_version='2026-10-27.v1-md1', version='2026-10-27.v1-md1',
        template="""

## Task
Consolidate the following notes about "{topic}" into a structured knowledge review. Merge duplicate content, preserve key facts, organize with subheadings, and start with an overview of the topic.

## Source material
{sources}""",
    ),
    'artifacts.image.question_default': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Please summarize the image content.',
    ),
    'artifacts.image.describe': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template="Objectively describe the visible content of the attachment and answer the user's question; do not claim it has been saved.\nUser request: {question}",
    ),
    'knowledge.gap_question': PromptTranslation(
        source_version='2026-10-27.v1-md1', version='2026-10-27.v1-md1',
        template="""

## Task and output
Rewrite the following personal knowledge-base gap as one natural, friendly, concise question in Chinese. Output only the question itself.

## Inputs
Gap type: {gap_type}
Related entities: {entities}
Default wording: {question}""",
    ),
    'knowledge.gap_no_entities': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='None',
    ),
    'tools.context_missing': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The tool is missing a trusted execution context.',
    ),
    'tools.execution_failed': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Tool execution failed.',
    ),
    'tools.web_read.domain_denied': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The target domain is not allowed; the body was not read.',
    ),
    'tools.web_read.no_body': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The provider returned no readable body.',
    ),
    'tools.web_read.failed': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Web reading failed: {detail}',
    ),
    'tools.web_read.transient': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Web reading failed temporarily: {detail}',
    ),
    'tools.web_read.undelivered': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Web reading did not deliver the body: {detail}',
    ),
    'tools.python.acceptance_missing': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The Python execution request has no accepted record.',
    ),
    'tools.python.read_receipt': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Read the receipt and original diagnostics.',
    ),
    'tools.python.status': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Actual Python execution status: {status}; {detail}',
    ),
    'tools.experiment.acceptance_missing': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The experiment request has no accepted record.',
    ),
    'tools.experiment.read_receipt': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='See the actual receipt.',
    ),
    'tools.experiment.status': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Experiment status: {status}; {detail}',
    ),
    'tools.artifact.acceptance_missing': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The save request has no accepted record bound to this execution identity.',
    ),
    'tools.verification.criteria_coverage': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The final verification output did not cover each current criterion_id exactly once; a verification receipt cannot be formed.',
    ),
    'tools.graph.unconfigured': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The graph is not configured or enabled.',
    ),
    'tools.graph.unavailable': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Graph retrieval is unavailable.',
    ),
    'tools.research.run_unavailable': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='No Research run accessible to this user was found.',
    ),
    'artifacts.ref_unavailable': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The file ID is outside the currently readable set or resolves to multiple distinct exact references.',
    ),
    'artifacts.ref_owner_mismatch': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The file ID does not identify an Artifact owned by the current principal.',
    ),
    'python_execution.authorization': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The current principal is not authorized for this Python execution deployment.',
    ),
    'python_execution.request_digest': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The Python request differs from its accepted digest.',
    ),
    'python_execution.accepted_deployment': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='This run did not accept the Python request under the current deployment.',
    ),
    'python_execution.receipt_command': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The Python receipt is missing its frozen Command.',
    ),
    'python_execution.execution_command': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The Python execution record is missing its frozen Command.',
    ),
    'python_execution.recovery_fact': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The recovered Python result differs from the saved process facts.',
    ),
    'python_execution.input_owner': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Python can read only exact Artifacts owned by the current principal.',
    ),
    'python_execution.input_boundary': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The Python input identity or byte length exceeds the boundary.',
    ),
    'python_execution.input_changed': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The Artifact identity changed while Python input was being read.',
    ),
    'python_execution.budget_exhausted': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='This run has exhausted its execution allowance or absolute deadline.',
    ),
    'python_execution.input_budget_exhausted': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='This run reached its deadline or exhausted its allowance while preparing Python inputs.',
    ),
    'python_execution.timer_resolution': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The remaining Python allowance is below execution timer resolution.',
    ),
    'python_execution.command_request': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The frozen Python Command differs from the accepted request or deployment.',
    ),
    'python_execution.program_bytes': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The frozen Python program differs from the accepted original bytes.',
    ),
    'python_execution.original_command': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The original Python artifact differs from the frozen Command.',
    ),
    'python_execution.dispatching_result': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The executor cannot return dispatching as an execution result.',
    ),
    'python_execution.capture_budget': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The executor returned more bytes than the frozen capture allowance.',
    ),
    'python_execution.stdout_limit': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='stdout reached the capture limit; the original contains only the bytes actually captured.',
    ),
    'python_execution.stderr_limit': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='stderr reached the capture limit; the original contains only the bytes actually captured.',
    ),
    'python_execution.output_unavailable': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The original job output cannot be recovered. The program was not rerun; do not interpret this as empty output.',
    ),
    'python_execution.invalid_utf8': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='{stream} contains invalid UTF-8; captured original bytes are preserved and no text preview is provided.',
    ),
    'retrieval_experiment.authorization': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The current principal is not authorized for the experiment deployment.',
    ),
    'retrieval_experiment.request_digest': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The experiment request does not match its accepted digest.',
    ),
    'retrieval_experiment.accepted_deployment': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='This run did not accept the experiment request under the original deployment.',
    ),
    'retrieval_experiment.result_not_successful': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Results must come from successful experiments submitted by this run.',
    ),
    'retrieval_experiment.program_unreadable': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The program or configuration is outside the currently readable set.',
    ),
    'retrieval_experiment.program_not_draft': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The program or configuration must be a formal draft of the corresponding type in this run.',
    ),
    'retrieval_experiment.development_after_final': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Development and tuning cannot continue after final evaluation has been dispatched.',
    ),
    'retrieval_experiment.duplicate_input': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Input results must not be duplicated.',
    ),
    'retrieval_experiment.input_rankings': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The input ranking data or depth does not meet the development configuration.',
    ),
    'retrieval_experiment.freeze_not_submitted': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Only a frozen plan submitted by this run may be executed.',
    ),
    'retrieval_experiment.deployment_changed': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The original deployment artifact changed.',
    ),
    'retrieval_experiment.clock': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The experiment clock must provide timezone-aware UTC time.',
    ),
    'retrieval_experiment.deadline': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The experiment time allowance is exhausted.',
    ),
    'retrieval_experiment.snapshot_changed': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The accepted input snapshot changed.',
    ),
    'retrieval_experiment.private_digest': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The private scoring artifact digest does not match.',
    ),
    'retrieval_experiment.freeze_after_final': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The frozen plan cannot be replaced after final evaluation has been dispatched.',
    ),
    'retrieval_experiment.projection_digest': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The public text projection differs from the deployment manifest digest.',
    ),
    'retrieval_experiment.unknown': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The terminal execution status remains unknown; the original reserved allowance is retained.',
    ),
    'experiment_delivery.unsettled': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The experiment still has unconfirmed executions and cannot be delivered as complete.',
    ),
    'experiment_delivery.successful_execution': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The successful receipt has no corresponding actual successful execution.',
    ),
    'experiment_delivery.final_missing': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='No complete final evaluation has executed successfully.',
    ),
    'experiment_delivery.final_ambiguous': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Distinct final plans exist; the delivery component cannot choose one.',
    ),
    'experiment_delivery.freeze_missing': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='No valid freeze from this run preceded final evaluation.',
    ),
    'experiment_delivery.frozen_file_missing': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The original frozen file does not exist.',
    ),
    'experiment_delivery.artifact_missing': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='An original file required for delivery does not exist.',
    ),
    'experiment_delivery.result_fact_missing': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The result has no actual successful record in this run.',
    ),
    'experiment_delivery.result_artifact_missing': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='An original file required by the result does not exist.',
    ),
    'experiment_delivery.candidate_source_missing': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The actual candidate is missing its source-code reference.',
    ),
    'experiment_delivery.development_missing': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Complete successful BM25 and dense development experiments are required.',
    ),
    'experiment_delivery.selected_identity': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The frozen selection is not a development result preceding the freeze.',
    ),
    'experiment_delivery.final_split': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The final receipt contains experiment results from another split.',
    ),
    'experiment_delivery.final_baseline': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The final evaluation is missing an actual BM25 baseline.',
    ),
    'experiment_delivery.final_selected': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The final evaluation is missing a unique result for the frozen selection.',
    ),
    'experiment_delivery.coverage': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The experiment result does not cover the current complete dataset.',
    ),
    'experiment_delivery.query_facts': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Query execution facts are incomplete or differ from the actual rankings.',
    ),
    'experiment_delivery.per_query': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Per-query metrics do not cover the complete query set.',
    ),
    'policy.deny_user': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Policy prohibits user {user_id} from performing this action.',
    ),
    'policy.deny_source': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Policy prohibits entry source {source}.',
    ),
    'policy.deny_tool': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Policy prohibits calling tool {tool_name}.',
    ),
    'policy.deny_scope': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Policy prohibits permission scope {scope}.',
    ),
    'policy.tool_confirmation': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Tool {tool_name} is a high-risk operation and requires user confirmation before execution.',
    ),
    'policy.agent_confirmation': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Agent {agent_id} is a high-risk delegation and requires user confirmation before execution.',
    ),
    'policy.react_not_allowed': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Tool {tool_name} is not in the current ReAct allowlist.',
    ),
    'policy.react_blocked': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Tool {tool_name} cannot be called during autonomous ReAct execution.',
    ),
    'policy.owner_mismatch': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Resource {resource} is not owned by user {user_id}.',
    ),
    'policy.memory_delete_confirmation': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Deleting long-term memory requires confirmation before execution.',
    ),
    'policy.source_not_allowed': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Entry source {source} is not in the allowlist.',
    ),
    'policy.user_not_allowed': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='User {user_id} is not in the allowlist.',
    ),
    'tool_gateway.not_found': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Tool not found: {tool_name}',
    ),
    'tool_gateway.rate_limited': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Tool {tool_name} reached its rate limit; try again later.',
    ),
    'tool_gateway.timed_out': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Tool {tool_name} timed out (>{seconds}s).',
    ),
    'tool_gateway.not_executed': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Tool {tool_name} was not executed.',
    ),
    'tool_gateway.no_pending_call': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The tool node received no pending tool call.',
    ),
    'tool_gateway.idempotency_key_missing': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Tool {tool_name} is missing idempotency_key for a confirmed high-risk action.',
    ),
    'tool_gateway.idempotency_pending': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The same idempotent call of tool {tool_name} is still executing and has no replayable receipt (idempotency_key={key}).',
    ),
    'tool_gateway.domain_denied': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The target URL of tool {tool_name} is outside the allowed domain list.',
    ),
    'tool_gateway.workflow_not_found': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Workflow tool not found: {tool_name}',
    ),
    'artifact_search.engine_missing': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='ripgrep is not installed; body-text search cannot run.',
    ),
    'artifact_search.output_limit': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Search-engine output exceeded capacity. Incomplete matches were not returned; narrow the search expression.',
    ),
    'artifact_search.timeout': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Body-text search timed out; the unfinished search was not interpreted as zero matches.',
    ),
    'artifact_search.failed': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The search expression or engine failed: ',
    ),
    'web_source.body_limit': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The source body exceeds the single-call capacity; an incomplete body was not delivered.',
    ),
    'python_backend.deployment': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The Python Command differs from the fixed execution deployment.',
    ),
    'python_backend.directory_symlink': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The Python execution directory must not contain symbolic links.',
    ),
    'python_backend.directory_escape': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The Python execution directory is outside its allowed boundary.',
    ),
    'python_backend.job_command': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The original Python job differs from the frozen Command.',
    ),
    'python_backend.job_command_missing': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The original Python job is missing its frozen Command; re-execution is forbidden.',
    ),
    'python_backend.input_bytes': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The Python backend input differs from the frozen original bytes.',
    ),
    'python_backend.input_command': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The execution inputs differ from the frozen Python Command.',
    ),
    'python_backend.job_identity': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The Python working directory is missing its original identity; re-execution is forbidden.',
    ),
    'python_backend.input_symlink': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The Python input directory must not be a symbolic link.',
    ),
    'python_backend.input_snapshot': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The Python input snapshot conflicts with the existing snapshot.',
    ),
    'python_backend.cleanup_identity': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Python cleanup has not confirmed a matching stopped container.',
    ),
    'python_backend.job_record_symlink': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The original Python job record must not be a symbolic link.',
    ),
    'python_backend.job_binding': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The Python backend job does not match the frozen Command.',
    ),
    'python_recovery.identity_missing': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The candidate directory is missing its original identity; re-execution is forbidden.',
    ),
    'python_recovery.input_digest': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Python recovery requires exact input digests or original artifacts.',
    ),
    'python_recovery.identity_mismatch': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The original candidate identity differs from the recovery request.',
    ),
    'python_recovery.capture_binding': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The original Python capture differs from the job identity or limits.',
    ),
    'python_recovery.output_incomplete': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The original candidate output is incomplete.',
    ),
    'python_recovery.stderr_incomplete': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The original Python stderr capture is incomplete.',
    ),
    'experiment_backend.directory_escape': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The experiment directory is outside its allowed boundary.',
    ),
    'experiment_backend.deployment_stale': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The experiment deployment identity is no longer valid.',
    ),
    'experiment_backend.execution_identity': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The original backend execution identity conflicts with the request.',
    ),
    'experiment_backend.filename': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The execution staging filename is invalid.',
    ),
    'experiment_backend.staging_bytes': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The original bytes in execution staging changed.',
    ),
    'experiment_backend.input_binding': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The actual inputs differ from the Command or deployment authorization.',
    ),
    'experiment_backend.diagnostic_path': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The candidate diagnostic file is outside the current command directory.',
    ),
    'experiment_backend.diagnostic_symlink': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The candidate diagnostic path must not contain symbolic links.',
    ),
    'experiment_backend.diagnostic_file': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Candidate diagnostics must come from regular files.',
    ),
    'experiment_backend.diagnostic_snapshot': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The candidate diagnostic capture was partially committed and is missing its original result snapshot.',
    ),
    'experiment_backend.diagnostic_original': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The candidate diagnostic capture was partially committed and is missing its fixed original artifact.',
    ),
    'experiment_backend.diagnostic_job': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The candidate diagnostic capture does not match the original job identity.',
    ),
    'experiment_backend.diagnostic_authorization': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The candidate diagnostics do not belong to a candidate job authorized by the current Command.',
    ),
    'experiment_backend.diagnostic_source': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The candidate diagnostics are missing source code bound to the Command.',
    ),
    'experiment_backend.diagnostic_input': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The candidate diagnostic input roles or source/configuration digests differ from the Command.',
    ),
    'experiment_backend.diagnostic_freeze': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The candidate diagnostic source/configuration digests differ from the freeze.',
    ),
    'experiment_backend.diagnostic_baseline': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The final candidate diagnostics are missing an actual baseline result.',
    ),
    'experiment_backend.diagnostic_parent': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The final candidate diagnostics are missing an actual parent result.',
    ),
    'experiment_backend.diagnostic_parent_recipe': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The parent-generation recipe of the final candidate diagnostics differs from the freeze.',
    ),
    'experiment_backend.diagnostic_digest': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The candidate diagnostic job or public input digests differ from the current Command.',
    ),
    'experiment_backend.diagnostic_size': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The candidate diagnostic original length differs from the saved snapshot or capture allowance.',
    ),
    'experiment_backend.diagnostic_changed': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The candidate diagnostic original length changed while being read.',
    ),
    'experiment_backend.diagnostic_stdout_digest': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The candidate diagnostic stdout original-byte digest does not match.',
    ),
    'experiment_backend.diagnostic_unknown_nonempty': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The prior unknown candidate capture has nonempty content but lacks a container identity.',
    ),
    'experiment_backend.diagnostic_unbound_nonempty': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='A nonempty diagnostic capture exists before the candidate identity has been established.',
    ),
    'experiment_backend.stdout_encoding': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Candidate stdout preserves captured original bytes and contains non-UTF-8 content; it cannot be read directly as UTF-8 text.',
    ),
    'experiment_backend.stderr_projection': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Candidate stderr is a UTF-8 diagnostic projection rather than original bytes; ',
    ),
    'experiment_backend.stderr_replaced': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='invalid bytes were replaced; ',
    ),
    'experiment_backend.stderr_not_replaced': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='no invalid bytes were replaced; ',
    ),
    'experiment_backend.stderr_truncated': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='it was truncated at a UTF-8 character boundary to fit the publication byte allowance.',
    ),
    'experiment_backend.stderr_not_truncated': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='it was not truncated by the publication byte allowance.',
    ),
    'experiment_backend.result_path': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The backend result path is outside its allowed boundary.',
    ),
    'experiment_backend.public_projection': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The public text projection digest differs from the actual prepare artifact.',
    ),
    'experiment_results.artifact_size': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The experiment original-byte size differs from its Artifact registration.',
    ),
    'experiment_results.publication_identity': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The published experiment file does not match the original result identity.',
    ),
    'experiment_results.projection_binding': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The data projection differs from its publication binding.',
    ),
    'experiment_results.projection_prepared': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The data projection differs from the data actually prepared for the deployment.',
    ),
    'experiment_rules.development_only': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='A plan can be frozen only from development results.',
    ),
    'experiment_rules.coverage': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The frozen result is missing complete, consistent development query execution facts.',
    ),
    'experiment_rules.input_rankings': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The input rankings supplied for freezing differ from the actual execution.',
    ),
    'experiment_rules.baseline_inputs': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='This version freezes only trusted baseline inputs from the same development dataset.',
    ),
    'experiment_rules.source_identity': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The candidate source code or configuration differs from the executed version.',
    ),
    'experiment_rules.final_dataset': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The test data differs from the frozen dataset snapshot.',
    ),
    'experiment_rules.query_overlap': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The test queries overlap with development queries.',
    ),
    'experiment_rules.final_recipe': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The actual test implementation or model differs from the frozen version.',
    ),
    'experiment_rules.final_candidate': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The actual test candidate identity differs from the frozen plan.',
    ),
    'experiment_rankings.coverage': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Rankings must contain every query in the current split exactly once.',
    ),
    'experiment_rankings.scores': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Rankings for query {query_id} must be a document-to-score mapping.',
    ),
    'experiment_rankings.depth': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Query {query_id} exceeds retrieve_k.',
    ),
    'experiment_rankings.document': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Query {query_id} contains an unknown document: {document_id}',
    ),
    'experiment_rankings.finite_score': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Document {document_id} in query {query_id} does not have a finite numeric score.',
    ),
    'experiment_controller.dataset_digest': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Dataset artifact digest mismatch: {artifact_name}',
    ),
    'experiment_controller.result_digest': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Result artifact digest mismatch: {path}',
    ),
    'knowledge.consolidation.topic_missing': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Provide a knowledge topic to consolidate.',
    ),
    'knowledge.consolidation.notes_missing': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='At least two relevant notes owned by the current user are required for consolidation.',
    ),
    'knowledge.consolidation.draft_missing': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='A review draft could not be generated.',
    ),
    'tools.knowledge.consolidation_failed': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Topic consolidation failed.',
    ),
    'tools.research.digest_missing': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The research did not produce a digest.',
    ),
    'python_validation.filename': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Input must be a valid non-reserved flat ASCII filename of 1 to 64 characters.',
    ),
    'python_validation.program_size': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The Python program exceeds 128 KiB.',
    ),
    'python_validation.input_names': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Input filenames must not be duplicates or differ only by letter case.',
    ),
    'python_validation.input_bytes': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The Python input length or original-byte digest does not match.',
    ),
    'python_validation.deadline': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The Python deadline must be later than the acceptance time.',
    ),
    'python_validation.reservation': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The Python reservation exceeds the frozen limit or deadline.',
    ),
    'python_validation.program_identity': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The Python program identity or length is invalid.',
    ),
    'python_validation.input_total': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='Python inputs are duplicated or exceed 64 MiB.',
    ),
    'python_validation.input_owner': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='A Python Command may bind only Artifacts owned by its principal.',
    ),
    'python_validation.command_digest': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The Python Command digest does not match.',
    ),
    'experiment_validation.input_digest': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The experiment snapshot does not match the original-byte digest.',
    ),
    'experiment_validation.deadline': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The experiment deadline must be later than the acceptance time.',
    ),
    'experiment_validation.command_digest': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The experiment Command digest does not match.',
    ),
    'experiment_validation.input_owner': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='A Command must not retain references owned by other principals or tagged private.',
    ),
    'web_source.response_limit': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The web response exceeds the 4 MiB capacity; the body was not delivered.',
    ),
    'tools.knowledge.note_unavailable': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='No note accessible to this user was found.',
    ),
    'research_validation.target_category': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='A requirement gap must target the original criterion ID; other errors must target a current claim span or answer segment.',
    ),
    'verification.cited_support_rejection.explanation': PromptTranslation(
        source_version='2026-10-27.v1', version='2026-10-27.v1',
        template='The submitted evidence does not sufficiently support the listed draft claims, so they are not delivered yet. This does not prove that the source lacks support or that the claims are necessarily false. Add existing citations, obtain further evidence, or revise the conclusions and submit again. When adding citations, you may retain supported draft text; do not change facts merely to rewrite the draft.',
    ),
}
