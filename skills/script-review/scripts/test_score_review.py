"""Focused tests for arithmetic, coverage and input-contract enforcement."""

import copy
import unittest

from score_review import compute_review


def review(mode="V1", score=8):
    count = 12 if mode == "V1" else 6
    return {
        "rules_version": "0.1.0",
        "context": {
            "title": "测试作品",
            "material_type": "完整剧本",
            "primary_goal": "剧作工艺",
        },
        "modes": [{
            "mode": mode,
            "status": "applicable",
            "items": [{
                "id": f"{mode}-{index:02d}",
                "status": "scored",
                "score_10": score,
                "evidence": [{"location": "第1场", "observation": "人物作出关键选择。"}],
                "rationale": "测试用评分依据。",
            } for index in range(1, count + 1)],
        }],
    }


class ScoreReviewTests(unittest.TestCase):
    def test_high_total_with_severe_weakness_is_not_comprehensively_excellent(self):
        data = review(score=10)
        data["modes"][0]["items"][-1]["score_10"] = 2
        result = compute_review(data)["modes"][0]
        self.assertEqual(result["full_total"], 112)
        self.assertEqual(result["lowest_score_10"], 2)
        self.assertIs(result["qualification"], False)

    def test_complete_v1_requires_both_total_and_floor(self):
        data = review(score=9)
        items = data["modes"][0]["items"]
        items[0]["score_10"], items[1]["score_10"] = 8, 10
        result = compute_review(data)["modes"][0]
        self.assertEqual(result["full_total"], 108)
        self.assertEqual(result["coverage"], 1)
        self.assertIs(result["qualification"], True)
        items[1]["score_10"] = 9
        self.assertIs(compute_review(data)["modes"][0]["qualification"], False)

    def test_insufficient_is_not_zero_and_never_extrapolated(self):
        data = review("V2", 8)
        last = data["modes"][0]["items"][-1]
        last.update(status="insufficient", score_10=None, evidence=[], rationale="未提供结尾。")
        result = compute_review(data)["modes"][0]
        self.assertEqual((result["earned_points"], result["assessed_max"]), (80, 100))
        self.assertEqual(result["expected_max"], 120)
        self.assertEqual(result["coverage"], 5 / 6)
        self.assertEqual((result["scored_count"], result["item_count"]), (5, 6))
        self.assertIsNone(result["full_total"])
        self.assertFalse(result["complete"])
        last.update(status="scored", score_10=0, evidence=[{
            "location": "结尾", "observation": "关键问题没有获得任何回应。",
        }])
        zero_result = compute_review(data)["modes"][0]
        self.assertEqual((zero_result["full_total"], zero_result["assessed_max"]), (80, 120))
        self.assertEqual(zero_result["lowest_score_10"], 0)
        for item in data["modes"][0]["items"]:
            item.update(status="insufficient", score_10=None, evidence=[])
        empty_result = compute_review(data)["modes"][0]
        self.assertEqual(empty_result["coverage"], 0)
        self.assertIsNone(empty_result["lowest_score_10"])
        self.assertIsNone(empty_result["full_total"])

    def test_invalid_scores_versions_and_duplicate_modes_are_rejected(self):
        for invalid_score in (-1, 11, True, False, 8.0, "8", None):
            with self.subTest(score=invalid_score):
                data = review()
                data["modes"][0]["items"][0]["score_10"] = invalid_score
                with self.assertRaises(ValueError):
                    compute_review(data)
        data = review()
        data["rules_version"] = "0.2.0"
        with self.assertRaises(ValueError):
            compute_review(data)
        data = review()
        data["modes"].append(copy.deepcopy(data["modes"][0]))
        with self.assertRaises(ValueError):
            compute_review(data)

    def test_missing_duplicate_and_unknown_dimension_ids_are_rejected(self):
        for invalid_id in ("V1-01", "V1-13", "V2-02"):
            with self.subTest(item_id=invalid_id):
                data = review()
                data["modes"][0]["items"][1]["id"] = invalid_id
                with self.assertRaises(ValueError):
                    compute_review(data)
        data = review()
        data["modes"][0]["items"].pop()
        with self.assertRaises(ValueError):
            compute_review(data)

    def test_evidence_and_rationale_are_required_for_scored_items(self):
        for field, value in (("evidence", []), ("rationale", "  ")):
            data = review()
            data["modes"][0]["items"][0][field] = value
            with self.assertRaises(ValueError):
                compute_review(data)
        for field in ("location", "observation"):
            data = review()
            data["modes"][0]["items"][0]["evidence"][0][field] = ""
            with self.assertRaises(ValueError):
                compute_review(data)
        data = review()
        data["modes"][0]["items"][0]["status"] = "insufficient"
        with self.assertRaises(ValueError):
            compute_review(data)

    def test_v4_requires_platform_audience_and_duration(self):
        data = review("V4")
        valid_context = {"platform": "暂定B站", "audience": "暂定电影爱好者", "duration": "暂定5分钟"}
        for omitted in valid_context:
            candidate = copy.deepcopy(data)
            candidate["context"].update({k: v for k, v in valid_context.items() if k != omitted})
            with self.subTest(omitted=omitted), self.assertRaises(ValueError):
                compute_review(candidate)
        data["context"].update(valid_context)
        result = compute_review(data)["modes"][0]
        self.assertEqual(result["full_total"], 96)
        self.assertNotIn("qualification", result)

    def test_not_applicable_has_no_quality_score_and_modes_are_not_aggregated(self):
        data = review("V2")
        data["modes"].append({
            "mode": "V4", "status": "not_applicable", "reason": "未选择传播用途。", "items": [],
        })
        result = compute_review(data)
        self.assertEqual(result["modes"][1], {
            "mode": "V4", "status": "not_applicable", "reason": "未选择传播用途。",
        })
        self.assertEqual(set(result), {"rules_version", "context", "calculation_notice", "modes"})
        self.assertEqual(result["context"], data["context"])
        self.assertNotIn("items", result["modes"][0])
        self.assertNotIn("evidence", result["modes"][0])
        invalid = copy.deepcopy(data)
        invalid["modes"][1]["reason"] = " "
        with self.assertRaises(ValueError):
            compute_review(invalid)
        invalid = copy.deepcopy(data)
        invalid["modes"][1]["items"] = data["modes"][0]["items"]
        with self.assertRaises(ValueError):
            compute_review(invalid)


if __name__ == "__main__":
    unittest.main()
