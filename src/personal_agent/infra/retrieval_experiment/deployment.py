"""显式部署JSON解析与本地执行环境；没有动态注册或隐式下载。"""

from __future__ import annotations
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field
from personal_agent.application.retrieval_experiment.models import RetrievalDeployment
from .file_io import read_json


class LocalExperimentEnvironment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    endpoint: str = Field(min_length=1)
    network: str = Field(min_length=1)
    es_endpoint: str = Field(min_length=1)
    model_path: Path
    workspace_root: Path


class RetrievalDeploymentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    deployment: RetrievalDeployment
    environment: LocalExperimentEnvironment


def load_retrieval_deployment(
    path: Path,
) -> tuple[RetrievalDeployment, LocalExperimentEnvironment]:
    config = RetrievalDeploymentConfig.model_validate(read_json(path))
    environment = config.environment
    if (
        not environment.model_path.is_absolute()
        or not environment.workspace_root.is_absolute()
    ):
        raise ValueError("部署模型和暂存根必须使用显式绝对路径")
    if not environment.model_path.is_dir():
        raise ValueError("部署模型快照不存在")
    if environment.workspace_root.is_symlink():
        raise ValueError("实验暂存根不能是符号链接")
    return config.deployment, environment
