"""外层文件读取、原字节摘要及不可覆盖写入。"""

from __future__ import annotations
import hashlib
import json
from pathlib import Path
from pydantic import BaseModel


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"JSON 包含重复键：{key}")
        result[key] = value
    return result


def read_json(path: Path) -> object:
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_unique_object,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"非有限值：{value}")
        ),
    )


def write_json(path: Path, value: object) -> None:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    with path.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(
            value, output, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        )
        output.write("\n")


def replace_json(path: Path, value: object) -> None:
    """原子写技术执行状态；业务接受事实由Conversation Journal拥有。"""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(
            value, stream, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        )
        stream.write("\n")
        stream.flush()
        import os

        os.fsync(stream.fileno())
    temporary.replace(path)
