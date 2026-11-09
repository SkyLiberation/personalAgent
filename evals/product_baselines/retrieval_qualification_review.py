"""研究评分资格的独立审读原件；这里只校验身份与结构，不代做语义审读。"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from evals.e2e_quality.research_answer_outcome import ResearchAnswerReferenceSet

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Status = Literal["passed", "failed", "inconclusive"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SealedFile(_Strict):
    path: Path
    sha256: Digest

    def read(self, base: Path) -> bytes:
        content = (base / self.path).resolve().read_bytes()
        if sha256(content).hexdigest() != self.sha256:
            raise ValueError("资格输入文件摘要失效")
        return content


def materialize_references(content: bytes) -> ResearchAnswerReferenceSet:
    """相同封存字节在执行与准入两端产生完全相同的无标签 revision。"""
    references = ResearchAnswerReferenceSet.model_validate_json(content)
    return references.model_copy(update={"revision": sha256(content).hexdigest()})


class ReviewActor(_Strict):
    kind: Literal["human", "independent_agent"]
    identifier: str = Field(min_length=1)
    review_report: SealedFile
    accounting_note: str = Field(min_length=1)


class AnswerRange(_Strict):
    """零起点、右开区间，按完整 answer 的 Unicode 码点定位。"""
    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def ordered(self) -> AnswerRange:
        if self.end <= self.start:
            raise ValueError("审读答案范围必须非空且有序")
        return self


class ReviewedRelation(_Strict):
    relation_id: str = Field(min_length=1)
    criterion: str = Field(min_length=1)
    answer_ranges: tuple[AnswerRange, ...] = Field(min_length=1)
    reference_indices: tuple[int, ...]
    reasoning: str = Field(min_length=1)


class SourceReview(_Strict):
    version: Literal[1] = 1
    actor: ReviewActor
    user_request_sha256: Digest
    source_report_sha256: Digest
    complete_answer_sha256: Digest
    reference_set_sha256: Digest
    transformation_sha256: Digest
    expected_status: Status
    relations: tuple[ReviewedRelation, ...] = Field(min_length=1)
    complete_materials_reviewed: bool
    unresolved: tuple[str, ...]
    conclusion: str = Field(min_length=1)

    @model_validator(mode="after")
    def unique_relations(self) -> SourceReview:
        ids = [item.relation_id for item in self.relations]
        if len(ids) != len(set(ids)):
            raise ValueError("来源审读关系不能重复")
        return self

    def validate_materials(self, *, user_request: bytes, report: bytes, answer: bytes, references: bytes,
                           transformation: bytes, expected_status: Status) -> None:
        actual = tuple(sha256(item).hexdigest() for item in (user_request, report, answer, references, transformation))
        expected = (self.user_request_sha256, self.source_report_sha256, self.complete_answer_sha256,
                    self.reference_set_sha256, self.transformation_sha256)
        if actual != expected or self.expected_status != expected_status:
            raise ValueError("来源审读未绑定本次完整原件及预声明标签")
        if not self.complete_materials_reviewed or self.unresolved:
            raise ValueError("来源审读尚缺必要材料或未闭合关系")
        text = answer.decode("utf-8")
        count = len(materialize_references(references).references)
        for relation in self.relations:
            if any(item.end > len(text) for item in relation.answer_ranges):
                raise ValueError("来源审读答案位置越界")
            if (len(set(relation.reference_indices)) != len(relation.reference_indices)
                    or any(index < 1 or index > count for index in relation.reference_indices)):
                raise ValueError("来源审读参考位置越界或重复")


class RelationAccuracy(_Strict):
    relation_id: str = Field(min_length=1)
    finding_indices: tuple[int, ...]
    faithful: bool
    reasoning: str = Field(min_length=1)


class JudgmentAccuracy(_Strict):
    sample_id: str = Field(pattern=r"^q[1-6]$")
    repetition: int = Field(ge=1, le=3)
    judgment_sha256: Digest
    source_review_sha256: Digest
    relations: tuple[RelationAccuracy, ...] = Field(min_length=1)
    all_findings_faithful: bool
    conclusion: str = Field(min_length=1)


class QualificationAccuracyReview(_Strict):
    version: Literal[1] = 1
    actor: ReviewActor
    plan_sha256: Digest
    judgments: tuple[JudgmentAccuracy, ...] = Field(min_length=18, max_length=18)

    @model_validator(mode="after")
    def complete_group(self) -> QualificationAccuracyReview:
        actual = {(item.sample_id, item.repetition) for item in self.judgments}
        expected = {(f"q{index}", repetition) for index in range(1, 7) for repetition in range(1, 4)}
        if actual != expected:
            raise ValueError("准确性审读必须逐项覆盖唯一六输入、各三次原判断")
        return self


def validate_judgment_accuracy(review: JudgmentAccuracy, source: SourceReview, *,
                               judgment: bytes, source_review: bytes, findings_count: int) -> None:
    if (review.judgment_sha256 != sha256(judgment).hexdigest()
            or review.source_review_sha256 != sha256(source_review).hexdigest()):
        raise ValueError("准确性审读绑定了不同的原判断或来源关系")
    expected = {relation.relation_id for relation in source.relations}
    actual = [relation.relation_id for relation in review.relations]
    if set(actual) != expected or len(actual) != len(expected):
        raise ValueError("准确性审读没有逐项消费来源关系")
    if not review.all_findings_faithful or not all(item.faithful for item in review.relations):
        raise ValueError("判断理由或定位的独立审读未通过")
    indices = {index for relation in review.relations for index in relation.finding_indices}
    if any(index < 1 or index > findings_count for index in indices) or indices != set(range(1, findings_count + 1)):
        raise ValueError("准确性审读漏审实际 finding 或定位越界")
