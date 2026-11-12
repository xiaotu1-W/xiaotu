from sqlalchemy import select, func
from sqlalchemy.orm import Session, selectinload
from app.models import Problem, Tag, UserProblem, problem_tags

def list_problems(db: Session, user_id: int | None, q: str | None, category: str | None, difficulty: str | None, tags: list[str], page: int, page_size: int, sort: str):
    stmt = select(Problem).options(selectinload(Problem.tags), selectinload(Problem.author))
    if user_id is None: stmt = stmt.where(Problem.is_public.is_(True))
    else: stmt = stmt.where((Problem.is_public.is_(True)) | (Problem.author_id == user_id))
    if q: stmt = stmt.where(Problem.title.ilike(f"%{q}%") | Problem.statement.ilike(f"%{q}%"))
    if category: stmt = stmt.where(Problem.category == category)
    if difficulty: stmt = stmt.where(Problem.difficulty == difficulty)
    if tags:
        matched = select(problem_tags.c.problem_id).join(Tag).where(Tag.name.in_(tags)).group_by(problem_tags.c.problem_id).having(func.count(func.distinct(Tag.id)) == len(set(tags)))
        stmt = stmt.where(Problem.id.in_(matched))
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    order = Problem.title.asc() if sort == "title" else Problem.created_at.asc() if sort == "oldest" else Problem.created_at.desc()
    problems = db.scalars(stmt.order_by(order, Problem.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    solved_ids = set()
    if user_id and problems:
        solved_ids = set(db.scalars(select(UserProblem.problem_id).where(UserProblem.user_id == user_id, UserProblem.solved.is_(True), UserProblem.problem_id.in_([p.id for p in problems]))).all())
    return [{"id": p.id, "title": p.title, "statement": p.statement, "input_description": p.input_description, "output_description": p.output_description, "sample_input": p.sample_input, "sample_output": p.sample_output, "difficulty": p.difficulty, "category": p.category, "tags": [t.name for t in p.tags], "author": p.author.username, "solved": p.id in solved_ids, "created_at": p.created_at} for p in problems], total
