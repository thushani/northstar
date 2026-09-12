import os
import unittest
from unittest.mock import patch

from backend.analyzer import analyze_match, assess_qualifications
from backend.hybrid_analyzer import analyze_match as hybrid_analyze_match
from backend.parser import parse_job_text


RESUME = {
    "rawText": (
        "Full-Stack Software Engineer with 7+ years experience. "
        "Production Python, FastAPI, Docker, AWS, CI/CD, testing and machine learning. "
        "Master of Data Science and Bachelor of Computer Engineering."
    ),
    "summary": "Full-Stack Software Engineer",
    "skills": [],
    "experience": [
        {
            "title": "Software Engineer",
            "description": "Built and tested production Python APIs and deployed Docker services.",
        }
    ],
}

PYTHON_JOB_TEXT = """Key Responsibilities
• Build and test production Python services.
Required Skills & Experience
• Strong Python proficiency.
• Practical familiarity with Docker and cloud concepts.
• Typically 3+ years relevant experience.
Desirable (but not required)
• Experience with Kubernetes.
• Exposure to ML/AI projects.
• Experience with CI/CD and testing best practices.
• Degree in Computer Science, Engineering, or a related technical field.
"""


class AnalyzerTests(unittest.TestCase):
    def setUp(self):
        self.python_job = {**parse_job_text(PYTHON_JOB_TEXT), "title": "Python Developer"}

    def test_evaluates_required_and_preferred_qualifications_separately(self):
        result = assess_qualifications(RESUME, self.python_job)
        self.assertEqual((result["requiredMatched"], result["requiredTotal"]), (3, 3))
        self.assertEqual((result["preferredMatched"], result["preferredTotal"]), (3, 4))
        kubernetes = next(item for item in result["preferred"] if "Kubernetes" in item["qualification"])
        self.assertFalse(kubernetes["matched"])

    def test_support_role_does_not_become_good_fit_from_technology_overlap(self):
        support_job = {
            **parse_job_text("""Required Skills
• Python
Responsibilities
• Resolve customer technical issues using Python.
"""),
            "title": "Premium Support Engineer",
        }
        result = analyze_match(RESUME, support_job)
        self.assertTrue(result["roleAlignment"]["coreMismatch"])
        self.assertLessEqual(result["matchScore"], 49)
        self.assertEqual(result["fit"], "limited")

    def test_missing_llm_key_falls_back_to_deterministic_analysis(self):
        environment = {key: value for key, value in os.environ.items() if key != "GEMINI_API_KEY"}
        with patch.dict(os.environ, environment, clear=True):
            result = hybrid_analyze_match(RESUME, self.python_job)
        self.assertEqual(result["analysisMode"], "deterministic")
        self.assertEqual(result["llmStatus"], "not_configured")


if __name__ == "__main__":
    unittest.main()
