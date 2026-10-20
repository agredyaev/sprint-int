"""Regression checks: Jira discussion completeness, evidence context, publication gating."""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import sprint_pipeline as sp


class JiraCommentContractTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = sp.read_json(str(HERE / "sample_snapshot.json"))
        self.issues = sp.read_jsonl(str(HERE / "sample_issues.jsonl"))
        self.labels = sp.read_jsonl(str(HERE / "sample_classifications.jsonl"))

    def test_verified_empty_comment_history_is_complete(self):
        cov = sp.coverage(self.snapshot, self.issues, self.labels)
        self.assertTrue(cov["comments_coverage_complete"], cov["warnings"])
        self.assertTrue(cov["coverage_complete"])
        self.assertEqual(cov["comments_incomplete_issue_keys"], [])

    def test_absent_comments_are_not_confirmed_zero(self):
        issues = copy.deepcopy(self.issues)
        issue = issues[0]
        for k in ("comments", "comments_total", "comments_pages", "comments_complete"):
            issue.pop(k)
        cov = sp.coverage(self.snapshot, issues, self.labels)
        self.assertFalse(cov["coverage_complete"])
        self.assertIn(issue["key"], cov["comments_incomplete_issue_keys"])

    def test_partial_pagination_blocks_final_coverage(self):
        issues = copy.deepcopy(self.issues)
        issue = issues[0]
        issue["comments_complete"] = False
        issue["comments_total"] = 2
        issue["comments_pages"] = 1
        issue["comments"] = [self.comment(issue, "1", "2026-10-10T08:00:00+02:00", "Partial page")]
        cov = sp.coverage(self.snapshot, issues, self.labels)
        self.assertFalse(cov["coverage_complete"])
        self.assertIn(issue["key"], cov["comments_incomplete_issue_keys"])

    def test_provider_count_mismatch_even_with_complete_flag(self):
        issues = copy.deepcopy(self.issues)
        issues[0]["comments_total"] = 2
        self.assertFalse(sp.coverage(self.snapshot, issues)["coverage_complete"])

    def test_duplicate_id_and_uncited_comment_block_final(self):
        issues = copy.deepcopy(self.issues)
        issue = issues[0]
        c = self.comment(issue, "1", "2026-10-10T08:00:00+02:00", "Accepted")
        issue["comments"] = [c, dict(c)]
        issue["comments_total"] = 2
        self.assertFalse(sp.coverage(self.snapshot, issues)["coverage_complete"])
        issue["comments"] = [dict(c, url="https://evil.test/comment/1")]
        issue["comments_total"] = 1
        self.assertFalse(sp.coverage(self.snapshot, issues)["coverage_complete"])

    def test_old_decision_context_and_last_four_recent_comments(self):
        issues = copy.deepcopy(self.issues)
        issue = issues[1]
        old = self.comment(issue,"old","2026-09-28T08:00:00+02:00", "Scope changed before sprint")
        recent = [self.comment(issue,str(n),f"2026-10-{n+5:02d}T12:00:00+02:00",f"Decision {n}") for n in range(1,7)]
        issue["comments"] = [old]+list(reversed(recent))
        issue["comments_total"] = 7
        start,end=sp.window(self.snapshot)
        result=sp.feature(issue,sp.root_epic(issue,sp.indexes(issues)),start,end)
        self.assertEqual(result["in_window_comment_count"],6)
        self.assertEqual([x["id"] for x in result["in_window_comments"]],["3","4","5","6"])
        self.assertEqual([x["id"] for x in result["prior_context_comments"]],["old"])
        self.assertTrue(result["evidence_truncated"])
        self.assertEqual(result["comments_total"],7)
        self.assertTrue(result["comments_complete"])

    def test_hash_changes_when_comment_changes(self):
        orig=sp.fingerprint({"snapshot":self.snapshot,"issues":self.issues})
        issues=copy.deepcopy(self.issues)
        issues[1]["comments"]=[self.comment(issues[1],"1","2026-10-10T12:00:00+02:00","Client rejected acceptance")]
        issues[1]["comments_total"]=1
        changed=sp.fingerprint({"snapshot":self.snapshot,"issues":issues})
        self.assertNotEqual(orig,changed)

    @staticmethod
    def comment(issue, ident, when, body):
        return {"id":ident,"created":when,"body":body,
                "url":issue["url"]+"?focusedCommentId="+ident}


if __name__ == "__main__":
    unittest.main()
