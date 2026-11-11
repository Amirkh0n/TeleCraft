"""cinema bots: movies table, bots.kind, user_sessions.state

Additive only, so the previous code version keeps working on a migrated database.

Revision ID: 0004_cinema
Revises: 0003_audience
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_cinema"
down_revision = "0003_audience"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "movies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bot_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("file_id", sa.String(length=512), nullable=False),
        sa.Column("file_type", sa.String(length=20), server_default="video", nullable=False),
        sa.Column("views", sa.Integer(), server_default="0", nullable=False),
        sa.Column("added_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["bot_id"], ["bots.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bot_id", "code", name="uq_movies_bot_code"),
    )
    op.create_index(op.f("ix_movies_bot_id"), "movies", ["bot_id"], unique=False)
    with op.batch_alter_table("bots") as b:
        b.add_column(sa.Column("kind", sa.String(length=20), server_default="standard", nullable=False))
    with op.batch_alter_table("user_sessions") as b:
        b.add_column(sa.Column("state", sa.String(length=32), nullable=True))
        b.add_column(sa.Column("state_data", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("user_sessions") as b:
        b.drop_column("state_data")
        b.drop_column("state")
    with op.batch_alter_table("bots") as b:
        b.drop_column("kind")
    op.drop_index(op.f("ix_movies_bot_id"), table_name="movies")
    op.drop_table("movies")
