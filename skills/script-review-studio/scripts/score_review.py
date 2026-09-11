#!/usr/bin/env python3
"""Validate review evidence records and calculate scores without evaluating text."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


RULES_VERSION = "0.1.0"
MODE_COUNTS = {"V1": 12, "V2": 6, "V3": 6, "V4": 6}
CALCULATION_NOTICE = (
    "此脚本仅校验输入与核算分数，无法验证文本证据真实性，也不会自动评价剧本。"
)


def _object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path}: must be an object")
    return value


def _fields(
    value: dict[str, Any], required: set[str], allowed: set[str], path: str
) -> None:
    if not required.issubset(value):
        raise ValueError(f"{path}: missing required fields")
    if not set(value).issubset(allowed):
        raise ValueError(f"{path}: contains unsupported fields")


def _text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path}: must be a nonempty string")
    return value


def _validate_item(item: Any, path: str) -> tuple[str, int | None]:
    item = _object(item, path)
    item_fields = {"id", "status", "score_10", "evidence", "rationale"}
    _fields(item, item_fields, item_fields, path)
    item_id = _text(item["id"], f"{path}.id")
    status = _text(item["status"], f"{path}.status")
    if status not in ("scored", "insufficient"):
        raise ValueError(f"{path}.status: must be scored or insufficient")
    _text(item["rationale"], f"{path}.rationale")

    evidence = item["evidence"]
    if not isinstance(evidence, list):
        raise ValueError(f"{path}.evidence: must be an array")
    if status == "scored" and not evidence:
        raise ValueError(f"{path}.evidence: scored items require evidence")
    for index, record in enumerate(evidence):
        record_path = f"{path}.evidence[{index}]"
        record = _object(record, record_path)
        evidence_fields = {"location", "observation"}
        _fields(record, evidence_fields, evidence_fields, record_path)
        for field in evidence_fields:
            _text(record[field], f"{record_path}.{field}")

    score = item["score_10"]
    if status == "insufficient":
        if score is not None:
            raise ValueError(f"{path}.score_10: insufficient items require null")
    elif type(score) is not int or not 0 <= score <= 10:
        # bool is an int subclass; it must never count as a submitted score.
        raise ValueError(f"{path}.score_10: must be an integer from 0 to 10")
    return item_id, score


def compute_review(data: Any) -> dict[str, Any]:
    """Return mode totals or raise ValueError for an invalid 0.1.0 record.

    coverage is the assessed-item fraction (0..1). Incomplete modes have no
    full_total; their earned_points and assessed_max refer only to assessed
    items. No cross-mode total or extrapolated score is produced.
    """
    data = _object(data, "review")
    root_fields = {"rules_version", "context", "modes"}
    _fields(data, root_fields, root_fields, "review")
    if data["rules_version"] != RULES_VERSION:
        raise ValueError("review.rules_version: unsupported version; expected 0.1.0")

    context = _object(data["context"], "review.context")
    required_context = {"title", "material_type", "primary_goal"}
    optional_context = {"platform", "audience", "duration"}
    _fields(context, required_context, required_context | optional_context, "review.context")
    for field in required_context:
        _text(context[field], f"review.context.{field}")
    for field in optional_context:
        if field in context and not isinstance(context[field], str):
            raise ValueError(f"review.context.{field}: must be a string")

    modes = data["modes"]
    if not isinstance(modes, list) or not modes:
        raise ValueError("review.modes: must be a nonempty array")
    results: list[dict[str, Any]] = []
    seen_modes: set[str] = set()
    for mode_index, mode_record in enumerate(modes):
        path = f"review.modes[{mode_index}]"
        mode_record = _object(mode_record, path)
        _fields(
            mode_record,
            {"mode", "status", "items"},
            {"mode", "status", "items", "reason"},
            path,
        )
        mode = _text(mode_record["mode"], f"{path}.mode")
        if mode not in MODE_COUNTS:
            raise ValueError(f"{path}.mode: must be V1, V2, V3 or V4")
        if mode in seen_modes:
            raise ValueError(f"{path}.mode: duplicate mode")
        seen_modes.add(mode)
        status = _text(mode_record["status"], f"{path}.status")
        if status not in ("applicable", "not_applicable"):
            raise ValueError(f"{path}.status: must be applicable or not_applicable")
        items = mode_record["items"]
        if not isinstance(items, list):
            raise ValueError(f"{path}.items: must be an array")
        if "reason" in mode_record:
            _text(mode_record["reason"], f"{path}.reason")
        if status == "not_applicable":
            reason = _text(mode_record.get("reason"), f"{path}.reason")
            if items:
                raise ValueError(f"{path}.items: not_applicable requires an empty array")
            results.append({"mode": mode, "status": status, "reason": reason})
            continue

        if mode == "V4":
            for field in ("platform", "audience", "duration"):
                _text(context.get(field), f"review.context.{field} (required for V4)")

        item_count = MODE_COUNTS[mode]
        expected_ids = {f"{mode}-{index:02d}" for index in range(1, item_count + 1)}
        seen_ids: set[str] = set()
        scores: list[int] = []
        for item_index, item in enumerate(items):
            item_path = f"{path}.items[{item_index}]"
            item_id, score = _validate_item(item, item_path)
            if item_id not in expected_ids:
                raise ValueError(f"{item_path}.id: unknown dimension for this mode")
            if item_id in seen_ids:
                raise ValueError(f"{item_path}.id: duplicate dimension")
            seen_ids.add(item_id)
            if score is not None:
                scores.append(score)
        if seen_ids != expected_ids:
            raise ValueError(f"{path}.items: must list every dimension exactly once")

        multiplier = 1 if mode == "V1" else 2
        scored_count = len(scores)
        earned_points = sum(scores) * multiplier
        complete = scored_count == item_count
        result: dict[str, Any] = {
            "mode": mode,
            "status": status,
            "earned_points": earned_points,
            "assessed_max": scored_count * 10 * multiplier,
            "expected_max": 120,
            "coverage": scored_count / item_count,
            "scored_count": scored_count,
            "item_count": item_count,
            "complete": complete,
            "full_total": earned_points if complete else None,
            "lowest_score_10": min(scores) if scores else None,
        }
        if mode == "V1":
            result["qualification"] = (
                earned_points >= 108 and min(scores) >= 8
                if complete
                else None
            )
        results.append(result)

    return {
        "rules_version": RULES_VERSION,
        "context": dict(context),
        "calculation_notice": CALCULATION_NOTICE,
        "modes": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="review JSON in the 0.1.0 input format")
    parser.add_argument("--output", type=Path, help="write totals JSON to this file")
    args = parser.parse_args(argv)
    try:
        with args.input.open("r", encoding="utf-8-sig") as source:
            data = json.load(source)
        result = compute_review(data)
        rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            with args.output.open("w", encoding="utf-8", newline="\n") as destination:
                destination.write(rendered)
        else:
            # Keep Chinese labels readable even under a non-UTF-8 Windows console.
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8")
            sys.stdout.write(rendered)
    except (OSError, UnicodeError, ValueError) as error:
        print(f"score_review: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
