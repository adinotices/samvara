"""add users.stripe_customer_id for direct-to-Samvara Stripe billing

Samvara now charges consumers directly via Stripe by default (revenue goes
to Samvara, not Beeminder) — see app/billing.py and app/stripe_billing.py.
Beeminder remains wired up but is gated to the app owner's account only.

Revision ID: a1c9e6f2b4d7
Revises: 9c8f7d3b2e1a
Create Date: 2026-08-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c9e6f2b4d7'
down_revision: Union[str, Sequence[str], None] = '9c8f7d3b2e1a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('users') as batch_op:
        batch_op.add_column(sa.Column('stripe_customer_id', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('stripe_customer_id')
