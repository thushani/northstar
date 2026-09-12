"""Document parsing module for PDF, DOCX, and TXT files"""

import re
from pathlib import Path
from typing import List, Dict, Any, Optional

try:
    from PyPDF2 import PdfReader
except ImportError:
    PdfReader = None

try:
    from docx import Document
except ImportError:
    Document = None

def parse_resume(file_path: str) -> Dict[str, Any]:
    """Parse resume from PDF, DOCX, or TXT file"""
    file_path = Path(file_path)
    
    if file_path.suffix.lower() == '.pdf':
        text = _parse_pdf(str(file_path))
    elif file_path.suffix.lower() == '.docx':
        text = _parse_docx(str(file_path))
    elif file_path.suffix.lower() == '.txt':
        text = _parse_txt(str(file_path))
    else:
        raise ValueError(f"Unsupported file format: {file_path.suffix}")
    
    # Extract structured data
    return {
        "rawText": text,
        "skills": extract_skills(text),
        "experience": extract_experience(text),
        "education": extract_education(text),
        "summary": extract_summary(text),
        "keywords": extract_keywords(text)
    }

def parse_job_description(file_path: str) -> Dict[str, Any]:
    """Parse job description from PDF, DOCX, or TXT file"""
    file_path = Path(file_path)
    
    if file_path.suffix.lower() == '.pdf':
        text = _parse_pdf(str(file_path))
    elif file_path.suffix.lower() == '.docx':
        text = _parse_docx(str(file_path))
    elif file_path.suffix.lower() == '.txt':
        text = _parse_txt(str(file_path))
    else:
        raise ValueError(f"Unsupported file format: {file_path.suffix}")
    
    return parse_job_text(text)

def parse_job_text(text: str) -> Dict[str, Any]:
    """Parse a pasted job description into the normalized job schema."""
    analysis_text = clean_job_text(text)
    skill_groups = extract_job_skill_groups(analysis_text)
    qualification_groups = extract_qualification_groups(analysis_text)
    return {
        "rawText": text,
        "analysisText": analysis_text,
        "skills": skill_groups["all"],
        "requiredSkills": skill_groups["required"],
        "preferredSkills": skill_groups["preferred"],
        "requirements": qualification_groups["required"],
        "preferredRequirements": qualification_groups["preferred"],
        "responsibilities": extract_responsibilities(analysis_text),
        "summary": extract_summary(analysis_text),
        "keywords": extract_keywords(analysis_text)
    }


_BOILERPLATE_HEADINGS = {
    "about us", "about the company", "company overview", "who we are", "our story",
    "benefits", "benefits and perks", "what we offer", "perks", "compensation",
    "salary", "how to apply", "application process", "equal opportunity",
    "equal opportunities", "diversity and inclusion", "privacy notice",
}
_REQUIRED_HEADINGS = {
    "requirements", "required skills", "must have", "must haves", "essential skills",
    "essential requirements", "minimum qualifications", "what you need",
    "what we are looking for", "what we're looking for", "qualifications",
    "required skills experience", "required skills and experience",
}
_PREFERRED_HEADINGS = {
    "preferred", "preferred skills", "preferred qualifications", "nice to have",
    "nice to haves", "desirable", "desirable skills", "bonus skills",
    "additional skills", "advantageous",
    "desirable but not required",
}
_RESPONSIBILITY_HEADINGS = {
    "responsibilities", "key responsibilities", "what you will do", "what you'll do",
    "the role", "role responsibilities", "duties", "day to day",
}


def _heading_kind(line: str) -> Optional[str]:
    normalized = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9' ]", " ", line.lower())).strip()
    if len(normalized.split()) > 7:
        return None
    if normalized in _BOILERPLATE_HEADINGS:
        return "boilerplate"
    if normalized in _REQUIRED_HEADINGS:
        return "required"
    if normalized in _PREFERRED_HEADINGS:
        return "preferred"
    if normalized in _RESPONSIBILITY_HEADINGS:
        return "responsibilities"
    return None


def clean_job_text(text: str) -> str:
    """Remove common non-role boilerplate while preserving evidence-bearing job content."""
    kept: List[str] = []
    ignored_section = False
    boilerplate_phrases = (
        "equal opportunity employer", "without regard to race", "privacy policy",
        "reasonable accommodation", "background check", "apply now", "submit your application",
    )
    # LinkedIn copies often concatenate every bullet and heading into one long line.
    text = re.sub(r"\s*[•●▪◦]\s*", "\n• ", text)
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        kind = _heading_kind(line)
        if kind:
            ignored_section = kind == "boilerplate"
            if not ignored_section:
                kept.append(line)
            continue
        if ignored_section or any(phrase in line.lower() for phrase in boilerplate_phrases):
            continue
        kept.append(line)
    return "\n".join(kept)


def extract_job_skill_groups(text: str) -> Dict[str, List[str]]:
    """Separate mandatory and optional skills using explicit job-description sections."""
    required_text: List[str] = []
    preferred_text: List[str] = []
    section: Optional[str] = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        kind = _heading_kind(line)
        if kind:
            section = kind
            continue
        lower = line.lower()
        if section == "required":
            required_text.append(line)
        elif section == "preferred":
            preferred_text.append(line)
        elif section is None and re.search(r"\b(must|required|essential|mandatory)\b", lower):
            required_text.append(line)
        elif section is None and re.search(r"\b(preferred|nice[- ]to[- ]have|desirable|bonus|advantage)\b", lower):
            preferred_text.append(line)

    all_skills = extract_skills(text)
    required = extract_skills("\n".join(required_text))
    preferred = [skill for skill in extract_skills("\n".join(preferred_text)) if skill not in required]
    # When a description has no explicit must-have section, treat uncategorized role skills as required.
    if not required:
        required = [skill for skill in all_skills if skill not in preferred]
    return {"all": all_skills, "required": required, "preferred": preferred}


def extract_qualification_groups(text: str) -> Dict[str, List[str]]:
    """Return individual must-have and additional qualification statements."""
    groups: Dict[str, List[str]] = {"required": [], "preferred": []}
    section: Optional[str] = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        kind = _heading_kind(line)
        if kind:
            section = kind
            continue
        item = line.lstrip('•-* ').strip()
        if section in groups and item:
            groups[section].append(item)
    return groups

def _parse_pdf(file_path: str) -> str:
    """Extract text from PDF file"""
    if not PdfReader:
        raise ImportError("PyPDF2 not installed. Run: pip install PyPDF2")
    
    text = []
    try:
        with open(file_path, 'rb') as f:
            reader = PdfReader(f)
            for page in reader.pages:
                text.append(page.extract_text())
        return "\n".join(text)
    except Exception as e:
        raise Exception(f"Failed to parse PDF: {str(e)}")

def _parse_docx(file_path: str) -> str:
    """Extract text from DOCX file"""
    if not Document:
        raise ImportError("python-docx not installed. Run: pip install python-docx")
    
    try:
        doc = Document(file_path)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n".join(paragraphs)
    except Exception as e:
        raise Exception(f"Failed to parse DOCX: {str(e)}")

def _parse_txt(file_path: str) -> str:
    """Extract text from TXT file"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        raise Exception(f"Failed to parse TXT: {str(e)}")

def extract_skills(text: str) -> List[str]:
    """Extract a controlled set of canonical skills without turning prose into skills."""
    text_lower = re.sub(r'\s+', ' ', text.lower())
    aliases = {
        'javascript': ['javascript', 'js'], 'typescript': ['typescript'], 'python': ['python'],
        'java': ['java'], 'c++': ['c++'], 'c#': ['c#', '.net', 'dotnet'], 'php': ['php'],
        'ruby': ['ruby'], 'go': ['golang'], 'rust': ['rust'], 'html': ['html'], 'css': ['css'],
        'react': ['react', 'react.js', 'reactjs'], 'next.js': ['next.js', 'nextjs'],
        'vue': ['vue', 'vue.js'], 'angular': ['angular'], 'node.js': ['node.js', 'nodejs', 'node js'],
        'express': ['express.js', 'expressjs'], 'django': ['django'], 'flask': ['flask'], 'fastapi': ['fastapi'],
        'sql': ['sql'], 'mysql': ['mysql'], 'postgresql': ['postgresql', 'postgres', 'postgre sql'],
        'mongodb': ['mongodb', 'mongo db'], 'redis': ['redis'], 'elasticsearch': ['elasticsearch', 'elastic search'],
        'aws': ['aws', 'amazon web services'], 'gcp': ['gcp', 'google cloud'], 'azure': ['azure'],
        'docker': ['docker'], 'kubernetes': ['kubernetes', 'k8s'], 'git': ['git', 'github', 'gitlab'],
        'rest api': ['rest api', 'restful'], 'graphql': ['graphql'], 'microservices': ['microservices'],
        'ci/cd': ['ci/cd', 'continuous integration'], 'agile': ['agile'], 'scrum': ['scrum'],
        'full stack': ['full stack', 'full-stack'], 'frontend': ['frontend', 'front-end'],
        'backend': ['backend', 'back-end'], 'machine learning': ['machine learning', 'ml/ai'],
        'deep learning': ['deep learning'], 'nlp': ['nlp', 'natural language processing'],
        'data science': ['data science'], 'analytics': ['analytics'], 'customer support': ['customer support', 'customer service'],
        'product design': ['product design'], 'user research': ['user research'], 'figma': ['figma'],
        'design systems': ['design system'], 'prototyping': ['prototyping'], 'accessibility': ['accessibility', 'wcag'],
        'mentoring': ['mentoring', 'mentor'], 'stakeholder management': ['stakeholder management'],
        'leadership': ['leadership'], 'communication': ['communication'],
        'problem solving': ['problem solving', 'problem-solving', 'troubleshoot', 'debug', 'root cause'],
        'teamwork': ['teamwork', 'collaboration'],
    }
    found = set()
    for canonical, variants in aliases.items():
        if any(re.search(rf'(?<![a-z0-9]){re.escape(value)}(?![a-z0-9])', text_lower) for value in variants):
            found.add(canonical)
    return sorted(found)

def extract_experience(text: str) -> List[Dict[str, str]]:
    """Extract work experience entries from text"""
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    experience = []
    current_role = None
    
    for line in lines:
        # Detect experience entries (usually start with dates or job titles)
        if re.search(r'\d{4}', line) or any(keyword in line.lower() for keyword in ['engineer', 'manager', 'director', 'developer', 'designer']):
            if current_role:
                experience.append(current_role)
            current_role = {"title": line, "description": ""}
        elif current_role and len(line) > 10:
            current_role["description"] += " " + line
    
    if current_role:
        experience.append(current_role)
    
    return experience[:5]  # Return top 5

def extract_education(text: str) -> List[str]:
    """Extract education entries from text"""
    education = []
    degree_keywords = ['bachelor', 'master', 'phd', 'diploma', 'degree', 'university', 'college']
    
    for line in text.split('\n'):
        if any(keyword in line.lower() for keyword in degree_keywords):
            education.append(line.strip())
    
    return education

def extract_requirements(text: str) -> List[str]:
    """Extract job requirements from text"""
    requirements = set()
    section: Optional[str] = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        kind = _heading_kind(line)
        if kind:
            section = kind
            continue
        if section == "required" and line:
            requirements.add(line.lstrip('•-* ').strip())
    
    if not requirements:
        patterns = [
            r'requirements?:?\s*([^\n.]+)',
            r'required:?\s*([^\n.]+)',
            r'must have:?\s*([^\n.]+)',
            r'minimum qualifications?:?\s*([^\n.]+)',
        ]
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                individual_reqs = [r.strip() for r in re.split('[,;]', match) if r.strip() and len(r.strip()) > 3]
                requirements.update(individual_reqs)
    
    return sorted(list(requirements))

def extract_responsibilities(text: str) -> List[str]:
    """Extract job responsibilities from text"""
    responsibilities = []
    section: Optional[str] = None
    has_responsibility_section = any(_heading_kind(line.strip()) == "responsibilities" for line in text.splitlines())

    for line in text.split('\n'):
        line_stripped = line.strip()
        kind = _heading_kind(line_stripped)
        if kind:
            section = kind
            continue
        if line_stripped.startswith('•') or line_stripped.startswith('-') or line_stripped.startswith('*'):
            responsibility = line_stripped.lstrip('•-* ').strip()
            if responsibility and (not has_responsibility_section or section == "responsibilities"):
                responsibilities.append(responsibility)
    
    if not responsibilities:
        action_words = ('build', 'develop', 'design', 'lead', 'create', 'manage', 'support', 'deliver', 'work', 'collaborate', 'implement', 'maintain', 'own', 'solve', 'help')
        candidates = re.split(r'[\n.!?]+', text)
        responsibilities = [item.strip() for item in candidates if 20 <= len(item.strip()) <= 300 and any(re.search(rf'\b{word}\w*\b', item, re.IGNORECASE) for word in action_words)]
    return responsibilities[:10]

def extract_summary(text: str) -> str:
    """Extract a brief summary from the beginning of text"""
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    summary = ' '.join(lines[:5])
    return summary[:500] if summary else "No summary available"

def extract_keywords(text: str) -> List[str]:
    """Extract important keywords from text"""
    words = re.findall(r'\b\w{4,}\b', text.lower())
    
    stop_words = {
        'that', 'this', 'with', 'from', 'have', 'been', 'were', 'their', 'which', 'work',
        'team', 'also', 'more', 'such', 'through', 'many', 'over', 'time', 'able', 'only',
        'year', 'years', 'experience', 'skills', 'education', 'about'
    }
    
    keywords = [w for w in set(words) if w not in stop_words and len(w) > 3]
    return sorted(keywords)[:20]
