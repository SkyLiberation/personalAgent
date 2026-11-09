"""固定 LongDS 材料；分析答案与参考代码只留在评测私有目录。"""

from __future__ import annotations

from hashlib import sha1, sha256
import json
from pathlib import Path
from typing import Literal
from urllib.request import urlopen

from pydantic import BaseModel, ConfigDict, Field, model_validator


DATASET_REVISION = "6b448459c333ecc050a2e89fcc65c0e044d763ac"
TASK_NAME = "business/netflix_movies_and_tv_shows/task3"
SOURCE_HASHES = {
    "task.json": "3df0afb9bbce7e7f1c9a47070eeca2cb09820b324169ece10cfac09b995e14f3",
    "input-tree.json": "f46c155d168f088c6ebd4cbdde0df0b0ab763718aa222033f60cfe6c626c3c08",
}


class LongDSTurn(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    turn_id: int = Field(ge=1, le=50, strict=True)
    context: str
    question: str = Field(min_length=1)

    def user_message(self, *, language: Literal["zh", "en"] = "zh") -> str:
        if language == "en":
            return f"Context:\n{self.context}\n\nQuestion:\n{self.question}"
        return f"分析条件：\n{self.context}\n\n本轮问题：\n{self.question}"


class LongDSInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    filename: str = Field(pattern=r"^[A-Za-z0-9_][A-Za-z0-9_. -]*$")
    bytes: int = Field(gt=0)
    git_blob: str = Field(pattern=r"^[0-9a-f]{40}$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    url: str


class LongDSPreparation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    task: str = Field(default=TASK_NAME, pattern=r"^[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+/task[0-9]+$")
    dataset_revision: str = DATASET_REVISION
    turns: tuple[LongDSTurn, ...]
    inputs: tuple[LongDSInput, ...]
    english_source_sha256: str
    chinese_source_sha256: str | None = None
    language: Literal["zh", "en"] = "zh"

    @model_validator(mode="after")
    def require_complete_source(self) -> LongDSPreparation:
        if self.dataset_revision != DATASET_REVISION:
            raise ValueError("材料必须使用固定的 LongDS 数据版本")
        if not self.turns or tuple(t.turn_id for t in self.turns) != tuple(range(1, len(self.turns) + 1)):
            raise ValueError("完整题面必须从第1轮连续编号")
        if not self.inputs or len({x.filename.casefold() for x in self.inputs}) != len(self.inputs):
            raise ValueError("必须包含不同名称的数据文件")
        if self.task == TASK_NAME and self.language == "zh":
            if len(self.turns) != 36 or len(self.inputs) != 16 or sum(x.bytes for x in self.inputs) != 3_454_619:
                raise ValueError("已有中文task3的轮数或数据身份不符")
        return self


def json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")


def seal(directory: Path) -> None:
    files = {
        p.relative_to(directory).as_posix(): sha256(p.read_bytes()).hexdigest()
        for p in sorted(directory.rglob("*"))
        if p.is_file() and p.name != "checksums.json"
    }
    with (directory / "checksums.json").open("xb") as stream:
        stream.write(json_bytes(files))


def verify_seal(directory: Path) -> None:
    hashes = json.loads((directory / "checksums.json").read_bytes())
    for name, expected in hashes.items():
        path = (directory / name).resolve()
        if not path.is_relative_to(directory.resolve()):
            raise ValueError("材料清单路径越界")
        if sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"材料校验和不符：{name}")


def verify_preparation(directory: Path) -> LongDSPreparation:
    verify_seal(directory)
    prepared = LongDSPreparation.model_validate_json((directory / "preparation.json").read_bytes())
    english = (directory / "evaluator-private/task.json").read_bytes()
    if sha256(english).hexdigest() != prepared.english_source_sha256:
        raise ValueError("英文原题校验和不符")
    references = json.loads(english)
    if len(references) != len(prepared.turns):
        raise ValueError("题面与原始参考轮数不符")
    if prepared.language == "en" and tuple(
        LongDSTurn.model_validate({key: row[key] for key in ("turn_id", "context", "question")})
        for row in references
    ) != prepared.turns:
        raise ValueError("英文题面必须逐字等于官方原稿")
    for item in prepared.inputs:
        data = (directory / "data" / item.filename).read_bytes()
        if len(data) != item.bytes or sha256(data).hexdigest() != item.sha256:
            raise ValueError(f"实际输入已变化：{item.filename}")
    return prepared


def prepare(directory: Path, *, source_directory: Path) -> LongDSPreparation:
    """只准备原题与原始数据，不执行参考程序或计算分析中间结果。"""
    source: dict[str, bytes] = {}
    for filename, expected in SOURCE_HASHES.items():
        data = (source_directory / filename).read_bytes()
        if sha256(data).hexdigest() != expected:
            raise ValueError(f"来源归档身份不符：{filename}")
        source[filename] = data
    english = json.loads(source["task.json"])
    if [row["turn_id"] for row in english] != list(range(1, 37)):
        raise ValueError("英文原题轮数或顺序不符")
    translation_path = Path(__file__).with_name("longds_zh.json")
    translation = translation_path.read_bytes()
    turns = tuple(LongDSTurn.model_validate(row) for row in json.loads(translation))
    directory.mkdir(parents=True, exist_ok=False)
    private = directory / "evaluator-private"
    private.mkdir()
    (private / "task.json").write_bytes(source["task.json"])
    data_directory = directory / "data"
    data_directory.mkdir()
    inputs: list[LongDSInput] = []
    for row in json.loads(source["input-tree.json"]):
        path = row["path"]
        if row["type"] != "file" or not path.startswith(f"data/longds/{TASK_NAME}/data/"):
            raise ValueError("数据树出现未准入路径")
        filename = Path(path).name
        url = f"https://huggingface.co/datasets/zjunlp/LongDS/resolve/{DATASET_REVISION}/{path}"
        with urlopen(url, timeout=60) as response:
            content = response.read()
        blob = sha1(f"blob {len(content)}\0".encode() + content).hexdigest()
        if len(content) != row["size"] or blob != row["oid"]:
            raise ValueError(f"数据字节或 Git blob 不符：{filename}")
        item = LongDSInput(filename=filename, bytes=len(content), git_blob=blob,
                           sha256=sha256(content).hexdigest(), url=url)
        (data_directory / item.filename).write_bytes(content)
        inputs.append(item)
    prepared = LongDSPreparation(
        turns=turns, inputs=tuple(inputs), english_source_sha256=SOURCE_HASHES["task.json"],
        chinese_source_sha256=sha256(translation).hexdigest(),
    )
    (directory / "preparation.json").write_text(prepared.model_dump_json(indent=2), encoding="utf-8")
    (directory / "prompts.zh.json").write_bytes(translation)
    (directory / "prompts.en.json").write_bytes(json_bytes([
        {key: row[key] for key in ("turn_id", "context", "question")} for row in english
    ]))
    seal(directory)
    return verify_preparation(directory)
