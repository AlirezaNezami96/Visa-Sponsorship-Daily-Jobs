import json
import unittest
from unittest.mock import MagicMock, patch

from generate_post import call_gemini_text_api


class TestLinkedInGeneratorGemini(unittest.TestCase):
    @patch("google.genai.Client")
    def test_call_gemini_text_api_interactions(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        mock_interaction = MagicMock()
        mock_interaction.output_text = json.dumps({
            "post_text": "Sample viral LinkedIn post on AI breakthroughs.",
            "image_title": "AI BREAKTHROUGH",
            "category": "AI TRENDS",
            "bg_prompt": "futuristic artificial intelligence concept"
        })
        mock_client.interactions.create.return_value = mock_interaction

        post_text, image_title, category, bg_prompt = call_gemini_text_api("test_api_key")

        mock_client_cls.assert_called_once_with(api_key="test_api_key")
        mock_client.interactions.create.assert_called_once()
        _, kwargs = mock_client.interactions.create.call_args
        self.assertEqual(kwargs["model"], "gemini-3.6-flash")
        self.assertEqual(kwargs["response_mime_type"], "application/json")
        self.assertEqual(post_text, "Sample viral LinkedIn post on AI breakthroughs.")
        self.assertEqual(image_title, "AI BREAKTHROUGH")
        self.assertEqual(category, "AI TRENDS")
        self.assertEqual(bg_prompt, "futuristic artificial intelligence concept")


if __name__ == "__main__":
    unittest.main()
