"""Initial OJ schema.

Revision ID: 0001_initial
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("users", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("username", sa.String(40), nullable=False), sa.Column("email", sa.String(255), nullable=False), sa.Column("password_hash", sa.String(255), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_users_username", "users", ["username"], unique=True); op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_table("problems", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("title", sa.String(200), nullable=False), sa.Column("statement", sa.Text(), nullable=False), sa.Column("input_description", sa.Text(), nullable=False), sa.Column("output_description", sa.Text(), nullable=False), sa.Column("sample_input", sa.Text(), nullable=False), sa.Column("sample_output", sa.Text(), nullable=False), sa.Column("difficulty", sa.String(20), nullable=False), sa.Column("category", sa.String(30), nullable=False), sa.Column("is_public", sa.Boolean(), nullable=False), sa.Column("author_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_problems_title", "problems", ["title"]); op.create_index("ix_problems_is_public", "problems", ["is_public"]); op.create_index("ix_problem_filters", "problems", ["category", "difficulty", "is_public"]); op.create_index("ix_problem_created", "problems", ["created_at"])
    op.create_table("tags", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("name", sa.String(40), nullable=False)); op.create_index("ix_tags_name", "tags", ["name"], unique=True)
    op.create_table("problem_tags", sa.Column("problem_id", sa.Integer(), sa.ForeignKey("problems.id", ondelete="CASCADE"), primary_key=True), sa.Column("tag_id", sa.Integer(), sa.ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True))
    op.create_table("test_cases", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("problem_id", sa.Integer(), sa.ForeignKey("problems.id", ondelete="CASCADE"), nullable=False), sa.Column("input_data", sa.Text(), nullable=False), sa.Column("expected_output", sa.Text(), nullable=False), sa.Column("is_sample", sa.Boolean(), nullable=False)); op.create_index("ix_test_cases_problem_id", "test_cases", ["problem_id"])
    op.create_table("submissions", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False), sa.Column("problem_id", sa.Integer(), sa.ForeignKey("problems.id"), nullable=False), sa.Column("language", sa.String(20), nullable=False), sa.Column("code", sa.Text(), nullable=False), sa.Column("status", sa.String(40), nullable=False), sa.Column("runtime_ms", sa.Integer()), sa.Column("memory_kb", sa.Integer()), sa.Column("passed_cases", sa.Integer(), nullable=False), sa.Column("total_cases", sa.Integer(), nullable=False), sa.Column("error_message", sa.Text()), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("finished_at", sa.DateTime()));
    for col in ("user_id", "problem_id", "status", "created_at"): op.create_index(f"ix_submissions_{col}", "submissions", [col])
    op.create_index("ix_submission_user_problem", "submissions", ["user_id", "problem_id"])
    op.create_table("user_problems", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False), sa.Column("problem_id", sa.Integer(), sa.ForeignKey("problems.id"), nullable=False), sa.Column("attempted", sa.Boolean(), nullable=False), sa.Column("solved", sa.Boolean(), nullable=False), sa.Column("first_solved_at", sa.DateTime()), sa.Column("last_submission_at", sa.DateTime()), sa.UniqueConstraint("user_id", "problem_id", name="uq_user_problem")); op.create_index("ix_user_problems_user_id", "user_problems", ["user_id"]); op.create_index("ix_user_problems_problem_id", "user_problems", ["problem_id"])

def downgrade():
    for table in ("user_problems", "submissions", "test_cases", "problem_tags", "tags", "problems", "users"): op.drop_table(table)
