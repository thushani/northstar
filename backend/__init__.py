"""Career Intelligence Assistant - Python Backend Package"""

from .parser import parse_resume, parse_job_description
from .analyzer import analyze_match

__version__ = "1.0.0"
__all__ = ["parse_resume", "parse_job_description", "analyze_match"]
