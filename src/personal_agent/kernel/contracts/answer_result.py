"""Deployment-owned answer composition, shared by configuration and run binding."""

from pydantic import BaseModel, ConfigDict, SerializerFunctionWrapHandler, StrictBool, model_serializer


class AnswerResultConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    test_mode: StrictBool = False

    @model_serializer(mode="wrap")
    def _serialize(self, handler: SerializerFunctionWrapHandler):
        data = handler(self)
        # Preserve the identity of earlier ordinary-mode evaluation configurations.
        if not self.test_mode:
            data.pop("test_mode", None)
        return data
