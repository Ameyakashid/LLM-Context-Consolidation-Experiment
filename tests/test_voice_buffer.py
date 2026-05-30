"""Tests for voice_buffer: rotation, dedup, capacity, aging, persistence."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from voice_buffer import VoiceBuffer, VoiceLine, disco_comments_to_voice_lines

_NOW = datetime(2026, 5, 29, 12, 0)


def _vl(who: str, line: str, age_h: float = 0.0, source: str = "topup") -> VoiceLine:
    return VoiceLine(who=who, line=line, created_at=_NOW - timedelta(hours=age_h), source=source)


class _Comment:
    def __init__(self, voice_name: str, comment: str) -> None:
        self.voice_name = voice_name
        self.comment = comment


class TestAddDedupCap:
    def test_add_prepends_newest_first(self, tmp_path: Path) -> None:
        buf = VoiceBuffer(tmp_path / "vb.json")
        buf.add([_vl("LOGIC", "a")])
        buf.add([_vl("EMPATHY", "b")])
        whos = [vl.who for vl in buf.current()]
        assert whos == ["EMPATHY", "LOGIC"]  # newest first

    def test_dedup_by_who_and_line(self, tmp_path: Path) -> None:
        buf = VoiceBuffer(tmp_path / "vb.json")
        buf.add([_vl("LOGIC", "same")])
        buf.add([_vl("LOGIC", "same")])
        assert len(buf.all_lines()) == 1

    def test_capacity_trims_oldest(self, tmp_path: Path) -> None:
        buf = VoiceBuffer(tmp_path / "vb.json", capacity=3)
        buf.add([_vl("L", f"line{i}") for i in range(5)])
        assert len(buf.all_lines()) == 3

    def test_current_limit(self, tmp_path: Path) -> None:
        buf = VoiceBuffer(tmp_path / "vb.json")
        buf.add([_vl("L", f"line{i}") for i in range(10)])
        assert len(buf.current(limit=4)) == 4


class TestAging:
    def test_fresh_count_excludes_aged(self, tmp_path: Path) -> None:
        buf = VoiceBuffer(tmp_path / "vb.json", max_age=timedelta(hours=6))
        buf.add([_vl("L", "fresh", age_h=1), _vl("L", "old", age_h=10)])
        assert buf.fresh_count(_NOW) == 1

    def test_needs_topup_when_below_min(self, tmp_path: Path) -> None:
        buf = VoiceBuffer(tmp_path / "vb.json")
        buf.add([_vl("L", "only")])
        assert buf.needs_topup(_NOW, min_lines=6) is True

    def test_no_topup_when_enough_fresh(self, tmp_path: Path) -> None:
        buf = VoiceBuffer(tmp_path / "vb.json")
        buf.add([_vl("L", f"l{i}") for i in range(6)])
        assert buf.needs_topup(_NOW, min_lines=6) is False

    def test_mark_aged_removes_old(self, tmp_path: Path) -> None:
        buf = VoiceBuffer(tmp_path / "vb.json", max_age=timedelta(hours=6))
        buf.add([_vl("L", "fresh", age_h=1), _vl("L", "old", age_h=10)])
        dropped = buf.mark_aged(_NOW)
        assert dropped == 1
        assert [vl.line for vl in buf.all_lines()] == ["fresh"]


class TestPersistence:
    def test_round_trip_across_instances(self, tmp_path: Path) -> None:
        path = tmp_path / "vb.json"
        VoiceBuffer(path).add([_vl("VOLITION", "begin"), _vl("LOGIC", "finite")])
        reloaded = VoiceBuffer(path)
        assert {vl.line for vl in reloaded.all_lines()} == {"begin", "finite"}

    def test_corrupt_file_loads_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "vb.json"
        path.write_text("}{ not json", encoding="utf-8")
        assert VoiceBuffer(path).all_lines() == []

    def test_missing_file_loads_empty(self, tmp_path: Path) -> None:
        assert VoiceBuffer(tmp_path / "nope.json").all_lines() == []


class TestDiscoMapping:
    def test_maps_voice_name_uppercase_and_drops_empty(self) -> None:
        comments = [
            _Comment("logic", "3 remain"),
            _Comment("empathy", "   "),       # dropped (blank)
            _Comment("inland_empire", "drift"),
        ]
        lines = disco_comments_to_voice_lines(comments, _NOW)
        assert [(vl.who, vl.line) for vl in lines] == [
            ("LOGIC", "3 remain"),
            ("INLAND EMPIRE", "drift"),
        ]
        assert all(vl.source == "fired" for vl in lines)


def test_file_line_budget() -> None:
    mod = Path(__file__).resolve().parents[1] / "voice_buffer.py"
    assert len(mod.read_text(encoding="utf-8").splitlines()) <= 300
