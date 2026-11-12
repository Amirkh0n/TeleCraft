"""quiz bots: tests, questions, attempts, polls, settings

Additive only (new tables).

Revision ID: 0007_quiz
Revises: 0006_booking
"""
from alembic import op
import sqlalchemy as sa


revision = '0007_quiz'
down_revision = '0006_booking'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('quiz_settings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('bot_id', sa.Integer(), nullable=False),
    sa.Column('who_can_create', sa.String(length=10), server_default='everyone', nullable=False),
    sa.Column('max_tests_per_user', sa.Integer(), server_default='30', nullable=False),
    sa.ForeignKeyConstraint(['bot_id'], ['bots.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('bot_id')
    )
    op.create_table('quiz_tests',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('bot_id', sa.Integer(), nullable=False),
    sa.Column('owner_tg_id', sa.BigInteger(), nullable=False),
    sa.Column('owner_name', sa.String(length=120), server_default='', nullable=False),
    sa.Column('title', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('time_limit_sec', sa.Integer(), server_default='30', nullable=False),
    sa.Column('shuffle_questions', sa.Boolean(), server_default='1', nullable=False),
    sa.Column('shuffle_options', sa.Boolean(), server_default='1', nullable=False),
    sa.Column('pick_count', sa.Integer(), nullable=True),
    sa.Column('is_public', sa.Boolean(), server_default='1', nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default='1', nullable=False),
    sa.Column('is_draft', sa.Boolean(), server_default='0', nullable=False),
    sa.Column('questions_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('plays', sa.Integer(), server_default='0', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['bot_id'], ['bots.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('quiz_tests', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_quiz_tests_bot_id'), ['bot_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_quiz_tests_owner_tg_id'), ['owner_tg_id'], unique=False)

    op.create_table('quiz_attempts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('bot_id', sa.Integer(), nullable=False),
    sa.Column('test_id', sa.Integer(), nullable=False),
    sa.Column('tg_user_id', sa.BigInteger(), nullable=False),
    sa.Column('user_name', sa.String(length=120), server_default='', nullable=False),
    sa.Column('status', sa.String(length=12), server_default='active', nullable=False),
    sa.Column('order', sa.JSON(), nullable=False),
    sa.Column('current', sa.Integer(), server_default='0', nullable=False),
    sa.Column('score', sa.Integer(), server_default='0', nullable=False),
    sa.Column('total', sa.Integer(), server_default='0', nullable=False),
    sa.Column('missed_streak', sa.Integer(), server_default='0', nullable=False),
    sa.Column('answers', sa.JSON(), nullable=False),
    sa.Column('time_spent_sec', sa.Integer(), server_default='0', nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['bot_id'], ['bots.id'], ),
    sa.ForeignKeyConstraint(['test_id'], ['quiz_tests.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('quiz_attempts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_quiz_attempts_bot_id'), ['bot_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_quiz_attempts_test_id'), ['test_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_quiz_attempts_tg_user_id'), ['tg_user_id'], unique=False)

    op.create_table('quiz_questions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('test_id', sa.Integer(), nullable=False),
    sa.Column('position', sa.Integer(), server_default='0', nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('options', sa.JSON(), nullable=False),
    sa.Column('correct', sa.JSON(), nullable=False),
    sa.Column('explanation', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['test_id'], ['quiz_tests.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('quiz_questions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_quiz_questions_test_id'), ['test_id'], unique=False)

    op.create_table('quiz_polls',
    sa.Column('poll_id', sa.String(length=64), nullable=False),
    sa.Column('attempt_id', sa.Integer(), nullable=False),
    sa.Column('question_id', sa.Integer(), nullable=False),
    sa.Column('chat_id', sa.BigInteger(), nullable=False),
    sa.Column('message_id', sa.Integer(), nullable=True),
    sa.Column('option_order', sa.JSON(), nullable=False),
    sa.Column('is_quiz', sa.Boolean(), server_default='0', nullable=False),
    sa.Column('deadline', sa.DateTime(timezone=True), nullable=False),
    sa.Column('answered', sa.Boolean(), server_default='0', nullable=False),
    sa.ForeignKeyConstraint(['attempt_id'], ['quiz_attempts.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('poll_id')
    )
    with op.batch_alter_table('quiz_polls', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_quiz_polls_attempt_id'), ['attempt_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('quiz_polls', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_quiz_polls_attempt_id'))

    op.drop_table('quiz_polls')
    with op.batch_alter_table('quiz_questions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_quiz_questions_test_id'))

    op.drop_table('quiz_questions')
    with op.batch_alter_table('quiz_attempts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_quiz_attempts_tg_user_id'))
        batch_op.drop_index(batch_op.f('ix_quiz_attempts_test_id'))
        batch_op.drop_index(batch_op.f('ix_quiz_attempts_bot_id'))

    op.drop_table('quiz_attempts')
    with op.batch_alter_table('quiz_tests', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_quiz_tests_owner_tg_id'))
        batch_op.drop_index(batch_op.f('ix_quiz_tests_bot_id'))

    op.drop_table('quiz_tests')
    op.drop_table('quiz_settings')
