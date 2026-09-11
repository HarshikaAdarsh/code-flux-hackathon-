"""Pydantic request/response models for the API surface in PRD section 9."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

Difficulty = Literal["basic", "medium", "hard"]
SubjectType = Literal["coding", "non-coding"]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------


class SignupRequest(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=128)
    preferred_language: str = "en"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class GoogleLoginRequest(BaseModel):
    id_token: str


class UserOut(ORMModel):
    id: uuid.UUID
    email: EmailStr
    name: str
    preferred_language: str
    pomodoro_minutes: int
    created_at: datetime


class UserUpdate(BaseModel):
    name: Optional[str] = None
    preferred_language: Optional[str] = None
    pomodoro_minutes: Optional[int] = Field(default=None, ge=5, le=120)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# --------------------------------------------------------------------------
# Subjects / tree
# --------------------------------------------------------------------------


class SubtopicIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)


class TopicIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    subtopics: List[SubtopicIn] = []


class SubjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    type: SubjectType = "non-coding"
    description: Optional[str] = None
    topics: List[TopicIn] = []


class SubjectUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[SubjectType] = None
    description: Optional[str] = None


class TreeReplace(BaseModel):
    topics: List[TopicIn]


class SubtopicOut(ORMModel):
    id: uuid.UUID
    title: str
    order_index: int
    is_completed: bool
    mastery_score: int
    mastery_updated_at: Optional[datetime] = None


class TopicOut(ORMModel):
    id: uuid.UUID
    title: str
    order_index: int
    is_completed: bool
    subtopics: List[SubtopicOut] = []


class SubjectOut(ORMModel):
    id: uuid.UUID
    name: str
    type: str
    status: str
    description: Optional[str] = None
    syllabus_file_url: Optional[str] = None
    created_at: datetime


class SubjectTreeOut(SubjectOut):
    topics: List[TopicOut] = []
    progress: Dict[str, Any] = {}


class SubjectListItem(SubjectOut):
    topic_count: int = 0
    subtopic_count: int = 0
    completed_subtopics: int = 0
    avg_mastery: int = 0


class TopicPatch(BaseModel):
    title: Optional[str] = None
    is_completed: Optional[bool] = None
    order_index: Optional[int] = None


class SubtopicPatch(BaseModel):
    title: Optional[str] = None
    is_completed: Optional[bool] = None
    order_index: Optional[int] = None


class ParsedTreeOut(BaseModel):
    """Returned after syllabus upload, before the user confirms (PRD 7.1)."""

    subject_id: uuid.UUID
    status: str
    confidence: float
    needs_manual_entry: bool
    message: str
    topics: List[TopicIn]


# --------------------------------------------------------------------------
# Teaching
# --------------------------------------------------------------------------


class TeachRequest(BaseModel):
    subject_id: Optional[uuid.UUID] = None
    subtopic_id: Optional[uuid.UUID] = None
    session_id: Optional[uuid.UUID] = None
    message: Optional[str] = None
    mode: Literal["text", "voice"] = "text"
    language: Optional[str] = None
    style: Literal["default", "simpler", "example", "summary"] = "default"


class ChatMessage(BaseModel):
    role: str
    content: str
    provider: Optional[str] = None
    created_at: Optional[str] = None


class TeachResponse(BaseModel):
    session_id: uuid.UUID
    reply: str
    provider: str
    voice_enabled: bool
    language: str
    messages: List[ChatMessage]


class ChatSessionOut(ORMModel):
    id: uuid.UUID
    subject_id: Optional[uuid.UUID] = None
    subtopic_id: Optional[uuid.UUID] = None
    mode: str
    language: str
    title: Optional[str] = None
    messages: List[Dict[str, Any]] = []
    created_at: datetime


# --------------------------------------------------------------------------
# Assessments
# --------------------------------------------------------------------------


class AssessmentStartRequest(BaseModel):
    subtopic_id: uuid.UUID
    max_questions: Optional[int] = Field(default=None, ge=3, le=30)
    language: Optional[str] = None


class QuestionOut(BaseModel):
    """Question as shown to the user — never carries the answer."""

    id: str
    difficulty: Difficulty
    kind: Literal["theory", "coding"]
    question: str
    options: Optional[List[str]] = None
    starter_code: Optional[str] = None
    visible_tests: Optional[List[Dict[str, Any]]] = None


class AssessmentStateOut(BaseModel):
    attempt_id: uuid.UUID
    status: str
    kind: str
    current_difficulty: Difficulty
    questions_answered: int
    max_questions: int
    mastery_score: int
    question: Optional[QuestionOut] = None
    last_feedback: Optional[str] = None
    finished: bool = False


class AnswerRequest(BaseModel):
    answer: str
    hints_used: int = 0


class CodeSubmitRequest(BaseModel):
    code: str
    language: Literal["python"] = "python"
    hints_used: int = 0
    give_up: bool = False


class TestCaseResult(BaseModel):
    name: str
    passed: bool
    input: Optional[str] = None
    expected: Optional[str] = None
    actual: Optional[str] = None
    error: Optional[str] = None


class CodeSubmitResponse(BaseModel):
    attempt_id: uuid.UUID
    passed: bool
    tests: List[TestCaseResult]
    stdout: str = ""
    stderr: str = ""
    runtime_ms: int = 0
    feedback: str = ""
    hint: Optional[str] = None
    solution: Optional[str] = None
    state: AssessmentStateOut


class AnswerResponse(BaseModel):
    is_correct: bool
    correct_answer: Optional[str] = None
    feedback: str
    state: AssessmentStateOut


class AttemptSummaryOut(BaseModel):
    attempt_id: uuid.UUID
    subtopic: str
    status: str
    kind: str
    total_questions: int
    correct: int
    accuracy: float
    highest_difficulty_reached: str
    hints_used: int
    mastery_score: int
    classification: str
    strengths: List[str] = []
    weaknesses: List[str] = []
    recommendation: str = ""
    responses: List[Dict[str, Any]] = []


class HintRequest(BaseModel):
    code: Optional[str] = None


class HintResponse(BaseModel):
    hint: str
    hints_used: int


# --------------------------------------------------------------------------
# Reports
# --------------------------------------------------------------------------


class SubtopicReport(BaseModel):
    subtopic_id: uuid.UUID
    topic: str
    subtopic: str
    attempts: int
    accuracy: float
    mastery_score: int
    highest_difficulty_reached: str
    hints_used: int
    classification: Literal["strength", "weakness", "needs_practice", "untested"]


class SubjectReportOut(BaseModel):
    subject_id: uuid.UUID
    subject: str
    overall_mastery: int
    tested_subtopics: int
    total_subtopics: int
    strengths: List[SubtopicReport]
    weaknesses: List[SubtopicReport]
    needs_practice: List[SubtopicReport]
    untested: List[SubtopicReport]
    next_recommendation: Optional[str] = None
    study_minutes_7d: int = 0


# --------------------------------------------------------------------------
# Voice
# --------------------------------------------------------------------------


class TranscriptionOut(BaseModel):
    text: str
    language: str
    provider: str


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    language: Optional[str] = None
    voice: Optional[str] = None


class VoiceChatOut(BaseModel):
    transcript: str
    language: str
    reply: str
    session_id: uuid.UUID
    audio_url: Optional[str] = None
    voice_enabled: bool
    provider: str


# --------------------------------------------------------------------------
# Pomodoro
# --------------------------------------------------------------------------


class PomodoroStartRequest(BaseModel):
    subject_id: Optional[uuid.UUID] = None
    subtopic_id: Optional[uuid.UUID] = None
    planned_minutes: int = Field(default=25, ge=1, le=180)


class PomodoroOut(ORMModel):
    id: uuid.UUID
    subject_id: Optional[uuid.UUID] = None
    subtopic_id: Optional[uuid.UUID] = None
    planned_minutes: int
    duration_minutes: int
    status: str
    started_at: datetime
    ended_at: Optional[datetime] = None


class PomodoroStatsOut(BaseModel):
    total_sessions: int
    total_minutes: int
    minutes_last_7_days: int
    by_subject: List[Dict[str, Any]]
    daily: List[Dict[str, Any]]
