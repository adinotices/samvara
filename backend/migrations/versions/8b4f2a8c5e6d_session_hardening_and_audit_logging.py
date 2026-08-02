"""session hardening and audit logging

Add device tracking (device_id on sessions, new devices table), audit logging
table for compliance, and created_at on sessions.

Revision ID: 8b4f2a8c5e6d
Revises: 837ecb16832a
Create Date: 2026-08-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8b4f2a8c5e6d'
down_revision: Union[str, Sequence[str], None] = '837ecb16832a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create devices table first (sessions.device_id references it)
    op.create_table('devices',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('user_agent', sa.String(), nullable=True),
    sa.Column('ip_address', sa.String(), nullable=True),
    sa.Column('created_at', sa.BigInteger(), nullable=False),
    sa.Column('last_seen_at', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_devices_user_id', 'devices', ['user_id'], unique=False)

    # Add columns to sessions table using batch mode for SQLite compatibility
    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('device_id', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('created_at', sa.BigInteger(), nullable=True))
        batch_op.create_foreign_key('fk_sessions_device_id', 'devices', ['device_id'], ['id'])
        batch_op.create_index('ix_sessions_device_id', ['device_id'], unique=False)

    # Create audit_logs table for compliance
    op.create_table('audit_logs',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('action', sa.String(), nullable=False),
    sa.Column('resource_type', sa.String(), nullable=True),
    sa.Column('resource_id', sa.String(), nullable=True),
    sa.Column('details', sa.Text(), nullable=True),
    sa.Column('ip_address', sa.String(), nullable=True),
    sa.Column('user_agent', sa.String(), nullable=True),
    sa.Column('created_at', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_audit_logs_user_id', 'audit_logs', ['user_id'], unique=False)
    op.create_index('ix_audit_logs_created_at', 'audit_logs', ['created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_audit_logs_created_at', table_name='audit_logs')
    op.drop_index('ix_audit_logs_user_id', table_name='audit_logs')
    op.drop_table('audit_logs')

    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.drop_index('ix_sessions_device_id')
        batch_op.drop_constraint('fk_sessions_device_id', type_='foreignkey')
        batch_op.drop_column('created_at')
        batch_op.drop_column('device_id')

    op.drop_index('ix_devices_user_id', table_name='devices')
    op.drop_table('devices')
