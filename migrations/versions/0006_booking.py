"""booking bots: services, specialists, hours, days off, bookings, settings

Additive only (new tables).

Revision ID: 0006_booking
Revises: 0005_cinema_channel
"""
from alembic import op
import sqlalchemy as sa


revision = '0006_booking'
down_revision = '0005_cinema_channel'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('booking_services',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('bot_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('duration_min', sa.Integer(), nullable=False),
    sa.Column('price', sa.Integer(), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default='1', nullable=False),
    sa.Column('position', sa.Integer(), server_default='0', nullable=False),
    sa.ForeignKeyConstraint(['bot_id'], ['bots.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('booking_services', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_booking_services_bot_id'), ['bot_id'], unique=False)

    op.create_table('booking_settings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('bot_id', sa.Integer(), nullable=False),
    sa.Column('timezone', sa.String(length=64), server_default='Asia/Tashkent', nullable=False),
    sa.Column('auto_confirm', sa.Boolean(), server_default='1', nullable=False),
    sa.Column('slot_step_min', sa.Integer(), server_default='30', nullable=False),
    sa.Column('min_notice_min', sa.Integer(), server_default='60', nullable=False),
    sa.Column('max_days_ahead', sa.Integer(), server_default='30', nullable=False),
    sa.Column('cancel_deadline_min', sa.Integer(), server_default='120', nullable=False),
    sa.Column('reminders', sa.JSON(), nullable=False),
    sa.Column('contact_text', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['bot_id'], ['bots.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('bot_id')
    )
    op.create_table('booking_staff',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('bot_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default='1', nullable=False),
    sa.Column('position', sa.Integer(), server_default='0', nullable=False),
    sa.ForeignKeyConstraint(['bot_id'], ['bots.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('booking_staff', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_booking_staff_bot_id'), ['bot_id'], unique=False)

    op.create_table('booking_days_off',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('bot_id', sa.Integer(), nullable=False),
    sa.Column('staff_id', sa.Integer(), nullable=True),
    sa.Column('day', sa.Date(), nullable=False),
    sa.ForeignKeyConstraint(['bot_id'], ['bots.id'], ),
    sa.ForeignKeyConstraint(['staff_id'], ['booking_staff.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('booking_days_off', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_booking_days_off_bot_id'), ['bot_id'], unique=False)

    op.create_table('booking_hours',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('bot_id', sa.Integer(), nullable=False),
    sa.Column('staff_id', sa.Integer(), nullable=True),
    sa.Column('weekday', sa.Integer(), nullable=False),
    sa.Column('start_min', sa.Integer(), nullable=False),
    sa.Column('end_min', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['bot_id'], ['bots.id'], ),
    sa.ForeignKeyConstraint(['staff_id'], ['booking_staff.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('booking_hours', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_booking_hours_bot_id'), ['bot_id'], unique=False)

    op.create_table('booking_staff_services',
    sa.Column('staff_id', sa.Integer(), nullable=False),
    sa.Column('service_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['service_id'], ['booking_services.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['staff_id'], ['booking_staff.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('staff_id', 'service_id')
    )
    op.create_table('bookings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('bot_id', sa.Integer(), nullable=False),
    sa.Column('service_id', sa.Integer(), nullable=True),
    sa.Column('staff_id', sa.Integer(), nullable=True),
    sa.Column('tg_user_id', sa.BigInteger(), nullable=False),
    sa.Column('client_name', sa.String(length=255), nullable=False),
    sa.Column('phone', sa.String(length=32), nullable=True),
    sa.Column('service_name', sa.String(length=120), nullable=False),
    sa.Column('staff_name', sa.String(length=120), nullable=True),
    sa.Column('price', sa.Integer(), nullable=True),
    sa.Column('start_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('end_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('status', sa.String(length=16), server_default='pending', nullable=False),
    sa.Column('reminders_sent', sa.JSON(), nullable=False),
    sa.Column('cancelled_by', sa.String(length=16), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['bot_id'], ['bots.id'], ),
    sa.ForeignKeyConstraint(['service_id'], ['booking_services.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['staff_id'], ['booking_staff.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('bookings', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_bookings_bot_id'), ['bot_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_bookings_start_at'), ['start_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_bookings_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_bookings_tg_user_id'), ['tg_user_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('bookings', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_bookings_tg_user_id'))
        batch_op.drop_index(batch_op.f('ix_bookings_status'))
        batch_op.drop_index(batch_op.f('ix_bookings_start_at'))
        batch_op.drop_index(batch_op.f('ix_bookings_bot_id'))

    op.drop_table('bookings')
    op.drop_table('booking_staff_services')
    with op.batch_alter_table('booking_hours', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_booking_hours_bot_id'))

    op.drop_table('booking_hours')
    with op.batch_alter_table('booking_days_off', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_booking_days_off_bot_id'))

    op.drop_table('booking_days_off')
    with op.batch_alter_table('booking_staff', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_booking_staff_bot_id'))

    op.drop_table('booking_staff')
    op.drop_table('booking_settings')
    with op.batch_alter_table('booking_services', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_booking_services_bot_id'))

    op.drop_table('booking_services')
