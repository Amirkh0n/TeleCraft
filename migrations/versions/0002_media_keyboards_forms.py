"""media on screens, reply keyboards, forms

Additive only: nothing is dropped or renamed, so the previous application version keeps
working against a database that already has this migration (safe rollback of the code).

Revision ID: 0002_media_keyboards_forms
Revises: 0001_baseline
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_media_keyboards_forms"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "forms",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bot_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("intro_text", sa.Text(), nullable=True),
        sa.Column("final_message", sa.Text(), nullable=True),
        sa.Column("notify_admins", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.ForeignKeyConstraint(["bot_id"], ["bots.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_forms_bot_id"), "forms", ["bot_id"], unique=False)

    op.create_table(
        "form_fields",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("form_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("type", sa.String(length=20), server_default="text", nullable=False),
        sa.Column("required", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("options", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["form_id"], ["forms.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_form_fields_form_id"), "form_fields", ["form_id"], unique=False)

    op.create_table(
        "form_submissions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("form_id", sa.Integer(), nullable=False),
        sa.Column("bot_id", sa.Integer(), nullable=False),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("answers", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["bot_id"], ["bots.id"]),
        sa.ForeignKeyConstraint(["form_id"], ["forms.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_form_submissions_bot_id"), "form_submissions", ["bot_id"], unique=False)
    op.create_index(op.f("ix_form_submissions_form_id"), "form_submissions", ["form_id"], unique=False)
    op.create_index(op.f("ix_form_submissions_tg_user_id"), "form_submissions", ["tg_user_id"], unique=False)

    with op.batch_alter_table("buttons") as batch:
        batch.add_column(sa.Column("kind", sa.String(length=20), server_default="normal", nullable=False))

    with op.batch_alter_table("menus") as batch:
        batch.add_column(sa.Column("media_type", sa.String(length=20), nullable=True))
        batch.add_column(sa.Column("media_file_id", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("keyboard_mode", sa.String(length=10), server_default="inline", nullable=False))
        batch.add_column(sa.Column("columns", sa.Integer(), server_default="1", nullable=False))

    with op.batch_alter_table("user_sessions") as batch:
        batch.add_column(sa.Column("form_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("form_step", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("form_data", sa.JSON(), nullable=True))
        batch.add_column(
            sa.Column("reply_keyboard_active", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
        batch.create_foreign_key("fk_user_sessions_form_id", "forms", ["form_id"], ["id"])

    # New button action kinds. PostgreSQL has a real enum type; SQLite stores plain text.
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TYPE actiontype ADD VALUE IF NOT EXISTS 'media'")
        op.execute("ALTER TYPE actiontype ADD VALUE IF NOT EXISTS 'form'")


def downgrade() -> None:
    with op.batch_alter_table("user_sessions") as batch:
        batch.drop_constraint("fk_user_sessions_form_id", type_="foreignkey")
        batch.drop_column("reply_keyboard_active")
        batch.drop_column("form_data")
        batch.drop_column("form_step")
        batch.drop_column("form_id")

    with op.batch_alter_table("menus") as batch:
        batch.drop_column("columns")
        batch.drop_column("keyboard_mode")
        batch.drop_column("media_file_id")
        batch.drop_column("media_type")

    with op.batch_alter_table("buttons") as batch:
        batch.drop_column("kind")

    op.drop_table("form_submissions")
    op.drop_table("form_fields")
    op.drop_table("forms")
    # PostgreSQL cannot remove enum values; 'media' and 'form' stay in actiontype (harmless).
