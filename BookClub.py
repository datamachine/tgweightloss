# Standard Library
import logging
import os.path
import re
import configparser

# 3rd Party Libraries
from twx import botapi
from twx.botapi.helpers.update_loop import UpdateLoop

# My Packages
import database


class BookClubBot:
    def __init__(self, config):
        self.config = config
        self.database = database.Database()
        self.logger = logging.Logger("BookClubBot")

        self.bot = botapi.TelegramBot(token=self.config['BookClubBot']['bot_token'])
        self.bot.update_bot_info().wait()

        self.update_loop = UpdateLoop(self.bot, self)

        self.update_loop.register_command(name='add_book', function=self.add_book)
        self.update_loop.register_command(name='addbook', function=self.add_book)

    def run(self):
        self.update_loop.run()  # Run update loop and register as handler

    def add_book(self, bot, msg, **kwargs):
        print("Adding book! " + msg.text)


if __name__ == '__main__':
    # Run as script
    if not os.path.exists("config.ini"):
        exit("Config file not found!")
    configfile = configparser.ConfigParser()
    configfile.read('config.ini')

    bot = BookClubBot(configfile)
    bot.run()