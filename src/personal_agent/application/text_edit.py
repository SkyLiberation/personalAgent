"""Typed arguments for exact edits of existing UTF-8 files."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .literal_replacement import replace_literal


class LiteralTextEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    file_path: str = Field(min_length=1, max_length=4096)
    old_string: str = Field(min_length=1)
    new_string: str
    replace_all: bool = False

    @model_validator(mode="after")
    def validate_edit(self) -> Self:
        if self.old_string == self.new_string:
            raise ValueError("old_string and new_string must differ")
        for value in (self.file_path, self.old_string, self.new_string):
            value.encode("utf-8")
        return self

    def replace(self, content: bytes, *, max_bytes: int) -> tuple[bytes, int]:
        return replace_literal(content, self.old_string.encode("utf-8"), self.new_string.encode("utf-8"),
                               self.replace_all, max_bytes)
