import google.generativeai as genai
from dotenv import load_dotenv
import os
from datetime import datetime

load_dotenv()
genai.configure(api_key=os.getenv('GEMINI_API_KEY'))

# 1. Mentor-Student Matching
def recommend_mentors(student_skills, student_goal):
    """Recommend best-fit mentors using AI"""
    model = genai.GenerativeModel('gemini-pro')
    prompt = f"""
    Recommend mentors for a student with:
    - Skills: {', '.join(student_skills)}
    - Career Goal: {student_goal}
    
    Consider these factors:
    1. Technical skill alignment
    2. Industry experience relevance
    3. Communication style
    
    Format response as:
    - Mentor Name: Match Reason (1-2 sentences)
    """
    response = model.generate_content(prompt)
    return response.text

# 2. Session Plan Generator
def generate_session_plan(mentor_expertise, student_goals):
    """Create customized session agenda"""
    model = genai.GenerativeModel('gemini-pro')
    prompt = f"""
    Create a 1-hour mentorship session plan between:
    Mentor Expertise: {mentor_expertise}
    Student Goals: {student_goals}
    
    Include:
    1. 5-minute intro
    2. Three 15-minute focus segments
    3. 10-minute Q&A
    4. Action items
    
    Format as markdown bullet points
    """
    response = model.generate_content(prompt)
    return response.text

# 3. Automated Email Composer
def compose_mentor_email(student_info, session_details):
    """Generate personalized mentor notification"""
    model = genai.GenerativeModel('gemini-pro')
    prompt = f"""
    Compose a professional email to notify a mentor about a new session request:
    
    Student Details:
    - Name: {student_info['name']}
    - Skills: {', '.join(student_info['skills'])}
    - Goal: {student_info['goal']}
    
    Session Request:
    - Date: {session_details['date']}
    - Duration: {session_details['duration']} mins
    - Topics: {session_details['topics']}
    
    Tone: Professional yet friendly
    Include: Acceptance link placeholder
    """
    response = model.generate_content(prompt)
    return response.text

# 4. Interview Question Generator
def generate_interview_questions(role, experience_level):
    """Create role-specific interview questions"""
    model = genai.GenerativeModel('gemini-pro')
    prompt = f"""
    Generate 5 technical interview questions for:
    - Role: {role}
    - Experience Level: {experience_level}
    
    Include:
    1. 2 coding/technical questions
    2. 2 system design/architecture questions
    3. 1 behavioral question
    
    For each question:
    - Mark difficulty (Easy/Medium/Hard)
    - Include key concepts tested
    """
    response = model.generate_content(prompt)
    return response.text

# 5. Post-Session Feedback Analyzer
def analyze_session_feedback(feedback_text):
    """Extract insights from session feedback"""
    model = genai.GenerativeModel('gemini-pro')
    prompt = f"""
    Analyze this mentorship session feedback:
    {feedback_text}
    
    Identify:
    1. 3 strengths
    2. 2 improvement areas
    3. Suggested follow-up topics
    4. Overall sentiment (Positive/Neutral/Negative)
    
    Format as JSON
    """
    response = model.generate_content(prompt)
    return response.text
