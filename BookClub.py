import database
import logging


class BookClubBot(object):
    def __init__(self):
        self.database = database.Database()
        logging.info("Initialized!")

if __name__ == '__main__':
    # Run as script
    bot = BookClubBot()
