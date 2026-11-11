"""cinema: movie poster, announcement channel on bots

Additive only.

Revision ID: 0005_cinema_channel
Revises: 0004_cinema
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_cinema_channel"
down_revision = "0004_cinema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("movies") as b:
        b.add_column(sa.Column("poster_file_id", sa.String(length=512), nullable=True))
    with op.batch_alter_table("bots") as b:
        b.add_column(sa.Column("movie_channel_id", sa.BigInteger(), nullable=True))
        b.add_column(sa.Column("movie_channel_title", sa.String(length=255), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("bots") as b:
        b.drop_column("movie_channel_title")
        b.drop_column("movie_channel_id")
    with op.batch_alter_table("movies") as b:
        b.drop_column("poster_file_id")
