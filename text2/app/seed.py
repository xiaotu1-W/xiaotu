from sqlalchemy import select
from app.database import SessionLocal, Base, engine
from app.models import User, Problem, Tag, TestCase
from app.services.auth import hash_password

SEEDS = [
    {"title": "两数之和", "statement": "给定两个整数 a 和 b，输出它们的和。", "input_description": "一行包含两个整数。", "output_description": "输出它们的和。", "sample_input": "2 3", "sample_output": "5", "difficulty": "简单", "category": "算法", "tags": ["入门", "数学"], "cases": [("2 3\n", "5\n"), ("-8 3\n", "-5\n"), ("100 200\n", "300\n")]},
    {"title": "统计单词数量", "statement": "读取一行文本，输出其中由空白分隔的单词数量。", "input_description": "一行文本。", "output_description": "单词数量。", "sample_input": "hello world", "sample_output": "2", "difficulty": "简单", "category": "Python", "tags": ["字符串", "入门"], "cases": [("hello world\n", "2\n"), ("one  two three\n", "3\n"), ("   \n", "0\n")]},
    {"title": "筛选及格成绩", "statement": "给定 n 个成绩，输出不低于 60 分的成绩数量。", "input_description": "第一项为 n，后面是 n 个整数。", "output_description": "及格人数。", "sample_input": "5 59 60 100 40 88", "sample_output": "3", "difficulty": "中等", "category": "Python", "tags": ["数组", "循环"], "cases": [("5 59 60 100 40 88\n", "3\n"), ("3 0 20 59\n", "0\n"), ("1 100\n", "1\n")]},
    {"title": "用户表查询", "statement": "有 users(id, name, age) 表，查询所有年龄不小于 18 的用户姓名，按 id 升序排列。", "input_description": "本题用于练习 SQL 查询语句的阅读与编写。", "output_description": "返回符合条件的 name 列。", "sample_input": "", "sample_output": "", "difficulty": "中等", "category": "SQL", "tags": ["SELECT", "WHERE"], "cases": []},
]

def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.username == "demo"))
        if not user:
            user = User(username="demo", email="demo@example.com", password_hash=hash_password("demo1234")); db.add(user); db.flush()
        for item in SEEDS:
            if db.scalar(select(Problem.id).where(Problem.title == item["title"])): continue
            problem = Problem(title=item["title"], statement=item["statement"], input_description=item["input_description"], output_description=item["output_description"], sample_input=item["sample_input"], sample_output=item["sample_output"], difficulty=item["difficulty"], category=item["category"], is_public=True, author_id=user.id)
            db.add(problem)
            for name in item["tags"]:
                tag = db.scalar(select(Tag).where(Tag.name == name))
                if not tag: tag = Tag(name=name); db.add(tag); db.flush()
                problem.tags.append(tag)
            problem.test_cases = [TestCase(input_data=case_in, expected_output=case_out, is_sample=False) for case_in, case_out in item["cases"]]
        db.commit()
    finally: db.close()

if __name__ == "__main__": seed()
