"""运行 ``python -m scripts.retrieval_experiment --help`` 查看独立工具入口。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from personal_agent.application.retrieval_experiment.contracts import (
    BM25Config,
    CandidateConfig,
    DenseConfig,
    RRFConfig,
)
from personal_agent.infra.retrieval_experiment.controller import (
    ExecutionEnvironment,
    freeze,
    load_result,
    rescore,
    run_baseline,
    run_candidate,
    run_rrf,
    run_test,
)
from personal_agent.infra.retrieval_experiment.retrieval import prepare_data


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="独立检索实验工具：真实执行、隔离候选、外部评分；不接入 Agent Runtime"
    )
    commands = root.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser(
        "prepare", help="校验原 Parquet/TSV 并创建不可覆盖的数据快照"
    )
    prepare.add_argument("--corpus", type=Path, required=True)
    prepare.add_argument("--queries", type=Path, required=True)
    prepare.add_argument("--qrels", type=Path, required=True)
    prepare.add_argument("--split", choices=["train", "test"], required=True)
    prepare.add_argument("--output", type=Path, required=True)
    frozen = commands.add_parser(
        "freeze", help="从实际开发结果冻结确切方案与输入生成规则"
    )
    frozen.add_argument("--result", type=Path, required=True)
    frozen.add_argument("--inputs", type=Path, nargs="*", default=[])
    frozen.add_argument("--output", type=Path, required=True)
    reproduce = commands.add_parser(
        "reproduce", help="从已解压交付清单及受信本地部署在新目录复现"
    )
    reproduce.add_argument("--manifest", type=Path, required=True)
    reproduce.add_argument("--output", type=Path, required=True)
    for name, help_text in (
        ("run", "执行一个 train 基线配置"),
        ("rrf", "执行固定 RRF(60)"),
        ("program", "隔离执行单文件候选，确认终态后独立评分"),
        ("score", "独立复算已有完整结果"),
        ("test", "执行冻结方案的完整 test"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument(
            "--endpoint", required=True, help="显式 Docker Engine endpoint"
        )
        command.add_argument(
            "--image", required=True, help="已预备的受信 worker 镜像，运行时不拉取"
        )
        command.add_argument(
            "--dataset", type=Path, required=True, help="prepare 产生的 manifest.json"
        )
        command.add_argument(
            "--output", type=Path, required=True, help="尚不存在的新目录"
        )
        if name in {"run", "test"}:
            command.add_argument(
                "--network", default="none", help="BM25 的专用实验网络，其余使用 none"
            )
            command.add_argument("--es-endpoint")
            command.add_argument("--model", type=Path)
            command.add_argument("--model-revision")
        if name in {"run", "rrf", "program"}:
            command.add_argument("--retrieve-k", type=int, default=100)
        if name == "run":
            command.add_argument("--method", choices=["bm25", "dense"], required=True)
        if name in {"rrf", "program", "test"}:
            command.add_argument("--inputs", type=Path, nargs="+", default=[])
        if name in {"program", "test"}:
            command.add_argument("--candidate-image", required=name == "program")
        if name == "program":
            command.add_argument("--program", type=Path, required=True)
            command.add_argument("--config", type=Path)
            command.add_argument("--timeout", type=int, default=60)
        if name == "score":
            command.add_argument("--result", type=Path, required=True)
        if name == "test":
            command.add_argument("--frozen", type=Path, required=True)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "prepare":
            path = prepare_data(
                args.corpus, args.queries, args.qrels, args.split, args.output
            )
        elif args.command == "freeze":
            path = freeze(args.result, args.inputs, args.output)
        elif args.command == "reproduce":
            from personal_agent.infra.retrieval_experiment.reproduction import (
                reproduce_from_settings,
            )

            path = reproduce_from_settings(args.manifest, args.output)
        else:
            environment = ExecutionEnvironment(
                endpoint=args.endpoint,
                image=args.image,
                network=getattr(args, "network", "none"),
                es_endpoint=getattr(args, "es_endpoint", None),
                model_path=getattr(args, "model", None),
                model_revision=getattr(args, "model_revision", None),
            )
            if args.command == "run":
                configuration = (
                    BM25Config(method="bm25", retrieve_k=args.retrieve_k)
                    if args.method == "bm25"
                    else DenseConfig(method="dense", retrieve_k=args.retrieve_k)
                )
                path = run_baseline(
                    args.dataset, args.output, configuration, environment
                )
            elif args.command == "rrf":
                path = run_rrf(
                    args.dataset,
                    args.inputs,
                    args.output,
                    RRFConfig(method="rrf", retrieve_k=args.retrieve_k),
                    environment,
                )
            elif args.command == "program":
                path = run_candidate(
                    args.dataset,
                    args.inputs,
                    args.program,
                    args.config,
                    args.candidate_image,
                    args.output,
                    CandidateConfig(method="candidate", retrieve_k=args.retrieve_k),
                    environment,
                    timeout_seconds=args.timeout,
                )
            elif args.command == "score":
                path = rescore(args.dataset, args.result, args.output, environment)
            else:
                path = run_test(
                    args.frozen,
                    args.dataset,
                    args.inputs,
                    args.output,
                    environment,
                    args.candidate_image,
                )
        summary: dict[str, object] = {"artifact": str(path.resolve())}
        if path.name == "result.json":
            result = load_result(path)
            summary.update(
                status=result.status,
                config=result.config.model_dump(mode="json"),
                metrics=result.metrics.model_dump(mode="json"),
            )
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    except Exception as error:
        print(f"实验工具失败：{type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
