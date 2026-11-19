"""child bot languages and content translations

Revision ID: 0017_bot_languages
Revises: 0016_pricing_promo
Create Date: 2026-11-18 14:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0017_bot_languages'
down_revision = '0016_pricing_promo'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('content_translations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('bot_id', sa.Integer(), nullable=False),
    sa.Column('entity', sa.String(length=16), nullable=False),
    sa.Column('entity_id', sa.Integer(), nullable=False),
    sa.Column('lang', sa.String(length=8), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['bot_id'], ['bots.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('entity', 'entity_id', 'lang', name='uq_content_translation')
    )
    op.create_index(op.f('ix_content_translations_bot_id'), 'content_translations', ['bot_id'], unique=False)
    with op.batch_alter_table('bots') as batch:
        batch.add_column(sa.Column('languages', sa.String(length=32), server_default='', nullable=False))
    with op.batch_alter_table('bot_users') as batch:
        batch.add_column(sa.Column('lang', sa.String(length=8), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('bot_users') as batch:
        batch.drop_column('lang')
    with op.batch_alter_table('bots') as batch:
        batch.drop_column('languages')
    op.drop_index(op.f('ix_content_translations_bot_id'), table_name='content_translations')
    op.drop_table('content_translations')
