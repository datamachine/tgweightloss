from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import (
    Column,
    String,
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


class Contest(Base):
    __tablename__ = 'contest'

    id = Column(Integer, primary_key=True)
    title = Column(String)
    date_start = Column(DateTime)
    date_end = Column(DateTime)

    @property
    def friendly_name(self):
        return f"{self.title}: {self.date_start} - {self.date_end}"


class UserParticipation(Base):
    __tablename__ = 'user_participation'

    id = Column(Integer, primary_key=True)

    join_date = Column(DateTime, default=func.now())

    goal_weight = Column(Integer)
    start_weight = Column(Integer)

    user_id = Column(BigInteger, ForeignKey('user.id'))
    user = relationship('User', backref='participation')
    contest_id = Column(Integer, ForeignKey('contest.id'))
    contest = relationship('Contest', backref='participants')

    active = Column(Boolean, default=True)


class ProgressUpdate(Base):
    __tablename__ = 'progress_update'

    id = Column(Integer, primary_key=True)

    update_date = Column(DateTime(timezone=True), default=func.now())
    progress = Column(Integer)  # Weight Check-in

    participation_id = Column(Integer, ForeignKey('user_participation.id'))
    participation = relationship('UserParticipation', backref='updates')
