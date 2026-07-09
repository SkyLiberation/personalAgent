from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class RetrievalGateThresholds:
    """Default-admission thresholds for a retrieval strategy.

    Quality metrics are compared against baselines per profile. Resource and
    grounding metrics are absolute budgets because they are product constraints,
    not benchmark-relative wins.
    """

    quality_metric_names: tuple[str, ...] = ("mrr", "recall_10", "ndcg_10")
    allowed_quality_drop: float = 0.0
    max_latency_ms: float | None = None
    max_cost_usd: float | None = None
    min_grounding_score: float | None = None
    max_harmed_fraction: float | None = None
    required_profiles: tuple[str, ...] = ("open", "galileo", "business")


@dataclass(frozen=True, slots=True)
class RetrievalGateInput:
    strategy_name: str
    metrics_by_profile: dict[str, dict[str, float]]
    baseline_by_profile: dict[str, dict[str, float]]
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    grounding_score: float = 1.0
    harmed_fraction: float = 0.0


@dataclass(frozen=True, slots=True)
class RetrievalGateDecision:
    passed: bool
    failures: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    checked_profiles: tuple[str, ...] = ()
    checked_metrics: tuple[str, ...] = ()


def evaluate_retrieval_gate(
    gate_input: RetrievalGateInput,
    thresholds: RetrievalGateThresholds | None = None,
) -> RetrievalGateDecision:
    thresholds = thresholds or RetrievalGateThresholds()
    failures: list[str] = []
    warnings: list[str] = []
    checked_profiles: list[str] = []

    for profile in thresholds.required_profiles:
        current = gate_input.metrics_by_profile.get(profile)
        baseline = gate_input.baseline_by_profile.get(profile)
        if current is None:
            failures.append(f"missing current metrics for profile={profile}")
            continue
        if baseline is None:
            failures.append(f"missing baseline metrics for profile={profile}")
            continue
        checked_profiles.append(profile)
        for metric_name in thresholds.quality_metric_names:
            if metric_name not in current:
                failures.append(f"missing current metric {profile}.{metric_name}")
                continue
            if metric_name not in baseline:
                failures.append(f"missing baseline metric {profile}.{metric_name}")
                continue
            floor = float(baseline[metric_name]) - thresholds.allowed_quality_drop
            observed = float(current[metric_name])
            if observed < floor:
                failures.append(
                    f"{profile}.{metric_name} regressed: observed={observed:.4f} floor={floor:.4f}"
                )

    if thresholds.max_latency_ms is not None and gate_input.latency_ms > thresholds.max_latency_ms:
        failures.append(
            f"latency_ms over budget: observed={gate_input.latency_ms:.2f} "
            f"budget={thresholds.max_latency_ms:.2f}"
        )
    if thresholds.max_cost_usd is not None and gate_input.cost_usd > thresholds.max_cost_usd:
        failures.append(
            f"cost_usd over budget: observed={gate_input.cost_usd:.6f} "
            f"budget={thresholds.max_cost_usd:.6f}"
        )
    if (
        thresholds.min_grounding_score is not None
        and gate_input.grounding_score < thresholds.min_grounding_score
    ):
        failures.append(
            f"grounding_score below floor: observed={gate_input.grounding_score:.4f} "
            f"floor={thresholds.min_grounding_score:.4f}"
        )
    if (
        thresholds.max_harmed_fraction is not None
        and gate_input.harmed_fraction > thresholds.max_harmed_fraction
    ):
        failures.append(
            f"harmed_fraction over budget: observed={gate_input.harmed_fraction:.4f} "
            f"budget={thresholds.max_harmed_fraction:.4f}"
        )
    if not failures and gate_input.harmed_fraction > 0:
        warnings.append(
            f"harmed queries present but within budget: fraction={gate_input.harmed_fraction:.4f}"
        )

    return RetrievalGateDecision(
        passed=not failures,
        failures=tuple(failures),
        warnings=tuple(warnings),
        checked_profiles=tuple(checked_profiles),
        checked_metrics=thresholds.quality_metric_names,
    )


def gate_payload(decision: RetrievalGateDecision) -> dict[str, object]:
    return {
        "passed": decision.passed,
        "failures": list(decision.failures),
        "warnings": list(decision.warnings),
        "checked_profiles": list(decision.checked_profiles),
        "checked_metrics": list(decision.checked_metrics),
    }


def build_gate_input_from_eval_results(
    *,
    strategy_name: str,
    current_by_profile: dict[str, Any],
    baseline_by_profile: dict[str, Any],
    strategy_by_profile: dict[str, str] | None = None,
    baseline_strategy_by_profile: dict[str, str] | None = None,
    latency_ms: float = 0.0,
    cost_usd: float = 0.0,
    grounding_score: float = 1.0,
    harmed_fraction: float = 0.0,
) -> RetrievalGateInput:
    strategy_by_profile = strategy_by_profile or {}
    baseline_strategy_by_profile = baseline_strategy_by_profile or strategy_by_profile
    return RetrievalGateInput(
        strategy_name=strategy_name,
        metrics_by_profile={
            profile: _quality_metrics_from_result(
                _find_result(payload, strategy_by_profile.get(profile, strategy_name))
            )
            for profile, payload in current_by_profile.items()
        },
        baseline_by_profile={
            profile: _quality_metrics_from_result(
                _find_result(payload, baseline_strategy_by_profile.get(profile, strategy_name))
            )
            for profile, payload in baseline_by_profile.items()
        },
        latency_ms=latency_ms,
        cost_usd=cost_usd,
        grounding_score=grounding_score,
        harmed_fraction=harmed_fraction,
    )


def load_eval_results(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _find_result(payload: Any, strategy_name: str) -> dict[str, Any]:
    if isinstance(payload, dict) and payload.get("strategy") == strategy_name:
        return payload
    if isinstance(payload, dict) and "results" in payload:
        return _find_result(payload["results"], strategy_name)
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict) and item.get("strategy") == strategy_name:
                return item
    raise ValueError(f"strategy '{strategy_name}' not found in eval payload")


def _quality_metrics_from_result(result: dict[str, Any]) -> dict[str, float]:
    metrics = _float_metrics(result.get("metrics") or {})
    utilized = _float_metrics(result.get("utilized_metrics") or {})
    if not utilized:
        return metrics
    merged = dict(metrics)
    for key, value in utilized.items():
        if key in merged:
            merged[key] = min(float(merged[key]), float(value))
        else:
            merged[f"utilized_{key}"] = float(value)
    return merged


def _float_metrics(raw: Any) -> dict[str, float]:
    if not isinstance(raw, dict):
        return {}
    metrics: dict[str, float] = {}
    for key, value in raw.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float):
            metrics[str(key)] = float(value)
    return metrics


def _parse_profile_paths(values: list[str] | None) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for value in values or []:
        if "=" not in value:
            raise ValueError(f"profile path must be PROFILE=PATH, got {value!r}")
        profile, path = value.split("=", 1)
        profile = profile.strip()
        if not profile:
            raise ValueError(f"profile path must include profile name, got {value!r}")
        paths[profile] = Path(path)
    return paths


def _parse_profile_values(values: list[str] | None) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for value in values or []:
        if "=" not in value:
            raise ValueError(f"profile value must be PROFILE=VALUE, got {value!r}")
        profile, raw = value.split("=", 1)
        profile = profile.strip()
        raw = raw.strip()
        if not profile or not raw:
            raise ValueError(f"profile value must include both profile and value, got {value!r}")
        parsed[profile] = raw
    return parsed


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate a retrieval strategy against cross-profile gates.")
    parser.add_argument("--strategy", required=True)
    parser.add_argument(
        "--profile-strategy",
        action="append",
        default=[],
        metavar="PROFILE=STRATEGY",
        help="Strategy name override for a profile when benchmark runners use different names.",
    )
    parser.add_argument(
        "--baseline-profile-strategy",
        action="append",
        default=[],
        metavar="PROFILE=STRATEGY",
        help="Baseline strategy name override for a profile. Defaults to --profile-strategy.",
    )
    parser.add_argument(
        "--current",
        action="append",
        default=[],
        metavar="PROFILE=PATH",
        help="Current eval JSON payload for a profile, e.g. open=evals/open_ragbench/results/latest.json",
    )
    parser.add_argument(
        "--baseline",
        action="append",
        default=[],
        metavar="PROFILE=PATH",
        help="Baseline eval JSON payload for a profile.",
    )
    parser.add_argument("--required-profile", action="append", dest="required_profiles", default=None)
    parser.add_argument("--allowed-quality-drop", type=float, default=0.0)
    parser.add_argument("--max-latency-ms", type=float, default=None)
    parser.add_argument("--max-cost-usd", type=float, default=None)
    parser.add_argument("--min-grounding-score", type=float, default=None)
    parser.add_argument("--max-harmed-fraction", type=float, default=None)
    parser.add_argument("--latency-ms", type=float, default=0.0)
    parser.add_argument("--cost-usd", type=float, default=0.0)
    parser.add_argument("--grounding-score", type=float, default=1.0)
    parser.add_argument("--harmed-fraction", type=float, default=0.0)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    current_paths = _parse_profile_paths(args.current)
    baseline_paths = _parse_profile_paths(args.baseline)
    strategy_by_profile = _parse_profile_values(args.profile_strategy)
    baseline_strategy_by_profile = (
        _parse_profile_values(args.baseline_profile_strategy)
        or strategy_by_profile
    )
    gate_input = build_gate_input_from_eval_results(
        strategy_name=args.strategy,
        current_by_profile={
            profile: load_eval_results(path)
            for profile, path in current_paths.items()
        },
        baseline_by_profile={
            profile: load_eval_results(path)
            for profile, path in baseline_paths.items()
        },
        strategy_by_profile=strategy_by_profile,
        baseline_strategy_by_profile=baseline_strategy_by_profile,
        latency_ms=args.latency_ms,
        cost_usd=args.cost_usd,
        grounding_score=args.grounding_score,
        harmed_fraction=args.harmed_fraction,
    )
    thresholds = RetrievalGateThresholds(
        allowed_quality_drop=args.allowed_quality_drop,
        max_latency_ms=args.max_latency_ms,
        max_cost_usd=args.max_cost_usd,
        min_grounding_score=args.min_grounding_score,
        max_harmed_fraction=args.max_harmed_fraction,
        required_profiles=tuple(args.required_profiles or ("open", "galileo", "business")),
    )
    decision = evaluate_retrieval_gate(gate_input, thresholds)
    payload = gate_payload(decision)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not decision.passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
