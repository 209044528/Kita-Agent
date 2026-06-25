import unittest

from app.evaluation.rag import RAGEvaluationCase, evaluate_rag


class RAGEvaluationTest(unittest.TestCase):
    def test_keyword_hit_rate(self):
        cases = [
            RAGEvaluationCase(query="agent", expected_keywords=["感知", "行动"]),
            RAGEvaluationCase(query="missing", expected_keywords=["不存在"]),
        ]

        def retrieve(query, _tag):
            return "Agent 能感知环境并采取行动" if query == "agent" else ""

        report = evaluate_rag(cases, retrieve)
        self.assertEqual(report.total, 2)
        self.assertEqual(report.hits, 1)
        self.assertEqual(report.hit_rate, 0.5)


if __name__ == "__main__":
    unittest.main()
