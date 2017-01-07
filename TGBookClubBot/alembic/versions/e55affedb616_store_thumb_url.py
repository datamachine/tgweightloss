"""Store thumb url

Revision ID: e55affedb616
Revises: 5a72882270c2
Create Date: 2017-01-07 02:27:07.410775

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e55affedb616'
down_revision = '5a72882270c2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('book', sa.Column('thumb_url', sa.String(), nullable=True))


def downgrade():
    op.drop_column('book', 'thumb_url')
