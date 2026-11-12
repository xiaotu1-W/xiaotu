from datetime import datetime
from sqlalchemy import String, Text, Integer, Boolean, DateTime, ForeignKey, Table, Column, UniqueConstraint, Index, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.utils import utcnow

problem_tags = Table("problem_tags", Base.metadata,
    Column("problem_id", ForeignKey("problems.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True))

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    problems: Mapped[list["Problem"]] = relationship(back_populates="author")
    submissions: Mapped[list["Submission"]] = relationship(back_populates="user")

class Problem(Base):
    __tablename__ = "problems"
    __table_args__ = (Index("ix_problem_filters", "category", "difficulty", "is_public"), Index("ix_problem_created", "created_at"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), index=True)
    statement: Mapped[str] = mapped_column(Text)
    input_description: Mapped[str] = mapped_column(Text, default="")
    output_description: Mapped[str] = mapped_column(Text, default="")
    sample_input: Mapped[str] = mapped_column(Text, default="")
    sample_output: Mapped[str] = mapped_column(Text, default="")
    difficulty: Mapped[str] = mapped_column(String(20), default="简单")
    category: Mapped[str] = mapped_column(String(30), default="Python")
    is_public: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    author: Mapped[User] = relationship(back_populates="problems")
    tags: Mapped[list["Tag"]] = relationship(secondary=problem_tags, back_populates="problems")
    test_cases: Mapped[list["TestCase"]] = relationship(back_populates="problem", cascade="all, delete-orphan")

class TestCase(Base):
    __tablename__ = "test_cases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    problem_id: Mapped[int] = mapped_column(ForeignKey("problems.id", ondelete="CASCADE"), index=True)
    input_data: Mapped[str] = mapped_column(Text)
    expected_output: Mapped[str] = mapped_column(Text)
    is_sample: Mapped[bool] = mapped_column(Boolean, default=False)
    problem: Mapped[Problem] = relationship(back_populates="test_cases")

class Tag(Base):
    __tablename__ = "tags"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    problems: Mapped[list[Problem]] = relationship(secondary=problem_tags, back_populates="tags")

class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (Index("ix_submission_user_problem", "user_id", "problem_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    problem_id: Mapped[int] = mapped_column(ForeignKey("problems.id"), index=True)
    language: Mapped[str] = mapped_column(String(20))
    code: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="Pending", index=True)
    runtime_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    memory_kb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    passed_cases: Mapped[int] = mapped_column(Integer, default=0)
    total_cases: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    user: Mapped[User] = relationship(back_populates="submissions")

class UserProblem(Base):
    __tablename__ = "user_problems"
    __table_args__ = (UniqueConstraint("user_id", "problem_id", name="uq_user_problem"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    problem_id: Mapped[int] = mapped_column(ForeignKey("problems.id"), index=True)
    attempted: Mapped[bool] = mapped_column(Boolean, default=False)
    solved: Mapped[bool] = mapped_column(Boolean, default=False)
    first_solved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_submission_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
