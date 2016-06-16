# Standard Library
import logging
import os.path
import configparser

# 3rd Party Libraries
import twx.botapi

# My Packages
import database


class BookClubBot(object):
    def __init__(self, config):
        self.config = config
        self.database = database.Database()
        self.logger = logging.Logger("BookClubBot")
        self.bot = twx.botapi.TelegramBot(self.config['BookClubBot']['bot_token'])

    def run(self):
        pass
        # update_id = 0
        # while True:
        #     pass


if __name__ == '__main__':
    # Run as script
    if not os.path.exists("config.ini"):
        exit("Config file not found!")
    configfile = configparser.ConfigParser()
    configfile.read('config.ini')

    bot = BookClubBot(configfile)
    bot.run()
