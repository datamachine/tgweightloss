# Standard Library
import logging
import os.path
import re
import configparser
from functools import wraps, partial

# 3rd Party Libraries
from twx import botapi
from twx.botapi.helpers.update_loop import UpdateLoop, Scope, Permission

# My Packages
from database import *
from sqlalchemy import engine_from_config

def require_group(f):
    @wraps(f)
    def wrapper(*args, **kwds):
        session = args[0].db.Session()
        chat = session.query(Chat).filter(Chat.id == args[1].chat.id).first()
        if not chat:
            args[0].bot.send_message(chat_id=args[1].chat.id, text="Can't run this command without registering first. Please run /setup_group",
                                     reply_to_message_id=args[1].message_id)
        else:
            return f(*args, **kwds)
    return wrapper

class BookClubBot:
    def __init__(self, config):
        self.config = config
        self.db = Database()
        self.logger = logging.Logger("BookClubBot")

        self.bot = botapi.TelegramBot(token=self.config['BookClubBot']['bot_token'])
        self.bot.update_bot_info().wait()

        self.update_loop = UpdateLoop(self.bot, self)

        # Admin Commands
        self.update_loop.register_command(name='setup_group', permission=Permission.Admin, function=self.setup_group)
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
    def setup_group(self, msg, arguments, **kwargs):
        session = self.db.Session()

        if msg.chat.type in ["group", "supergroup"]:
            chat = session.query(Chat).filter(Chat.id == msg.chat.id).first()
            if not chat:
                chat = Chat()
                chat.id = msg.chat.id

                chat.username = msg.chat.username
                chat.title = msg.chat.title

                session.add(chat)
                session.commit()

                self.bot.send_message(chat_id=msg.chat.id, text="Registered!", reply_to_message_id=msg.message_id)
            else:
                self.bot.send_message(chat_id=msg.chat.id, text="Already registered, use /config_group to change settings.", reply_to_message_id=msg.message_id)
        elif msg.chat.type == "private":
            self.bot.send_message(chat_id=msg.chat.id, text="TODO: Register from PM", reply_to_message_id=msg.message_id)  # TODO: Register from PM


    @require_group
    def add_book(self, msg, arguments, **kwargs):
        query = self.bot.send_message(chat_id=msg.chat.id, text="Author of book to add?",
                                      reply_markup=botapi.ForceReply.create(selective=True), reply_to_message_id=msg.message_id).join().result
        self.update_loop.register_reply_watch(message_id=query.message_id, function=self.add_book__set_author)

    def add_book__set_author(self, msg, arguments, **kwargs):
        # TODO: Validate text?
        query = self.bot.send_message(chat_id=msg.chat.id, text="Title of book to add?",
                                      reply_markup=botapi.ForceReply.create(selective=True), reply_to_message_id=msg.message_id).join().result
        self.update_loop.register_reply_watch(message_id=query.message_id, function=partial(self.add_book__set_title, msg.text))

    def add_book__set_title(self, author_name, msg, arguments, **kwargs):
        session = self.db.Session()

        # TODO: Look up the book, maybe another group has entered it?

        author = session.query(Author).filter(Author.name == author_name).first()  # TODO: Look up on GoodReads, for both an ID and a bit of fuzzy searching
                                                                                   # ("Arthur C Clarke" vs "Arthur C. Clarke" vs "Sir Arthur C Clarke")
        if not author:
            author = Author()
            author.name = author_name

            session.add(author)

        book = session.query(Book).filter(Book.title == msg.text).first()  # TODO: Look up on GoodReads, for both an ID and a bit of fuzzy searching
        if not book:
            book = Book()
            book.author = author
            book.title = msg.text
            session.add(book)

        assignment = session.query(BookAssignment).filter(BookAssignment.book_id == book.id).filter(BookAssignment.chat_id == msg.chat.id).first()
        if not assignment:
            assignment = BookAssignment()
            assignment.book = book
            assignment.chat_id = msg.chat.id
            session.add(assignment)
            session.commit()
            self.bot.send_message(chat_id=msg.chat.id, text=f"Added book to the group: {book.friendly_name}", reply_to_message_id=msg.message_id)

    @require_group
    def register_ebook(self, msg, arguments, **kwargs):
        print("Registering Ebook! " + msg.text)

    @require_group
    def register_audiobook(self, msg, arguments, **kwargs):
        print("Registering Audiobook! " + msg.text)

    @require_group
    def set_due_date(self, msg, arguments, **kwargs):
        print("Setting Due date! " + msg.text)

    @require_group
    def set_progress(self, msg, arguments, **kwargs):
        print("Setting progress! " + msg.text)

    @require_group
    def start_book(self, msg, arguments, **kwargs):
        session = self.db.Session()

        open_books = session.query(BookAssignment).filter(BookAssignment.chat_id == msg.chat.id).filter(BookAssignment.done == False).filter(BookAssignment.current == False).all()
        current_book = session.query(BookAssignment).filter(BookAssignment.chat_id == msg.chat.id).filter(BookAssignment.current == True).all()

        if len(open_books) == 0:
            self.bot.send_message(chat_id=msg.chat.id, text="There are no open books to start.",
                                  reply_to_message_id=msg.message_id)
            
            return

        reply = ""

        if len(current_book) > 0:
            reply += f"There are currently {len(current_book)} active books. \n"
        reply += "Which book do you want to set as active?"

        keyboard = []
        for book_assign in open_books:
            keyboard.append([book_assign.book.friendly_name])

        query = self.bot.send_message(chat_id=msg.chat.id, text=reply,
                                      reply_markup=botapi.ReplyKeyboardMarkup.create(keyboard, one_time_keyboard=True, resize_keyboard=True, selective=True),
                                      reply_to_message_id=msg.message_id).join().result
        self.update_loop.register_reply_watch(message_id=query.message_id, function=self.start_book__select_book)

    def start_book__select_book(self, msg, arguments, **kwargs):
        session = self.db.Session()

        author_name, book_name = msg.text.split(' - ', maxsplit=1)
        assignment = session.query(BookAssignment).join(Book).join(Author).filter(Book.title == book_name).filter(Author.name == author_name).filter(BookAssignment.chat_id == msg.chat.id).first()

        if not assignment:
            self.bot.send_message(chat_id=msg.chat.id, text="Error starting book, cannot find it in DB.")

        assignment.current = True

        session.add(assignment)
        session.commit()

        self.bot.send_message(chat_id=msg.chat.id, text=f"Starting book {assignment.book.friendly_name}.")

    # User Commands
    @require_group
    def get_progress(self, msg, arguments, **kwargs):
        print("Getting progress! " + msg.text)

    @require_group
    def get_due_date(self, msg, arguments, **kwargs):
        print("Getting due date! " + msg.text)

    @require_group
    def get_book(self, msg, arguments, **kwargs):
        print("Getting a book! " + msg.text)

    @require_group
    def join_book(self, msg, arguments, **kwargs):
        print("Joined a book! " + msg.text)


if __name__ == '__main__':
    # Run as script
    if not os.path.exists("config.ini"):
        exit("Config file not found!")
    configfile = configparser.ConfigParser()
    configfile.read('config.ini')

    engine = engine_from_config(configfile['BookClubBot'], 'sqlalchemy.')
    DBSession.configure(bind=engine)

    mybot = BookClubBot(configfile)
    mybot.run()