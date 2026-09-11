#!/usr/bin/env python3
"""Search the local review knowledge index; no network or third-party packages."""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any


MODE_COUNTS = {"V1": 12, "V2": 6, "V3": 6, "V4": 6}
DEFAULT_KNOWLEDGE_DIR = Path(__file__).resolve().parents[1] / "knowledge"
NOTICE = "相关度仅用于本地检索排序，不是作品评分或判断置信度；未命中时不补造来源。"
SEARCH_FIELDS = (("tags", 14), ("aliases", 14), ("title", 10), ("summary", 4))


def _text(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{location}: must be a nonempty string")
    return value


def _texts(value: Any, location: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{location}: must be an array of strings")
    for item in value:
        _text(item, location)
    return value


def _dimension(value: Any, location: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"V[1-4]-\d{2}", value):
        raise ValueError(f"{location}: expected a dimension such as V2-02")
    mode, number = value.split("-")
    if not 1 <= int(number) <= MODE_COUNTS[mode]:
        raise ValueError(f"{location}: dimension outside the {mode} range")
    return value


def _safe_path(root: Path, relative: Any, location: str) -> Path:
    relative = _text(relative, location)
    # Interpret both separators on all operating systems, including Windows drives.
    normalized = relative.replace("\\", "/")
    portable = PurePosixPath(normalized)
    windows = PureWindowsPath(relative)
    if portable.is_absolute() or windows.drive or ".." in portable.parts:
        raise ValueError(f"{location}: expected a relative path inside knowledge-dir")
    resolved = (root / Path(*portable.parts)).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"{location}: path escapes knowledge-dir")
    if not resolved.is_file():
        raise ValueError(f"{location}: knowledge file does not exist")
    return resolved


def _read_index(root: Path) -> dict[str, Any]:
    index_path = _safe_path(root, "index.json", "index")
    try:
        data = json.loads(index_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"index: cannot read valid UTF-8 JSON ({type(exc).__name__})") from exc
    if not isinstance(data, dict):
        raise ValueError("index: expected an object")
    _text(data.get("knowledge_version"), "index.knowledge_version")
    if not isinstance(data.get("cards"), list):
        raise ValueError("index.cards: expected an array")
    seen_ids: set[str] = set()
    for number, card in enumerate(data["cards"]):
        where = f"index.cards[{number}]"
        if not isinstance(card, dict):
            raise ValueError(f"{where}: expected an object")
        card_id = _text(card.get("id"), f"{where}.id")
        if not re.fullmatch(r"[KC]\d{2,}", card_id) or card_id in seen_ids:
            raise ValueError(f"{where}.id: expected a unique Kxx or Cxx identifier")
        seen_ids.add(card_id)
        _text(card.get("title"), f"{where}.title")
        _text(card.get("summary"), f"{where}.summary")
        _safe_path(root, card.get("path"), f"{where}.path")
        if card.get("kind") not in ("reference", "case"):
            raise ValueError(f"{where}.kind: expected reference or case")
        modes = _texts(card.get("modes"), f"{where}.modes")
        if not modes or any(mode not in MODE_COUNTS for mode in modes):
            raise ValueError(f"{where}.modes: expected V1, V2, V3 or V4")
        for dimension in _texts(card.get("dimensions"), f"{where}.dimensions"):
            _dimension(dimension, f"{where}.dimensions")
            if dimension.split("-")[0] not in modes:
                raise ValueError(f"{where}.dimensions: dimension mode is not in modes")
        for field in ("tags", "aliases"):
            _texts(card.get(field), f"{where}.{field}")
        if not isinstance(card.get("sources"), list):
            raise ValueError(f"{where}.sources: expected an array")
        for source in card["sources"]:
            if not isinstance(source, dict):
                raise ValueError(f"{where}.sources: expected source objects")
            for field in ("title", "url", "checked"):
                _text(source.get(field), f"{where}.sources.{field}")
    return data


def _normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _bigrams(text: str) -> set[str]:
    return {
        run[index : index + 2]
        for run in re.findall(r"[\u3400-\u9fff]+", text)
        for index in range(len(run) - 1)
    }


def _meaningful(text: str) -> bool:
    return bool(_bigrams(text) or re.search(r"[a-z0-9]{2,}", text))


def _contains(needle: str, haystack: str) -> bool:
    if re.fullmatch(r"[a-z0-9 ]+", needle):
        return re.search(r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])", haystack) is not None
    return needle in haystack


def _rank(card: dict[str, Any], query: str) -> tuple[float, list[str]]:
    query_grams = _bigrams(query)
    query_words = set(re.findall(r"[a-z0-9]{2,}", query))
    matched_grams: set[str] = set()
    matched_words: set[str] = set()
    exact_match = False
    score = 0.0
    reasons: list[str] = []
    for field, weight in SEARCH_FIELDS:
        values = card[field] if isinstance(card[field], list) else [card[field]]
        field_score = 0.0
        field_grams: set[str] = set()
        field_words: set[str] = set()
        full_matches: list[str] = []
        for value in values:
            normalized = _normalize(value)
            if not _meaningful(normalized):
                continue
            grams = query_grams & _bigrams(normalized)
            words = query_words & set(re.findall(r"[a-z0-9]{2,}", normalized))
            field_grams.update(grams)
            field_words.update(words)
            if _contains(normalized, query) or _contains(query, normalized):
                exact_match = True
                full_matches.append(value)
                field_score += weight * 3
        matched_grams.update(field_grams)
        matched_words.update(field_words)
        field_score += weight * (min(len(field_grams), 8) + min(len(field_words), 4)) / 4
        if full_matches:
            reasons.append(f"{field}: 词条匹配「{'、'.join(full_matches[:3])}」")
        elif field_grams or field_words:
            matches = sorted(field_grams | field_words)
            reasons.append(f"{field}: 片段匹配「{'、'.join(matches[:8])}」")
        score += field_score
    # A lone incidental two-character fragment in prose is too weak to retrieve.
    if not exact_match and len(matched_grams) < 2 and not matched_words:
        return 0.0, []
    return round(score, 2), reasons


def search_knowledge(
    query: str,
    knowledge_dir: str | Path | None = None,
    mode: str | None = None,
    dimension: str | None = None,
    limit: int = 3,
    include_text: bool = False,
) -> dict[str, Any]:
    """Return ranked metadata and, optionally, the selected cards' full text."""
    if not isinstance(query, str):
        raise ValueError("query: expected a string")
    if mode is not None and mode not in MODE_COUNTS:
        raise ValueError("mode: expected V1, V2, V3 or V4")
    if dimension is not None:
        _dimension(dimension, "dimension")
        if mode is not None and dimension.split("-")[0] != mode:
            raise ValueError("dimension: does not belong to the selected mode")
    if type(limit) is not int or not 1 <= limit <= 8:
        raise ValueError("limit: expected an integer from 1 to 8")
    if type(include_text) is not bool:
        raise ValueError("include_text: expected a boolean")
    root = Path(knowledge_dir if knowledge_dir is not None else DEFAULT_KNOWLEDGE_DIR).resolve()
    data = _read_index(root)
    normalized_query = _normalize(query)
    candidates: list[tuple[float, dict[str, Any], list[str]]] = []
    if _meaningful(normalized_query):
        for card in data["cards"]:
            if mode is not None and mode not in card["modes"]:
                continue
            if dimension is not None and dimension not in card["dimensions"]:
                continue
            relevance, reasons = _rank(card, normalized_query)
            if relevance:
                candidates.append((relevance, card, reasons))
    candidates.sort(key=lambda item: (-item[0], item[1]["id"]))
    hits = []
    for relevance, card, reasons in candidates[:limit]:
        hit = {key: card[key] for key in (
            "id", "title", "path", "kind", "modes", "dimensions", "summary", "sources"
        )}
        hit["relevance"] = relevance
        hit["hit_reasons"] = reasons
        if include_text:
            selected_path = _safe_path(root, card["path"], f"card {card['id']}.path")
            try:
                hit["text"] = selected_path.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeError) as exc:
                raise ValueError(f"card {card['id']}: cannot read UTF-8 text ({type(exc).__name__})") from exc
        hits.append(hit)
    return {
        "status": "ok" if hits else "no_match",
        "query": query,
        "knowledge_version": data["knowledge_version"],
        "filters": {"mode": mode, "dimension": dimension},
        "hits": hits,
        "notice": NOTICE,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True)
    parser.add_argument("--knowledge-dir", type=Path)
    parser.add_argument("--mode", choices=tuple(MODE_COUNTS))
    parser.add_argument("--dimension")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--include-text", action="store_true")
    args = parser.parse_args()
    try:
        result = search_knowledge(**vars(args))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
