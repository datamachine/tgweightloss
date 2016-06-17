# Standard Library
import logging
import os.path
from threading import Thread
from time import sleep
import configparser

# 3rd Party Libraries
import twx.botapi

# My Packages
import database


class BookClubBot:
    def __init__(self, config):
        self.config = config
        self.database = database.Database()
        self.logger = logging.Logger("BookClubBot")
        self.twx = twx.botapi.TelegramBot(self.config['BookClubBot']['bot_token'])
        self.thread = Thread(target=self.main_loop)

    def run(self):
        self.thread.run()
        return self

    def main_loop(self):
        last_update = 0
        while True:
            # Process Telegram Events
            updates = self.twx.get_updates(last_update).wait()
            if updates:
                for update in updates:
                    if update:
                        last_update = update.update_id + 1
                        self.process_request(update)
            sleep(.1)

    def process_request(self, message):
        pass


if __name__ == '__main__':
    # Run as script
    if not os.path.exists("config.ini"):
        exit("Config file not found!")
    configfile = configparser.ConfigParser()
    configfile.read('config.ini')

    bot = BookClubBot(configfile)
    bot.run()
