"""use_timezones

Revision ID: 5a72882270c2
Revises: 9cddf0ff1c31
Create Date: 2017-01-03 17:37:07.893515

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5a72882270c2'
down_revision = '9cddf0ff1c31'
branch_labels = None
depends_on = None


def timezone_change(require):
    op.alter_column(
        table_name='book_review',
        column_name='review_date',
        type_=sa.DateTime(timezone=require)
    )
    op.alter_column(
        table_name='book_assignment',
        column_name='start_date',
        type_=sa.DateTime(timezone=require)
    )
    op.alter_column(
        table_name='book_schedule',
        column_name='due_date',
        type_=sa.DateTime(timezone=require)
    )
    op.alter_column(
        table_name='user_participation',
        column_name='join_date',
        type_=sa.DateTime(timezone=require)
    )
    op.alter_column(
        table_name='progress_update',
        column_name='update_date',
        type_=sa.DateTime(timezone=require)
    )


def upgrade():
    timezone_change(True)


def downgrade():
    timezone_change(False)
