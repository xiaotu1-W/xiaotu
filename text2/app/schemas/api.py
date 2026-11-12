from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict

class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=40, pattern=r"^[\w-]+$")
    email: str = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)

class LoginIn(BaseModel):
    username: str
    password: str

class UserOut(BaseModel):
    id: int
    username: str
    email: str
    model_config = ConfigDict(from_attributes=True)

class CaseIn(BaseModel):
    input: str
    output: str

class ProblemCreate(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    statement: str
    input_description: str = ""
    output_description: str = ""
    sample_input: str = ""
    sample_output: str = ""
    difficulty: str = "简单"
    category: str = "Python"
    tags: list[str] = []
    test_cases: list[CaseIn] = []
    is_public: bool = True

class ProblemOut(BaseModel):
    id: int
    title: str
    statement: str
    input_description: str
    output_description: str
    sample_input: str
    sample_output: str
    difficulty: str
    category: str
    tags: list[str]
    author: str
    solved: bool = False
    created_at: datetime

class SubmitIn(BaseModel):
    language: str
    code: str = Field(min_length=1, max_length=50000)

class SubmissionOut(BaseModel):
    id: int
    problem_id: int
    language: str
    status: str
    runtime_ms: int | None
    memory_kb: int | None
    passed_cases: int
    total_cases: int
    error_message: str | None
    created_at: datetime
    finished_at: datetime | None

class PageOut(BaseModel):
    items: list[ProblemOut]
    total: int
    page: int
    page_size: int
