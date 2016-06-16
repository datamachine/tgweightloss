from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy import (
    Column,
    String,
    Text,
    Integer,
    DateTime,
    ForeignKey,
)


class Database(object):
    def __init__(self):
        self.db = create_engine('sqlite:///data.db', echo=True)
        Base.metadata.create_all(self.db)


# Models
Base = declarative_base()


class Chat(Base):
    __tablename__ = 'chats'

    id = Column(Integer, primary_key=True)
    type = Column(String)
    title = Column(String)
    username = Column(String)


class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    first_name = Column(String)
    last_name = Column(String)
    username = Column(String)


class Book(Base):
    __tablename__ = 'books'

    id = Column(Integer, primary_key=True)
    title = Column(String)
    isbn = Column(String)
    goodreads_id = Column(Integer)

    author_id = Column(Integer, ForeignKey('authors.id'))
    author = relationship('Author', back_populates='books')


class Author(Base):
    __tablename__ = 'authors'

    id = Column(Integer, primary_key=True)
    name = Column(String)
    goodreads_id = Column(Integer)


class BookReview(Base):
    __tablename__ = 'book_reviews'

    id = Column(Integer, primary_key=True)
    review_date = Column(DateTime)
    rating = Column(Integer)
    review_text = Column(Text)

    user_id = Column(Integer, ForeignKey('users.id'))
    user = relationship('User', back_populates='reviews')
    book_id = Column(Integer, ForeignKey('books.id'))
    book = relationship('Book', back_populates='reviews')


class BookAssignment(Base):
    __tablename__ = 'book_assignments'

    id = Column(Integer, primary_key=True)
    schedule_type = Column(String)
    start_date = Column(DateTime)

    book_id = Column(Integer, ForeignKey('books.id'))
    book = relationship('Book', back_populates='assignments')
    chat_id = Column(Integer, ForeignKey('chats.id'))
    chat = relationship('Chat', back_populates='assignments')


class BookSchedule(Base):
    __tablename__ = 'book_schedules'

    id = Column(Integer, primary_key=True)
    due_date = Column(DateTime)
    start = Column(Integer)
    end = Column(Integer)

    book_assignment_id = Column(Integer, ForeignKey('book_assignments.id'))
    book_assignment = relationship('BookAssignment', back_populates='schedules')


class UserParticipation(Base):
    __tablename__ = 'user_participation'

    id = Column(Integer, primary_key=True)

    join_date = Column(DateTime)
    edition = Column(String)

    user_id = Column(Integer, ForeignKey('users.id'))
    user = relationship('User', back_populates='participation')
    book_assignment_id = Column(Integer, ForeignKey('book_assignments.id'))
    book_assignment = relationship('BookAssignment', back_populates='participation')


class ProgressUpdate(Base):
    __tablename__ = 'progress_updates'

    id = Column(Integer, primary_key=True)

    update_date = Column(DateTime)
    progress = Column(Integer)  # TODO: Progress in pages? Maybe track as percent? Edition is available.

    participation_id = Column(Integer, ForeignKey('user_participation.id'))
    participation = relationship('UserParticipation', back_populates='updates')
