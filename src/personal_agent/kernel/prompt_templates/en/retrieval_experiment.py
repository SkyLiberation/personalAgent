"""English instructions for retrieval experiments and published results."""

from personal_agent.kernel.prompt_registry import PromptTranslation


TRANSLATIONS = {
    "retrieval_experiment.description": PromptTranslation(
        'v2-result-publication-md1', 'v2-result-publication-en.1-md1',
        """

## Purpose and results
Run development experiments, freeze exact results, or evaluate a frozen approach in the offline deployment authorized for this task. Combinations consume only actual result references; candidate consumes program_ref saved for this task and optional config_ref. Return the real status, a metric summary, and formal artifact references; failure or unknown status does not mean completion.

## Result references
receipt.result_refs and summaries.result_ref point to the business result experiment.json. Use these references for combination input_result_refs and freezing selected_result_ref. summary.publication is read-only content from that original business result; raw_result_ref, rankings_ref, metrics_ref, and similar fields point to subfiles from the same experiment. The existence of subfiles or a saved program does not represent another execution. Read the corresponding references when specific configuration or body content is needed.

## Program inputs
Candidate programs always start with python -I /inputs/program.py /inputs, where argv[1] is the read-only input directory. rankings_0.json, rankings_1.json, and so on are provided in input_result_refs order; each maps query_id → doc_id → finite numeric score. queries.json maps query_id → original query text, corpus_ids.json is an array of valid document IDs, and config.json is also present when config_ref is supplied. Only the Python standard library is available; network access and dependency installation are prohibited, and inputs contain no grading labels.

## Output and diagnostics
stdout must contain only ranking JSON of the same shape, covering all current queries, with at most this run's retrieve_k valid documents per query; empty rankings are allowed. Do not append metrics, logs, or completion claims. Write diagnostics to stderr. In failure receipts, diagnostic_refs point to actual execution facts and available bounded output; read them as needed and interpret them together with limitations. Logs do not represent valid rankings or scoring results.""",
    ),
}
