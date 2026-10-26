"""Read explicit execution permission and local Docker environment."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from personal_agent.application.python_execution.models import PythonExecutionAuthorization


class PythonExecutionDeploymentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    authorization: PythonExecutionAuthorization
    endpoint: str = Field(min_length=1)


def load_python_deployment(path: Path) -> PythonExecutionDeploymentConfig:
    if path.is_symlink():
        raise ValueError("Python部署配置不得为符号链接")
    return PythonExecutionDeploymentConfig.model_validate_json(path.read_bytes())
