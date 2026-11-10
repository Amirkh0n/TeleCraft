"""audience (bot_users), broadcasts, required channels

Additive only (new tables), so the previous code version keeps working on a migrated database.

Revision ID: 0003_audience
Revises: 0002_media_keyboards_forms
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_audience"
down_revision = "0002_media_keyboards_forms"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bot_users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bot_id", sa.Integer(), nullable=False),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("language_code", sa.String(length=16), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("is_blocked", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["bot_id"], ["bots.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bot_id", "tg_user_id", name="uq_bot_users_bot_tg"),
    )
    op.create_index(op.f("ix_bot_users_bot_id"), "bot_users", ["bot_id"], unique=False)

    op.create_table(
        "required_channels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bot_id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("invite_link", sa.String(length=512), nullable=True),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["bot_id"], ["bots.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bot_id", "chat_id", name="uq_required_channels_bot_chat"),
    )
    op.create_index(op.f("ix_required_channels_bot_id"), "required_channels", ["bot_id"], unique=False)

    op.create_table(
        "broadcasts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bot_id", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("media_type", sa.String(length=20), nullable=True),
        sa.Column("media_file_id", sa.String(length=255), nullable=True),
        sa.Column("button_text", sa.String(length=64), nullable=True),
        sa.Column("button_url", sa.String(length=512), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="draft", nullable=False),
        sa.Column("cursor", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("total", sa.Integer(), server_default="0", nullable=False),
        sa.Column("sent", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("blocked", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["bot_id"], ["bots.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_broadcasts_bot_id"), "broadcasts", ["bot_id"], unique=False)


def downgrade() -> None:
    op.drop_table("broadcasts")
    op.drop_table("required_channels")
    op.drop_table("bot_users")
