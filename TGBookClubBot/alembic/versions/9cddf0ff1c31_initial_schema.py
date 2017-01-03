"""Initial Schema

Revision ID: 9cddf0ff1c31
Revises: 
Create Date: 2017-01-03 12:28:02.548443

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9cddf0ff1c31'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('author',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('name', sa.String(), nullable=True),
    sa.Column('goodreads_id', sa.BigInteger(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('chat',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('type', sa.String(), nullable=True),
    sa.Column('title', sa.String(), nullable=True),
    sa.Column('username', sa.String(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('user',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('first_name', sa.String(), nullable=True),
    sa.Column('last_name', sa.String(), nullable=True),
    sa.Column('username', sa.String(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('book',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('title', sa.String(), nullable=True),
    sa.Column('isbn', sa.String(), nullable=True),
    sa.Column('goodreads_id', sa.BigInteger(), nullable=True),
    sa.Column('author_id', sa.BigInteger(), nullable=True),
    sa.ForeignKeyConstraint(['author_id'], ['author.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('book_assignment',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('schedule_type', sa.String(), nullable=True),
    sa.Column('start_date', sa.DateTime(), nullable=True),
    sa.Column('done', sa.Boolean(), nullable=True),
    sa.Column('current', sa.Boolean(), nullable=True),
    sa.Column('audiobook_message_id', sa.BigInteger(), nullable=True),
    sa.Column('ebook_message_id', sa.BigInteger(), nullable=True),
    sa.Column('book_id', sa.BigInteger(), nullable=True),
    sa.Column('chat_id', sa.BigInteger(), nullable=True),
    sa.ForeignKeyConstraint(['book_id'], ['book.id'], ),
    sa.ForeignKeyConstraint(['chat_id'], ['chat.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('book_review',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('review_date', sa.DateTime(), nullable=True),
    sa.Column('rating', sa.BigInteger(), nullable=True),
    sa.Column('review_text', sa.Text(), nullable=True),
    sa.Column('user_id', sa.BigInteger(), nullable=True),
    sa.Column('book_id', sa.BigInteger(), nullable=True),
    sa.ForeignKeyConstraint(['book_id'], ['book.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('book_schedule',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('due_date', sa.DateTime(), nullable=True),
    sa.Column('start', sa.BigInteger(), nullable=True),
    sa.Column('end', sa.BigInteger(), nullable=True),
    sa.Column('book_assignment_id', sa.BigInteger(), nullable=True),
    sa.ForeignKeyConstraint(['book_assignment_id'], ['book_assignment.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('user_participation',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('join_date', sa.DateTime(), nullable=True),
    sa.Column('edition', sa.String(), nullable=True),
    sa.Column('user_id', sa.BigInteger(), nullable=True),
    sa.Column('book_assignment_id', sa.BigInteger(), nullable=True),
    sa.Column('active', sa.Boolean(), nullable=True),
    sa.ForeignKeyConstraint(['book_assignment_id'], ['book_assignment.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('progress_update',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('update_date', sa.DateTime(), nullable=True),
    sa.Column('progress', sa.BigInteger(), nullable=True),
    sa.Column('participation_id', sa.BigInteger(), nullable=True),
    sa.ForeignKeyConstraint(['participation_id'], ['user_participation.id'], ),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('progress_update')
    op.drop_table('user_participation')
    op.drop_table('book_schedule')
    op.drop_table('book_review')
    op.drop_table('book_assignment')
    op.drop_table('book')
    op.drop_table('user')
    op.drop_table('chat')
    op.drop_table('author')
