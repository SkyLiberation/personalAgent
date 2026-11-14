"""Immutable deployment flags, loaded once at the configuration boundary."""
from pathlib import Path
import tomllib

from pydantic import BaseModel, ConfigDict, StrictBool


class FeatureFlags(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    goal_verification: StrictBool = True
    answer_verification: StrictBool = True
    low_budget_warning: StrictBool = False


class _FeatureFlagDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    features: FeatureFlags


def load_feature_flags(path: Path = Path("config/feature_flags.toml")) -> FeatureFlags:
    with path.open("rb") as source:
        document = _FeatureFlagDocument.model_validate(tomllib.load(source))
    flags = document.features
    if flags.model_fields_set != set(FeatureFlags.model_fields):
        raise ValueError(f"feature flag 配置必须包含全部开关：{path}")
    return flags


def write_feature_flags(path: Path, flags: FeatureFlags) -> None:
    values = (f"{key} = {str(value).lower()}\n" for key, value in flags.model_dump().items())
    path.write_text("[features]\n" + "".join(values), encoding="utf-8")
