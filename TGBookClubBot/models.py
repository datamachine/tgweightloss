from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import (
    Column,
    String,
    Text,
    BigInteger,
    Integer,
    DateTime,
    ForeignKey,
    Boolean,
    func
)

from sqlalchemy.orm import (
    scoped_session,
    sessionmaker,
    relationship,
    )


DBSession = scoped_session(sessionmaker(expire_on_commit=False))

# Models
Base = declarative_base()


class Chat(Base):
    __tablename__ = 'chat'

    id = Column(BigInteger, primary_key=True)
    type = Column(String)
    title = Column(String)
    username = Column(String)

    @staticmethod
    def create_or_get(src_chat):
        chat = DBSession.query(Chat).filter(Chat.id == src_chat.id).first()
        if not chat:
            chat = Chat()
            chat.id = src_chat.id
        chat.username = src_chat.username
        chat.title = src_chat.title

        DBSession.add(chat)
        DBSession.commit()

        return chat

class User(Base):
    __tablename__ = 'user'

    id = Column(BigInteger, primary_key=True)
    first_name = Column(String)
    last_name = Column(String)
    username = Column(String)

    def active_participation(self, chat_id=None):
        if chat_id is not None:
            return [p for p in self.participation if p.active and p.book_assignment.chat_id == chat_id]
        else:
            return [p for p in self.participation if p.active]

    @staticmethod
    def create_or_get(sender):
        user = DBSession.query(User).filter(User.id == sender.id).first()
        if not user:
            user = User()
            user.id = sender.id
        user.username = sender.username
        user.first_name = sender.first_name
        user.last_name = sender.last_name

        DBSession.add(user)
        DBSession.commit()

        return user

class Book(Base):
    __tablename__ = 'book'

    id = Column(BigInteger, primary_key=True)
    title = Column(String)
    isbn = Column(String)
    goodreads_id = Column(BigInteger)

    author_id = Column(BigInteger, ForeignKey('author.id'))
    author = relationship('Author', backref='books')

    @property
    def friendly_name(self):
        return f"{self.author.name} - {self.title}"


class Author(Base):
    __tablename__ = 'author'

    id = Column(BigInteger, primary_key=True)
    name = Column(String)
    goodreads_id = Column(BigInteger)


class BookReview(Base):
    __tablename__ = 'book_review'

    id = Column(BigInteger, primary_key=True)
    review_date = Column(DateTime(timezone=True), default=func.now())
    rating = Column(BigInteger)
    review_text = Column(Text)

    user_id = Column(BigInteger, ForeignKey('user.id'))
    user = relationship('User', backref='reviews')
    book_id = Column(BigInteger, ForeignKey('book.id'))
    book = relationship('Book', backref='reviews')


class BookAssignment(Base):
    __tablename__ = 'book_assignment'

    id = Column(BigInteger, primary_key=True)
    schedule_type = Column(String, default="chapters")
    start_date = Column(DateTime(timezone=True), default=func.now())
    done = Column(Boolean, default=False)
    current = Column(Boolean, default=False)
    
    audiobook_message_id = Column(BigInteger)
    ebook_message_id = Column(BigInteger)

    book_id = Column(BigInteger, ForeignKey('book.id'))
    book = relationship('Book', backref='assignments')
    chat_id = Column(BigInteger, ForeignKey('chat.id'))
    chat = relationship('Chat', backref='assignments')


class BookSchedule(Base):
    __tablename__ = 'book_schedule'

    id = Column(BigInteger, primary_key=True)
    due_date = Column(DateTime(timezone=True))
    start = Column(BigInteger)
    end = Column(BigInteger)

    book_assignment_id = Column(BigInteger, ForeignKey('book_assignment.id'))
    book_assignment = relationship('BookAssignment', backref='schedules')


class UserParticipation(Base):
    __tablename__ = 'user_participation'

    id = Column(BigInteger, primary_key=True)

    join_date = Column(DateTime, default=func.now())
    edition = Column(String)

    user_id = Column(BigInteger, ForeignKey('user.id'))
    user = relationship('User', backref='participation')
    book_assignment_id = Column(BigInteger, ForeignKey('book_assignment.id'))
    book_assignment = relationship('BookAssignment', backref='participation')

    active = Column(Boolean, default=True)

    @property
    def book(self):
        return self.book_assignment.book

class ProgressUpdate(Base):
    __tablename__ = 'progress_update'

    id = Column(BigInteger, primary_key=True)

    update_date = Column(DateTime(timezone=True), default=func.now())
    progress = Column(BigInteger)  # TODO: Progress in pages? Maybe track as percent? Edition is available.

    participation_id = Column(BigInteger, ForeignKey('user_participation.id'))
    participation = relationship('UserParticipation', backref='updates')
