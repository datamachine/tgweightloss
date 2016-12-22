# Standard Library
import logging
import os.path
import re
import configparser
from functools import wraps

# 3rd Party Libraries
from twx import botapi
from twx.botapi.helpers.update_loop import UpdateLoop, Scope, Permission

# My Packages
import database


def require_group(f):
    @wraps(f)
    def wrapper(*args, **kwds):
        # TODO: Ensure we're in the DB
        return f(*args, **kwds)
    return wrapper

class BookClubBot:
    def __init__(self, config):
        self.config = config
        self.database = database.Database()
        self.logger = logging.Logger("BookClubBot")

        self.bot = botapi.TelegramBot(token=self.config['BookClubBot']['bot_token'])
        self.bot.update_bot_info().wait()

        self.update_loop = UpdateLoop(self.bot, self)

        # Admin Commands
        self.update_loop.register_command(name='setup_group', permission=Permission.Admin, function=self.setup_group)
        self.update_loop.register_command(name='add_book', permission=Permission.Admin, function=self.add_book)
        self.update_loop.register_command(name='set_book', permission=Permission.Admin, function=self.set_book)
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
    def setup_group(self, bot, msg, arguments, **kwargs):
        chat = self.database.session.query(database.Chat).filter(database.Chat.id==msg.chat.id).first()

        if not chat:
            chat = database.Chat()
            chat.id = msg.chat.id

        chat.username = msg.chat.username
        chat.title = msg.chat.title

        self.database.session.add(chat)
        print("Registered!")

    @require_group
    def add_book(self, bot, msg, arguments, **kwargs):
        pass

    def register_ebook(self, bot, msg, arguments, **kwargs):
        print("Registering Ebook! " + msg.text)

    def register_audiobook(self, bot, msg, arguments, **kwargs):
        print("Registering Audiobook! " + msg.text)

    def set_due_date(self, bot, msg, arguments, **kwargs):
        print("Setting Due date! " + msg.text)

    def set_progress(self, bot, msg, arguments, **kwargs):
        print("Setting progress! " + msg.text)

    def set_book(self, bot, msg, arguments, **kwargs):
        print("Setting book! " + msg.text)

    # User Commands
    def get_progress(self, bot, msg, arguments, **kwargs):
        print("Getting progress! " + msg.text)

    def get_due_date(self, bot, msg, arguments, **kwargs):
        print("Getting due date! " + msg.text)

    def get_book(self, bot, msg, arguments, **kwargs):
        print("Getting a book! " + msg.text)

    def join_book(self, bot, msg, arguments, **kwargs):
        print("Joined a book! " + msg.text)


if __name__ == '__main__':
    # Run as script
    if not os.path.exists("config.ini"):
        exit("Config file not found!")
    configfile = configparser.ConfigParser()
    configfile.read('config.ini')

    bot = BookClubBot(configfile)
    bot.run()