import unittest

from app.domain.agent.tool_call import ToolCallParser


class ToolCallParserTest(unittest.TestCase):
    def setUp(self):
        self.parser = ToolCallParser()

    def test_parse_structured_tool_call(self):
        action = self.parser.parse(
            '{"tool":"knowledge_search","arguments":{"query":"ReAct","tag":"agent"}}'
        )
        self.assertEqual(action.tool, "knowledge_search")
        self.assertEqual(action.arguments["query"], "ReAct")
        self.assertEqual(action.format, "json")

    def test_parse_finish(self):
        action = self.parser.parse(
            '{"tool":"finish","arguments":{"answer":"done"}}'
        )
        self.assertTrue(action.is_finish)
        self.assertEqual(action.final_answer, "done")

    def test_legacy_format_is_compatible(self):
        action = self.parser.parse(
            'Thought: search\nAction: knowledge_search(query="中文", tag="agent")'
        )
        self.assertEqual(action.arguments["query"], "中文")
        self.assertEqual(action.format, "legacy")

    def test_invalid_payload_fails(self):
        with self.assertRaises(ValueError):
            self.parser.parse("not a tool call")


if __name__ == "__main__":
    unittest.main()
