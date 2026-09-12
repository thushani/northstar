import unittest

from backend.parser import parse_job_text


LINKEDIN_JOB = """About the company
We use AWS and Python across the business.
Key Responsibilities• Build APIs with Python.• Deploy containerised services.
Required Skills & Experience• Strong Python proficiency.• Practical familiarity with Docker.• Typically 3+ years relevant experience.
Desirable (but not required)• Experience with Kubernetes.• Exposure to ML/AI projects.• Experience with CI/CD.
Benefits and perks
Python training and an AWS allowance.
Equal opportunity employer.
"""


class JobParserTests(unittest.TestCase):
    def setUp(self):
        self.job = parse_job_text(LINKEDIN_JOB)

    def test_removes_boilerplate_from_analysis_text(self):
        cleaned = self.job["analysisText"].lower()
        self.assertNotIn("about the company", cleaned)
        self.assertNotIn("benefits and perks", cleaned)
        self.assertNotIn("equal opportunity", cleaned)
        self.assertNotIn("aws allowance", cleaned)

    def test_splits_linkedin_bullets_and_sections(self):
        self.assertEqual(
            self.job["responsibilities"],
            ["Build APIs with Python.", "Deploy containerised services."],
        )
        self.assertEqual(self.job["requiredSkills"], ["docker", "python"])
        self.assertEqual(
            self.job["preferredSkills"],
            ["ci/cd", "kubernetes", "machine learning"],
        )

    def test_preserves_original_text_for_editing(self):
        self.assertEqual(self.job["rawText"], LINKEDIN_JOB)


if __name__ == "__main__":
    unittest.main()
