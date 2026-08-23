"""Local Saved Answer Library & Question Similarity Engine."""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_SAVED_ANSWERS_PATH = "state/saved_answers.json"


def normalize_question_text(question: str) -> str:
    """Normalize question text for comparison."""
    if not question:
        return ""
    text = question.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def calculate_jaccard_similarity(text1: str, text2: str) -> float:
    """Calculate token-level Jaccard similarity."""
    tokens1 = set(normalize_question_text(text1).split())
    tokens2 = set(normalize_question_text(text2).split())
    if not tokens1 or not tokens2:
        return 0.0
    intersection = tokens1.intersection(tokens2)
    union = tokens1.union(tokens2)
    return len(intersection) / len(union)


class SavedAnswersLibrary:
    """Manages local library of candidate answers for recurring application questions."""

    def __init__(self, storage_path: str = DEFAULT_SAVED_ANSWERS_PATH):
        self.storage_path = storage_path
        self._answers = self._load()

    def _load(self) -> List[Dict[str, Any]]:
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.debug("Failed to load saved answers from %s: %s", self.storage_path, e)
        return []

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.storage_path) or ".", exist_ok=True)
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(self._answers, f, indent=2)
        except Exception as e:
            logger.warning("Failed to save answers to %s: %s", self.storage_path, e)

    def find_matching_answer(self, question: str, threshold: float = 0.75) -> Optional[str]:
        """Find an existing saved answer if the question matches with high similarity."""
        norm_q = normalize_question_text(question)
        if not norm_q:
            return None

        best_score = 0.0
        best_answer = None

        for item in self._answers:
            item_q = normalize_question_text(item.get("question", ""))
            if norm_q == item_q:
                return item.get("answer")
            sim = calculate_jaccard_similarity(norm_q, item_q)
            if sim > best_score:
                best_score = sim
                best_answer = item.get("answer")

        if best_score >= threshold:
            logger.info("Found saved answer with similarity %.2f for '%s'", best_score, question[:40])
            return best_answer

        return None

    def save_answer(self, question: str, answer: str, category: str = "general") -> None:
        """Save or update an answer."""
        if not question or not answer:
            return

        norm_q = normalize_question_text(question)
        for item in self._answers:
            if normalize_question_text(item.get("question", "")) == norm_q:
                item["answer"] = answer
                item["updated_at"] = time.time()
                self._save()
                return

        self._answers.append({
            "question": question,
            "answer": answer,
            "category": category,
            "created_at": time.time(),
            "updated_at": time.time(),
        })
        self._save()
