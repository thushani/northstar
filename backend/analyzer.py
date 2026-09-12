"""Resume-to-job matching and analysis engine"""

from typing import Dict, List, Any, Optional
import re
from .parser import parse_job_text, extract_skills

def analyze_match(resume_data: Dict[str, Any], job_data: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze resume match against job description"""
    # Re-extract on every analysis so parser improvements apply to existing uploads.
    resume_data = {**resume_data, "skills": extract_skills(resume_data.get("rawText", "")) or resume_data.get("skills", [])}
    # Reparse the original description so cleanup/category improvements also apply to saved jobs.
    reparsed_job = parse_job_text(job_data.get("rawText", "")) if job_data.get("rawText") else job_data
    job_data = {**job_data, **reparsed_job}
    
    # Calculate skill alignment
    skill_match = calculate_skill_match(
        resume_data.get('skills', []),
        job_data.get('skills', []),
        job_data.get('requiredSkills', []),
        job_data.get('preferredSkills', []),
    )
    
    # Find skill gaps
    skill_gaps = find_skill_gaps(
        resume_data.get('skills', []), 
        job_data.get('skills', []), 
        job_data.get('requirements', []),
        job_data.get('requiredSkills', []),
        job_data.get('preferredSkills', []),
    )
    
    # Calculate experience alignment
    experience_alignment = assess_experience_alignment(
        resume_data.get('experience', []),
        job_data.get('responsibilities', []),
        resume_data.get('rawText', '')
    )
    role_alignment = assess_role_alignment(resume_data, job_data)
    qualification_match = assess_qualifications(resume_data, job_data)
    
    # Calculate overall match score
    match_score = calculate_match_score(skill_match, experience_alignment, skill_gaps)
    if qualification_match["total"]:
        match_score = round(
            skill_match["percentage"] * 0.35
            + experience_alignment["score"] * 0.25
            + qualification_match["percentage"] * 0.40
        )
    if role_alignment["coreMismatch"]:
        match_score = min(match_score, role_alignment["scoreCap"])
    
    # Generate insights
    insights = generate_insights(resume_data, job_data, skill_gaps, experience_alignment)
    if role_alignment["coreMismatch"]:
        insights.insert(0, {
            "type": "challenge",
            "title": "Transferable skills, different role background",
            "description": role_alignment["detail"],
            "priority": "high",
        })
    
    # Generate interview questions
    interview_questions = generate_interview_questions(resume_data, job_data, skill_gaps)
    
    # Generate next steps
    next_steps = generate_next_steps(skill_gaps, resume_data, job_data)
    
    return {
        "matchScore": match_score,
        "fit": "limited" if role_alignment["coreMismatch"] else assess_fit(match_score),
        "skillMatch": skill_match,
        "experienceAlignment": experience_alignment,
        "roleAlignment": role_alignment,
        "qualificationMatch": qualification_match,
        "skillGaps": skill_gaps,
        "keyStrengths": identify_key_strengths(resume_data.get('skills', []), job_data.get('skills', [])),
        "insights": insights,
        "interviewQuestions": interview_questions,
        "nextSteps": next_steps
    }


def assess_qualifications(resume_data: Dict[str, Any], job_data: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate objective must-have and preferred qualification statements."""
    resume_text = re.sub(r"\s+", " ", resume_data.get("rawText", "").lower())
    resume_skills = set(extract_skills(resume_data.get("rawText", "")))
    soft_criteria = {"communication", "problem solving", "teamwork", "leadership", "mentoring", "stakeholder management"}

    def has_degree_requirement(value: str) -> bool:
        return bool(re.search(r"\b(degree in|bachelor|master|phd|technical field)\b", value.lower()))

    def objective(items: List[str]) -> List[str]:
        return [item for item in items if (
            any(skill not in soft_criteria for skill in extract_skills(item))
            or re.search(r"\b\d+\+?\s*years?\b", item.lower())
            or has_degree_requirement(item)
        )]

    def evaluate(item: str) -> Dict[str, Any]:
        lower = item.lower()
        mentioned_skills = extract_skills(item)
        matched_skills = [skill for skill in mentioned_skills if skill in resume_skills]
        supported = bool(matched_skills) if mentioned_skills else False
        evidence = ", ".join(matched_skills)

        years = re.search(r"\b(\d+)\+?\s*years?\b", lower)
        if years:
            resume_years = [int(value) for value in re.findall(r"\b(\d+)\+?\s*years?\b", resume_text)]
            supported = bool(resume_years and max(resume_years) >= int(years.group(1)))
            evidence = f"{max(resume_years)}+ years stated in resume" if supported else ""
        elif has_degree_requirement(item):
            degree = re.search(r"\b(bachelor|master|phd|degree)\b", resume_text)
            supported = bool(degree)
            evidence = "Degree listed in resume" if supported else ""

        return {"qualification": item, "matched": supported, "evidence": evidence or None}

    required = [evaluate(item) for item in objective(job_data.get("requirements", []))]
    preferred = [evaluate(item) for item in objective(job_data.get("preferredRequirements", []))]
    required_matches = sum(item["matched"] for item in required)
    preferred_matches = sum(item["matched"] for item in preferred)
    weighted_total = len(required) * 2 + len(preferred)
    weighted_matches = required_matches * 2 + preferred_matches
    percentage = round(weighted_matches / weighted_total * 100) if weighted_total else 0
    return {
        "required": required,
        "preferred": preferred,
        "requiredMatched": required_matches,
        "requiredTotal": len(required),
        "preferredMatched": preferred_matches,
        "preferredTotal": len(preferred),
        "total": len(required) + len(preferred),
        "percentage": percentage,
    }


def assess_role_alignment(resume_data: Dict[str, Any], job_data: Dict[str, Any]) -> Dict[str, Any]:
    """Prevent transferable technology overlap from being mistaken for core support experience."""
    target_title = job_data.get("title", "").lower()
    career_titles = " ".join(
        [resume_data.get("summary", "")]
        + [item.get("title", "") for item in resume_data.get("experience", [])]
    ).lower()
    support_target = bool(re.search(r"\b(premium|technical|customer|developer) support\b|\bsupport engineer\b", target_title))
    support_background = bool(re.search(
        r"\b(technical support|customer support|developer support|support engineer|support specialist|customer success)\b",
        career_titles,
    ))
    mismatch = support_target and not support_background
    return {
        "targetFamily": "support" if support_target else "general",
        "directExperience": not mismatch,
        "coreMismatch": mismatch,
        "scoreCap": 49 if mismatch else 100,
        "detail": (
            "The resume shows transferable engineering skills but not a direct support-engineering role."
            if mismatch else "The resume career background aligns with the role family."
        ),
    }

def calculate_skill_match(resume_skills: List[str], job_skills: List[str], required_skills: Optional[List[str]] = None, preferred_skills: Optional[List[str]] = None) -> Dict[str, Any]:
    """Calculate skill alignment, giving must-have skills twice the optional-skill weight."""
    resume_set = {skill.lower() for skill in resume_skills}
    job_skills_lower = list(dict.fromkeys(skill.lower() for skill in job_skills))
    required = list(dict.fromkeys(skill.lower() for skill in (required_skills or [])))
    preferred = [skill.lower() for skill in (preferred_skills or []) if skill.lower() not in required]
    general = [skill for skill in job_skills_lower if skill not in required and skill not in preferred]
    if not required:
        required, general = general, []

    matched = [skill for skill in job_skills_lower if skill in resume_set]
    matched_required = [skill for skill in required if skill in resume_set]
    matched_preferred = [skill for skill in preferred if skill in resume_set]
    weighted_total = len(required) * 2 + len(preferred) + len(general)
    weighted_matched = len(matched_required) * 2 + len(matched_preferred) + len([skill for skill in general if skill in resume_set])
    match_percentage = weighted_matched / weighted_total * 100 if weighted_total else 0
    
    return {
        "percentage": int(match_percentage),
        "matchedSkills": matched,
        "totalRequired": len(required),
        "totalPreferred": len(preferred),
        "totalMatched": len(matched),
        "requiredPercentage": round(len(matched_required) / len(required) * 100) if required else 100,
        "preferredPercentage": round(len(matched_preferred) / len(preferred) * 100) if preferred else 100,
        "matchedRequiredSkills": matched_required,
        "matchedPreferredSkills": matched_preferred,
    }

def find_skill_gaps(resume_skills: List[str], job_skills: List[str], job_requirements: List[str], required_skills: Optional[List[str]] = None, preferred_skills: Optional[List[str]] = None) -> Dict[str, Any]:
    """Identify skill gaps between resume and job requirements"""
    resume_skills_lower = [s.lower() for s in resume_skills]
    job_skills_lower = [s.lower() for s in job_skills]
    
    gaps = [skill for skill in job_skills_lower if skill not in resume_skills_lower]
    
    required_set = {skill.lower() for skill in (required_skills or [])}
    preferred_set = {skill.lower() for skill in (preferred_skills or [])}
    critical_gaps = [gap for gap in gaps if gap in required_set]
    nice_to_have = [gap for gap in gaps if gap in preferred_set]
    uncategorized = [gap for gap in gaps if gap not in required_set and gap not in preferred_set]
    if not required_set:
        critical_gaps = uncategorized
        uncategorized = []
    
    return {
        "totalGaps": len(gaps),
        "gaps": gaps,
        "criticalGaps": critical_gaps,
        "niceToHave": nice_to_have,
        "uncategorized": uncategorized,
        "developmentPriority": prioritize_gaps(gaps)
    }

def prioritize_gaps(gaps: List[str]) -> Dict[str, List[str]]:
    """Prioritize skill gaps by category"""
    tech_keywords = ['javascript', 'python', 'java', 'database', 'aws', 'api', 'react', 'backend']
    soft_keywords = ['leadership', 'communication', 'management', 'teamwork']
    
    return {
        "technical": [g for g in gaps if any(t in g.lower() for t in tech_keywords)],
        "soft": [g for g in gaps if any(s in g.lower() for s in soft_keywords)],
        "domain": [g for g in gaps if g not in [g2 for g2 in gaps if any(t in g2.lower() for t in tech_keywords) or any(s in g2.lower() for s in soft_keywords)]]
    }

def assess_experience_alignment(resume_experience: List[Dict], job_responsibilities: List[str], raw_text: str) -> Dict[str, Any]:
    """Assess how well resume experience aligns with job responsibilities"""
    
    if not resume_experience:
        return {
            "score": 0,
            "detail": "No experience found in resume",
            "alignedItems": []
        }
    
    if not job_responsibilities:
        return {
            "score": 50,
            "detail": "Unable to assess without job responsibilities",
            "alignedItems": []
        }
    
    stop_words = {'the', 'and', 'for', 'with', 'you', 'your', 'our', 'will', 'this', 'that', 'from', 'into', 'are', 'have', 'has', 'using', 'work', 'role', 'team'}
    def tokens(value: str) -> set[str]:
        return {word for word in re.findall(r"[a-z0-9+#.]+", value.lower()) if len(word) > 2 and word not in stop_words}

    experience_text = [exp.get('title', '') + ' ' + exp.get('description', '') for exp in resume_experience]
    resume_tokens = tokens(raw_text + ' ' + ' '.join(experience_text))
    pairs = []
    for responsibility in job_responsibilities:
        required = tokens(responsibility)
        best_index, best_score = 0, (len(required & resume_tokens) / len(required) if required else 0.0)
        for index, experience in enumerate(experience_text):
            present = tokens(experience)
            score = len(required & present) / len(required) if required else 0
            if score > best_score:
                best_index, best_score = index, score
        pairs.append((best_score, best_index, responsibility))
    matched_count = sum(1 for score, _, _ in pairs if score >= .15)
    evidence_coverage = matched_count / len(pairs) * 100
    average_similarity = sum(score for score, _, _ in pairs) / len(pairs) * 100
    # Coverage answers "how many duties have evidence?"; similarity adds confidence without
    # unfairly penalising concise resume evidence against verbose job-advert wording.
    alignment_score = min(100, max(5, round(evidence_coverage * 0.7 + average_similarity * 0.3)))
    # Keep the response concise while reporting the count across every responsibility.
    aligned_items = [{"responsibility": responsibility, "experience": resume_experience[index].get('title', 'Resume evidence'), "similarity": round(score, 2)} for score, index, responsibility in sorted(pairs, reverse=True) if score >= .15][:3]
    
    return {
        "score": alignment_score,
        "detail": f"Found evidence for {matched_count} of {len(job_responsibilities)} key responsibilities",
        "matchedCount": matched_count,
        "totalResponsibilities": len(job_responsibilities),
        "alignedItems": aligned_items
    }

def calculate_match_score(skill_match: Dict, experience_alignment: Dict, skill_gaps: Dict) -> int:
    """Calculate overall match score (0-100)"""
    skill_weight = 0.65
    experience_weight = 0.35
    
    skill_score = skill_match.get('percentage', 0)
    experience_score = experience_alignment.get('score', 50)
    
    match_score = (
        skill_score * skill_weight +
        experience_score * experience_weight
    )
    
    return int(min(100, max(0, match_score)))

def assess_fit(score: int) -> str:
    """Assess fit level based on score"""
    if score >= 80:
        return "excellent"
    elif score >= 60:
        return "good"
    elif score >= 40:
        return "moderate"
    elif score >= 20:
        return "developing"
    else:
        return "significant-gaps"

def identify_key_strengths(resume_skills: List[str], job_skills: List[str]) -> List[str]:
    """Identify resume skills that match job requirements"""
    resume_skills_lower = [s.lower() for s in resume_skills]
    job_skills_lower = [s.lower() for s in job_skills]
    
    strengths = [skill for skill in job_skills_lower if skill in resume_skills_lower]
    return strengths[:5]

def generate_insights(resume_data: Dict, job_data: Dict, skill_gaps: Dict, experience_alignment: Dict) -> List[Dict[str, Any]]:
    """Generate actionable insights"""
    insights = []
    
    if skill_gaps['totalGaps'] == 0:
        insights.append({
            "type": "strength",
            "title": "Perfect skill alignment",
            "description": "Your skillset matches all the required and desired skills for this role.",
            "priority": "high"
        })
    elif skill_gaps['totalGaps'] <= 3:
        insights.append({
            "type": "opportunity",
            "title": "Minor skill gaps",
            "description": f"You're missing {skill_gaps['totalGaps']} skills, which are learnable with focused effort.",
            "priority": "medium"
        })
    else:
        insights.append({
            "type": "development",
            "title": "Skill development needed",
            "description": f"{skill_gaps['totalGaps']} skills require development. Consider a structured learning path.",
            "priority": "high"
        })
    
    if experience_alignment['score'] >= 70:
        insights.append({
            "type": "strength",
            "title": "Strong experience alignment",
            "description": "Your background directly translates to the key responsibilities of this role.",
            "priority": "high"
        })
    elif experience_alignment['score'] >= 40:
        insights.append({
            "type": "opportunity",
            "title": "Transferable experience",
            "description": "You have relevant experience that transfers well, though some growth is needed.",
            "priority": "medium"
        })
    else:
        insights.append({
            "type": "challenge",
            "title": "Experience gap exists",
            "description": "Consider highlighting transferable skills and your ability to learn quickly.",
            "priority": "high"
        })
    
    return insights

def generate_interview_questions(resume_data: Dict, job_data: Dict, skill_gaps: Dict) -> List[Dict[str, Any]]:
    """Generate tailored interview questions"""
    questions = []
    
    job_summary = job_data.get('summary', '')
    resume_experience = resume_data.get('experience', [])
    critical_gaps = skill_gaps.get('criticalGaps', [])
    
    # Question 1: About top skill gap
    if critical_gaps:
        gap = critical_gaps[0]
        questions.append({
            "index": 1,
            "question": f"Tell us about your experience with {gap}. How have you used it in previous roles?",
            "hint": "This is a critical skill for the role. Be honest about your familiarity and willingness to learn.",
            "category": "skill-gap"
        })
    
    # Question 2: About strongest experience
    if resume_experience:
        exp_title = resume_experience[0].get('title', 'your most recent role')
        questions.append({
            "index": 2,
            "question": f"Walk us through {exp_title}. How does it apply to this role?",
            "hint": "Connect your past accomplishments directly to what you'll do in this role.",
            "category": "experience"
        })
    
    # Question 3: About motivation
    questions.append({
        "index": 3,
        "question": "Why are you interested in this role? What excites you about this opportunity?",
        "hint": "Show that you've researched the company and role. Be specific about what excites you.",
        "category": "motivation"
    })
    
    # Question 4: About learning
    if skill_gaps.get('niceToHave'):
        skill = skill_gaps['niceToHave'][0]
        questions.append({
            "index": 4,
            "question": f"We notice you don't have experience with {skill}. How do you approach learning new technologies?",
            "hint": "Demonstrate your learning mindset with examples of skills you've picked up quickly.",
            "category": "learning-agility"
        })
    
    # Question 5: About growth
    questions.append({
        "index": 5,
        "question": "Where do you see yourself growing in the next 2 years, and how does this role support that?",
        "hint": "Align your growth goals with the company's trajectory and role requirements.",
        "category": "growth"
    })
    
    return questions[:5]

def generate_next_steps(skill_gaps: Dict, resume_data: Dict, job_data: Dict) -> List[Dict[str, Any]]:
    """Generate next steps for the candidate"""
    steps = []
    
    critical_gaps = skill_gaps.get('criticalGaps', [])
    experience = resume_data.get('experience', [])
    
    if critical_gaps:
        top_gaps = critical_gaps[:2] if len(critical_gaps) > 1 else critical_gaps
        steps.append({
            "priority": "high",
            "action": "Build a learning plan",
            "detail": f"Focus on mastering: {', '.join(top_gaps)}",
            "timeline": "2-4 weeks",
            "resources": "Online courses, documentation, side projects"
        })
    
    if experience:
        steps.append({
            "priority": "high",
            "action": "Prepare a case study",
            "detail": f"Highlight: {experience[0].get('title', 'your most relevant role')}",
            "timeline": "1 week",
            "resources": "Portfolio, GitHub, project documentation"
        })
    
    steps.append({
        "priority": "medium",
        "action": "Research the company",
        "detail": "Understand their products, culture, recent news, and technical stack",
        "timeline": "3-5 days",
        "resources": "Company website, tech blog, LinkedIn"
    })
    
    steps.append({
        "priority": "medium",
        "action": "Practice interview questions",
        "detail": "Record yourself answering common behavioral and technical questions",
        "timeline": "1 week",
        "resources": "Interview prep guides, mock interviews with friends"
    })
    
    return steps
