import re
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy import select, func
from sqlalchemy.orm import Session, selectinload
from app.database import get_db
from app.models import User, Problem, Tag, TestCase, Submission, UserProblem, problem_tags
from app.schemas.api import RegisterIn, LoginIn, UserOut, ProblemCreate, SubmitIn
from app.services.auth import hash_password, verify_password, create_token, get_current_user
from app.repositories.problems import list_problems
from app.services.judge import _execute
from app.services.auth import oauth2_scheme

router = APIRouter(prefix="/api")

@router.post("/auth/register", status_code=201)
def register(payload: RegisterIn, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email): raise HTTPException(422, "邮箱格式不正确")
    if db.scalar(select(User).where((User.username == payload.username) | (User.email == email))): raise HTTPException(409, "用户名或邮箱已被使用")
    user = User(username=payload.username, email=email, password_hash=hash_password(payload.password))
    db.add(user); db.commit(); db.refresh(user)
    return {"user": UserOut.model_validate(user), "access_token": create_token(user), "token_type": "bearer"}

@router.post("/auth/login")
def login(payload: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == payload.username))
    if not user or not verify_password(payload.password, user.password_hash): raise HTTPException(401, "用户名或密码错误")
    return {"user": UserOut.model_validate(user), "access_token": create_token(user), "token_type": "bearer"}

@router.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)): return user

def optional_user(token: str | None = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    if not token: return None
    from jose import jwt, JWTError
    from app.config import settings
    try: return db.get(User, int(jwt.decode(token, settings.jwt_secret, algorithms=["HS256"]).get("sub", "")))
    except (JWTError, ValueError): return None

@router.get("/problems")
def problems(q: str | None = None, category: str | None = None, difficulty: str | None = None, tags: list[str] = Query(default=[]), page: int = Query(1, ge=1), page_size: int = Query(12, ge=1, le=100), sort: str = Query("newest", pattern="^(newest|oldest|title)$"), db: Session = Depends(get_db), user: User | None = Depends(optional_user)):
    items, total = list_problems(db, user.id if user else None, q, category, difficulty, tags, page, page_size, sort)
    return {"items": items, "total": total, "page": page, "page_size": page_size}

@router.get("/problems/{problem_id}")
def problem_detail(problem_id: int, db: Session = Depends(get_db), user: User | None = Depends(optional_user)):
    p = db.scalar(select(Problem).options(selectinload(Problem.tags), selectinload(Problem.author)).where(Problem.id == problem_id))
    if not p or (not p.is_public and (not user or p.author_id != user.id)): raise HTTPException(404, "题目不存在")
    solved = bool(user and db.scalar(select(UserProblem.solved).where(UserProblem.user_id == user.id, UserProblem.problem_id == p.id)))
    return {"id": p.id, "title": p.title, "statement": p.statement, "input_description": p.input_description, "output_description": p.output_description, "sample_input": p.sample_input, "sample_output": p.sample_output, "difficulty": p.difficulty, "category": p.category, "tags": [x.name for x in p.tags], "author": p.author.username, "solved": solved, "created_at": p.created_at}

@router.post("/problems", status_code=201)
def create_problem(payload: ProblemCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if payload.difficulty not in {"简单", "中等", "困难"}: raise HTTPException(422, "难度必须是简单、中等或困难")
    if payload.category not in {"SQL", "Python", "算法"}: raise HTTPException(422, "分类必须是 SQL、Python 或算法")
    if not payload.test_cases: raise HTTPException(422, "至少添加一个隐藏测试用例")
    p = Problem(**payload.model_dump(exclude={"tags", "test_cases"}), author_id=user.id)
    db.add(p)
    p.tags = []
    for name in sorted(set(t.strip() for t in payload.tags if t.strip())):
        tag = db.scalar(select(Tag).where(Tag.name == name)) or Tag(name=name)
        if not tag.id: db.add(tag); db.flush()
        p.tags.append(tag)
    p.test_cases = [TestCase(input_data=c.input, expected_output=c.output, is_sample=False) for c in payload.test_cases]
    db.commit(); db.refresh(p)
    return {"id": p.id, "title": p.title}

@router.get("/tags")
def tags(db: Session = Depends(get_db)):
    return db.scalars(select(Tag.name).order_by(Tag.name)).all()

@router.post("/problems/{problem_id}/submissions", status_code=202)
def submit(problem_id: int, payload: SubmitIn, background: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = db.get(Problem, problem_id)
    if not p or (not p.is_public and p.author_id != user.id): raise HTTPException(404, "题目不存在")
    sub = Submission(user_id=user.id, problem_id=problem_id, language=payload.language, code=payload.code, status="Pending")
    db.add(sub); db.commit(); db.refresh(sub)
    background.add_task(_execute, sub.id)
    return {"id": sub.id, "status": sub.status, "poll_url": f"/api/submissions/{sub.id}"}

@router.get("/submissions/{submission_id}")
def submission_detail(submission_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    sub = db.get(Submission, submission_id)
    if not sub or sub.user_id != user.id: raise HTTPException(404, "提交记录不存在")
    return {"id": sub.id, "problem_id": sub.problem_id, "language": sub.language, "status": sub.status, "runtime_ms": sub.runtime_ms, "memory_kb": sub.memory_kb, "passed_cases": sub.passed_cases, "total_cases": sub.total_cases, "error_message": sub.error_message, "created_at": sub.created_at, "finished_at": sub.finished_at}

@router.get("/problems/{problem_id}/submissions")
def submission_history(problem_id: int, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = select(Submission).where(Submission.problem_id == problem_id, Submission.user_id == user.id).order_by(Submission.created_at.desc())
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.offset((page-1)*page_size).limit(page_size)).all()
    return {"items": [{"id": x.id, "language": x.language, "status": x.status, "runtime_ms": x.runtime_ms, "passed_cases": x.passed_cases, "total_cases": x.total_cases, "created_at": x.created_at} for x in rows], "total": total, "page": page}

@router.get("/stats/summary")
def stats(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    solved = db.scalar(select(func.count()).select_from(UserProblem).where(UserProblem.user_id == user.id, UserProblem.solved.is_(True))) or 0
    submitted = db.scalar(select(func.count()).select_from(Submission).where(Submission.user_id == user.id)) or 0
    accepted = db.scalar(select(func.count()).select_from(Submission).where(Submission.user_id == user.id, Submission.status == "Accepted")) or 0
    by_category = db.execute(select(Problem.category, func.count(UserProblem.id)).join(UserProblem, UserProblem.problem_id == Problem.id).where(UserProblem.user_id == user.id, UserProblem.solved.is_(True)).group_by(Problem.category)).all()
    by_difficulty = db.execute(select(Problem.difficulty, func.count(UserProblem.id)).join(UserProblem, UserProblem.problem_id == Problem.id).where(UserProblem.user_id == user.id, UserProblem.solved.is_(True)).group_by(Problem.difficulty)).all()
    return {"solved_count": solved, "submission_count": submitted, "accepted_count": accepted, "acceptance_rate": round(accepted / submitted * 100, 1) if submitted else 0, "by_category": dict(by_category), "by_difficulty": dict(by_difficulty)}
