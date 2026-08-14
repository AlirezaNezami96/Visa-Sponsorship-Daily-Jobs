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
            "post_text": "Sample viral LinkedIn post on saving time with AI.",
            "image_title": "AI PRODUCTIVITY",
            "category": "AI TOOLS / PRODUCTIVITY",
            "bg_prompt": "minimalist productivity workplace illustration"
        })
        mock_client.interactions.create.return_value = mock_interaction

        post_text, image_title, category, bg_prompt = call_gemini_text_api("test_api_key")

        mock_client_cls.assert_called_once_with(api_key="test_api_key")
        mock_client.interactions.create.assert_called_once()
        _, kwargs = mock_client.interactions.create.call_args
        self.assertEqual(kwargs["model"], "gemini-3.6-flash")
        self.assertEqual(kwargs["response_mime_type"], "application/json")
        self.assertEqual(post_text, "Sample viral LinkedIn post on saving time with AI.")
        self.assertEqual(image_title, "AI PRODUCTIVITY")
        self.assertEqual(category, "AI TOOLS / PRODUCTIVITY")
        self.assertEqual(bg_prompt, "minimalist productivity workplace illustration")


if __name__ == "__main__":
    unittest.main()
