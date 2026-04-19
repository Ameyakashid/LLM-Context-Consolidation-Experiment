"""Response-parsing tests for the Dream engine."""

from __future__ import annotations

import json

import pytest

from dream_helpers import parse_consolidation_response
from dream_types import MAX_CONTENT_CHARS, DreamParseError


def _ok_payload(
    insights: list[dict[str, object]] | None = None,
    resolves: list[str] | None = None,
) -> str:
    return json.dumps(
        {
            "insights": insights or [],
            "entries_to_resolve": resolves or [],
        }
    )


class TestParseHappyPath:
    def test_single_insight_accepted(self) -> None:
        payload = _ok_payload(
            insights=[{
                "category": "commitment",
                "content": "keep writing tests",
                "metadata": {"confidence": "high"},
                "supersedes_id": "",
            }],
        )
        out = parse_consolidation_response(payload, frozenset())
        assert len(out.insights) == 1
        assert out.insights[0].category == "commitment"
        assert out.insights[0].content == "keep writing tests"
        assert out.insights[0].metadata == {"confidence": "high"}

    def test_resolve_known_id_accepted(self) -> None:
        payload = _ok_payload(resolves=["known-id"])
        out = parse_consolidation_response(payload, frozenset({"known-id"}))
        assert out.resolves == ["known-id"]
        assert out.dropped == []

    def test_empty_output_valid(self) -> None:
        out = parse_consolidation_response(_ok_payload(), frozenset())
        assert out.insights == []
        assert out.resolves == []
        assert out.dropped == []

    def test_all_five_categories_accepted(self) -> None:
        insights: list[dict[str, object]] = [
            {"category": c, "content": f"sample {c}",
             "metadata": {}, "supersedes_id": ""}
            for c in ("commitment", "deadline", "blocker",
                      "energy_state", "context_switch")
        ]
        out = parse_consolidation_response(_ok_payload(insights), frozenset())
        assert len(out.insights) == 5


class TestParseMalformed:
    def test_not_json_raises(self) -> None:
        with pytest.raises(DreamParseError, match="not valid JSON"):
            parse_consolidation_response("not json at all", frozenset())

    def test_root_not_object_raises(self) -> None:
        with pytest.raises(DreamParseError, match="must be a JSON object"):
            parse_consolidation_response("[1, 2, 3]", frozenset())

    def test_missing_insights_key_raises(self) -> None:
        payload = json.dumps({"entries_to_resolve": []})
        with pytest.raises(DreamParseError, match="top-level"):
            parse_consolidation_response(payload, frozenset())

    def test_missing_resolves_key_raises(self) -> None:
        payload = json.dumps({"insights": []})
        with pytest.raises(DreamParseError, match="top-level"):
            parse_consolidation_response(payload, frozenset())


class TestParseInsightValidation:
    def test_unknown_category_dropped(self) -> None:
        payload = _ok_payload(insights=[{
            "category": "made_up",
            "content": "x",
            "metadata": {},
            "supersedes_id": "",
        }])
        out = parse_consolidation_response(payload, frozenset())
        assert out.insights == []
        assert any("unknown_category" in reason for _, reason in out.dropped)

    def test_empty_content_dropped(self) -> None:
        payload = _ok_payload(insights=[{
            "category": "commitment",
            "content": "   ",
            "metadata": {},
            "supersedes_id": "",
        }])
        out = parse_consolidation_response(payload, frozenset())
        assert out.insights == []
        assert any("empty_content" in reason for _, reason in out.dropped)

    def test_oversize_content_dropped(self) -> None:
        payload = _ok_payload(insights=[{
            "category": "commitment",
            "content": "x" * (MAX_CONTENT_CHARS + 1),
            "metadata": {},
            "supersedes_id": "",
        }])
        out = parse_consolidation_response(payload, frozenset())
        assert out.insights == []
        assert any("oversize_content" in reason for _, reason in out.dropped)

    def test_non_dict_insight_dropped(self) -> None:
        payload = _ok_payload(insights=["not an object"])  # type: ignore[list-item]
        out = parse_consolidation_response(payload, frozenset())
        assert out.insights == []
        assert any("not_an_object" in reason for _, reason in out.dropped)

    def test_max_insights_enforced(self) -> None:
        insights: list[dict[str, object]] = [
            {"category": "commitment", "content": f"item {i}",
             "metadata": {}, "supersedes_id": ""}
            for i in range(20)
        ]
        out = parse_consolidation_response(_ok_payload(insights), frozenset())
        assert len(out.insights) == 10

    def test_metadata_coerced_to_strings(self) -> None:
        payload = _ok_payload(insights=[{
            "category": "commitment",
            "content": "numeric meta",
            "metadata": {"count": 3, "active": True, "nope": None},
            "supersedes_id": "",
        }])
        out = parse_consolidation_response(payload, frozenset())
        assert out.insights[0].metadata["count"] == "3"
        assert out.insights[0].metadata["active"] == "true"
        assert out.insights[0].metadata["nope"] == ""


class TestParseResolveValidation:
    def test_phantom_id_dropped(self) -> None:
        out = parse_consolidation_response(
            _ok_payload(resolves=["ghost-id"]),
            frozenset({"real-id"}),
        )
        assert out.resolves == []
        assert any("phantom_id" in reason for _, reason in out.dropped)

    def test_non_string_resolve_id_dropped(self) -> None:
        out = parse_consolidation_response(
            _ok_payload(resolves=[123]),  # type: ignore[list-item]
            frozenset({"real-id"}),
        )
        assert out.resolves == []
        assert any("non_string_resolve_id" in reason for _, reason in out.dropped)
