"""Read explicit execution permission and native sandbox deployment."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from personal_agent.application.bash_execution.models import BashExecutionAuthorization


class BashExecutionDeploymentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    authorization: BashExecutionAuthorization


def load_bash_deployment(path: Path) -> BashExecutionDeploymentConfig:
    if path.is_symlink():
        raise ValueError("Bash部署配置不得为符号链接")
    return BashExecutionDeploymentConfig.model_validate_json(path.read_bytes())
