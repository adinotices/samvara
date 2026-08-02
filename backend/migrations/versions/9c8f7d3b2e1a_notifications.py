"""add notifications table for server-driven alerts

Add notifications table to track events: commitment charges, charge failures,
auto-missed commitments, penalties, access requests, device logins, etc.
Clients poll this table to display server-driven notifications to users.

Revision ID: 9c8f7d3b2e1a
Revises: 8b4f2a8c5e6d
Create Date: 2026-08-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9c8f7d3b2e1a'
down_revision: Union[str, Sequence[str], None] = '8b4f2a8c5e6d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('notifications',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('type', sa.String(), nullable=False),
    sa.Column('title', sa.String(), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('read', sa.Boolean(), nullable=False, server_default='false'),
    sa.Column('data', sa.Text(), nullable=True),
    sa.Column('created_at', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_notifications_user_id', 'notifications', ['user_id'], unique=False)
    op.create_index('ix_notifications_read', 'notifications', ['user_id', 'read'], unique=False)
    op.create_index('ix_notifications_created_at', 'notifications', ['user_id', 'created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_notifications_created_at', table_name='notifications')
    op.drop_index('ix_notifications_read', table_name='notifications')
    op.drop_index('ix_notifications_user_id', table_name='notifications')
    op.drop_table('notifications')
