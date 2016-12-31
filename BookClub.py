# Standard Library
import logging
import os.path
import re
import configparser
from functools import wraps, partial

# 3rd Party Libraries
from twx import botapi
from twx.botapi.helpers.update_loop import UpdateLoop, Permission

# My Packages
from database import *
from sqlalchemy import engine_from_config

def update_metadata(f):
    @wraps(f)
    def wrapper(*args, **kwds):
        if args[1].chat.type in ['supergroup', 'group']:
            Chat.create_or_get(args[1].chat)
        User.create_or_get(args[1].sender)
        return f(*args, **kwds)
    return wrapper

class BookClubBot:
    def __init__(self, config):
        self.config = config
        self.logger = logging.Logger("BookClubBot")

        self.bot = botapi.TelegramBot(token=self.config['BookClubBot']['bot_token'])
        self.bot.update_bot_info().wait()

        self.update_loop = UpdateLoop(self.bot, self)

        # Admin Commands
        self.update_loop.register_command(name='add_book', permission=Permission.Admin, function=self.add_book)
        self.update_loop.register_command(name='start_book', permission=Permission.Admin, function=self.start_book)
        self.update_loop.register_command(name='register_ebook', permission=Permission.Admin, function=self.register_ebook)
        self.update_loop.register_command(name='register_audiobook', permission=Permission.Admin, function=self.register_audiobook)
        self.update_loop.register_command(name='set_due_date', permission=Permission.Admin, function=self.set_due_date)

        # User Commands
        self.update_loop.register_command(name='get_book', function=self.get_book)
        self.update_loop.register_command(name='join_book', function=self.join_book)
        self.update_loop.register_command(name='set_progress', function=self.set_progress)
        self.update_loop.register_command(name='get_progress',  function=self.get_progress)
        self.update_loop.register_command(name='get_due_date',  function=self.get_due_date)

    def run(self):
        self.update_loop.run()  # Run update loop and register as handler

    # Admin Commands
    @update_metadata
    def add_book(self, msg, arguments, **kwargs):
        query = self.bot.send_message(chat_id=msg.chat.id, text="Author of book to add?",
                                      reply_markup=botapi.ForceReply.create(selective=True), reply_to_message_id=msg.message_id).join().result
        self.update_loop.register_reply_watch(message=query, function=self.add_book__set_author)

    def add_book__set_author(self, msg, arguments, **kwargs):
        # TODO: Validate text?
        query = self.bot.send_message(chat_id=msg.chat.id, text="Title of book to add?",
                                      reply_markup=botapi.ForceReply.create(selective=True), reply_to_message_id=msg.message_id).join().result
        self.update_loop.register_reply_watch(message=query, function=partial(self.add_book__set_title, msg.text))

    def add_book__set_title(self, author_name, msg, arguments, **kwargs):
        # TODO: Look up the book, maybe another group has entered it?
        author = DBSession.query(Author).filter(Author.name == author_name).first()  # TODO: Look up on GoodReads, for both an ID and a bit of fuzzy searching
                                                                                     # ("Arthur C Clarke" vs "Arthur C. Clarke" vs "Sir Arthur C Clarke")
        if not author:
            author = Author()
            author.name = author_name

            DBSession.add(author)

        book = DBSession.query(Book).filter(Book.title == msg.text).first()  # TODO: Look up on GoodReads, for both an ID and a bit of fuzzy searching
        if not book:
            book = Book()
            book.author = author
            book.title = msg.text
            DBSession.add(book)

        assignment = DBSession.query(BookAssignment).filter(BookAssignment.book_id == book.id).filter(BookAssignment.chat_id == msg.chat.id).first()
        if not assignment:
            assignment = BookAssignment()
            assignment.book = book
            assignment.chat_id = msg.chat.id
            DBSession.add(assignment)
            DBSession.commit()
            self.bot.send_message(chat_id=msg.chat.id, text=f"Added book to the group: {book.friendly_name}", reply_to_message_id=msg.message_id)

    @update_metadata
    def register_ebook(self, msg, arguments, **kwargs):
        print("Registering Ebook! " + msg.text)

    @update_metadata
    def register_audiobook(self, msg, arguments, **kwargs):
        print("Registering Audiobook! " + msg.text)

    @update_metadata
    def set_due_date(self, msg, arguments, **kwargs):
        print("Setting Due date! " + msg.text)

    @update_metadata
    def start_book(self, msg, arguments, **kwargs):
        open_books = DBSession.query(BookAssignment).filter(BookAssignment.chat_id == msg.chat.id).filter(BookAssignment.done == False).filter(BookAssignment.current == False).all()
        current_book = DBSession.query(BookAssignment).filter(BookAssignment.chat_id == msg.chat.id).filter(BookAssignment.current == True).all()

        if len(open_books) == 0:
            self.bot.send_message(chat_id=msg.chat.id, text="There are no open books to start.",
                                  reply_to_message_id=msg.message_id)
            return

        reply = ""

        if len(current_book) > 0:
            reply += f"There are currently {len(current_book)} active books. \n"
        reply += "Which book do you want to set as active?"

        # TODO: Support a "More" button.
        keyboard_rows = []
        for book_assign in open_books:
            keyboard_rows.append([botapi.InlineKeyboardButton(text=book_assign.book.friendly_name, callback_data=str(book_assign.book.id))])

        keyboard = botapi.InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

        query = self.bot.send_message(chat_id=msg.chat.id, text=reply,
                                      reply_markup=keyboard, reply_to_message_id=msg.message_id).join().result
        self.update_loop.register_inline_reply(message=query, srcmsg=msg, function=self.start_book__select_book, permission=Permission.SameUser)
        pass

    def start_book__select_book(self, cbquery, data, **kwargs):
        assignment = DBSession.query(BookAssignment).filter(BookAssignment.book_id==int(data)).first()

        if not assignment:
            self.bot.send_message(chat_id=cbquery.message.chat.id, text="Error starting book, cannot find it in DB.")

        assignment.current = True

        DBSession.add(assignment)
        DBSession.commit()

        self.bot.edit_message_text(chat_id=cbquery.message.chat.id, message_id=cbquery.message.message_id, text=f"Starting book {assignment.book.friendly_name}.")

    # User Commands
    @update_metadata
    def get_progress(self, msg, arguments, **kwargs):
        print("Getting progress! " + msg.text)

    @update_metadata
    def set_progress(self, msg, arguments, **kwargs):
        user = User.create_or_get(msg.sender)
        joined_books = DBSession.query(BookAssignment).join(UserParticipation).\
            filter(UserParticipation.book_assignment_id == BookAssignment.id).\
            filter(BookAssignment.current == True).all()

        if len(joined_books) == 0:
            self.bot.send_message(chat_id=msg.chat.id, text="You are not currently reading any books!", reply_to_message_id=msg.message_id)
            return

        reply = "Which book do you want to join?"

        keyboard_rows = []
        for book_assign in joined_books:
            keyboard_rows.append([botapi.InlineKeyboardButton(text=book_assign.book.friendly_name, callback_data=str(book_assign.book.id))])

        keyboard = botapi.InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

        query = self.bot.send_message(chat_id=msg.chat.id, text=reply,
                                      reply_markup=keyboard, reply_to_message_id=msg.message_id).join().result
        self.update_loop.register_inline_reply(message=query, srcmsg=msg, function=self.set_progress__select_book, permission=Permission.SameUser)



    def set_progress__select_book(self, cbquery, data, **kwargs):
        pass

    @update_metadata
    def get_due_date(self, msg, arguments, **kwargs):
        print("Getting due date! " + msg.text)

    @update_metadata
    def get_book(self, msg, arguments, **kwargs):
        print("Getting a book! " + msg.text)

    @update_metadata
    def join_book(self, msg, arguments, **kwargs):
        current_books = DBSession.query(BookAssignment).filter(BookAssignment.chat_id == msg.chat.id).filter(BookAssignment.current == True).all()

        if len(current_books) == 0:
            self.bot.send_message(chat_id=msg.chat.id, text="No books are currently being read!", reply_to_message_id=msg.message_id)
            return

        if len(current_books) == 1:
            user = User.create_or_get(msg.sender)
            participation = UserParticipation()
            participation.book_assignment = current_books[0]
            participation.user = User.create_or_get(user)

            DBSession.add(participation)
            DBSession.commit()

            self.bot.send_message(chat_id=msg.chat.id,
                                  text=f"@{msg.sender.username} joined book {current_books[0].book.friendly_name}!",
                                  reply_to_message_id=msg.message_id)
            return

        reply = "Which book do you want to join?"

        keyboard_rows = []
        for book_assign in current_books:
            keyboard_rows.append([botapi.InlineKeyboardButton(text=book_assign.book.friendly_name, callback_data=str(book_assign.book.id))])

        keyboard = botapi.InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

        query = self.bot.send_message(chat_id=msg.chat.id, text=reply,
                                      reply_markup=keyboard, reply_to_message_id=msg.message_id).join().result
        self.update_loop.register_inline_reply(message=query, srcmsg=msg, function=self.join_book__select_book, permission=Permission.SameUser)

    def join_book__select_book(self, cbquery, data, **kwargs):
        assignment = DBSession.query(BookAssignment).filter(BookAssignment.book_id==int(data)).first()
        user = User.create_or_get(cbquery.sender)

        if not assignment:
            self.bot.send_message(chat_id=cbquery.message.chat.id, text="Error joining book, cannot find it in DB.")

        participation = UserParticipation()
        participation.book_assignment = assignment
        participation.user = user

        DBSession.add(participation)
        DBSession.commit()

        self.bot.edit_message_text(chat_id=cbquery.message.chat.id, message_id=cbquery.message.message_id,
                                   text=f"@{cbquery.sender.username} joined book {assignment.book.friendly_name}!")

if __name__ == '__main__':
    # Run as script
    if not os.path.exists("config.ini"):
        exit("Config file not found!")
    configfile = configparser.ConfigParser()
    configfile.read('config.ini')

    engine = engine_from_config(configfile['BookClubBot'], 'sqlalchemy.')
    DBSession.configure(bind=engine)
    Base.metadata.create_all(engine)

    mybot = BookClubBot(configfile)
    mybot.run()