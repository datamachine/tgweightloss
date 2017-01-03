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
import sqlalchemy.exc

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

        # region command registration
        # Admin Commands
        self.update_loop.register_command(name='add_book', permission=Permission.Admin, function=self.add_book)
        self.update_loop.register_command(name='start_book', permission=Permission.Admin, function=self.start_book)
        self.update_loop.register_command(name='register_ebook', permission=Permission.Admin, function=self.register_ebook)
        self.update_loop.register_command(name='register_audiobook', permission=Permission.Admin, function=self.register_audiobook)
        self.update_loop.register_command(name='set_due_date', permission=Permission.Admin, function=self.set_due_date)

        # User Commands
        self.update_loop.register_command(name='get_book', function=self.get_book)
        self.update_loop.register_command(name='join_book', function=self.join_book)
        self.update_loop.register_command(name='quit_book', function=self.quit_book)
        self.update_loop.register_command(name='set_progress', function=self.set_progress)
        self.update_loop.register_command(name='get_progress',  function=self.get_progress)
        self.update_loop.register_command(name='get_due_date',  function=self.get_due_date)
        # endregion

    # Admin Commands
    # region add_book command
    @update_metadata
    def add_book(self, msg, arguments):
        query = self.bot.send_message(chat_id=msg.chat.id, text="Author of book to add?",
                                      reply_markup=botapi.ForceReply.create(selective=True), reply_to_message_id=msg.message_id).join().result
        self.update_loop.register_reply_watch(message=query, function=self.add_book__set_author)

    def add_book__set_author(self, msg):
        # TODO: Validate text?
        query = self.bot.send_message(chat_id=msg.chat.id, text="Title of book to add?",
                                      reply_markup=botapi.ForceReply.create(selective=True), reply_to_message_id=msg.message_id).join().result
        self.update_loop.register_reply_watch(message=query, function=partial(self.add_book__set_title, msg.text))

    def add_book__set_title(self, author_name, msg):
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
    # endregion

    # region register_ebook command
    @update_metadata
    def register_ebook(self, msg, arguments):
        open_books = DBSession.query(BookAssignment).filter(BookAssignment.chat_id == msg.chat.id).filter(BookAssignment.done == False).all()
        if len(open_books) == 0:
            self.bot.send_message(chat_id=msg.chat.id, text="There are no open books.",
                                  reply_to_message_id=msg.message_id)
        elif len(open_books) == 1:
            query = self.bot.send_message(chat_id=msg.chat.id, text="Gimmie that ebook.",
                                          reply_markup=botapi.ForceReply.create(selective=True), reply_to_message_id=msg.message_id).join().result
            self.update_loop.register_reply_watch(message=query, function=partial(self.register_ebook__file, open_books[0].id))
        else:
            # TODO: Support a "More" button.
            keyboard_rows = []
            for book_assign in open_books:
                keyboard_rows.append([botapi.InlineKeyboardButton(text=book_assign.book.friendly_name, callback_data=str(book_assign.book.id))])

            keyboard = botapi.InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

            query = self.bot.send_message(chat_id=msg.chat.id, text="Which book do you want to register an ebook for?",
                                          reply_markup=keyboard, reply_to_message_id=msg.message_id).join().result
            self.update_loop.register_inline_reply(message=query, srcmsg=msg, function=partial(self.register_ebook__select_book, msg.message_id), permission=Permission.SameUser)

    def register_ebook__select_book(self, original_msg_id, cbquery, data):
        assignment = DBSession.query(BookAssignment).filter(BookAssignment.id==int(data)).first()

        query = self.bot.send_message(chat_id=cbquery.message.chat.id, text="Gimmie that ebook.",
                                      reply_markup=botapi.ForceReply.create(selective=True), reply_to_message_id=original_msg_id).join().result
        self.update_loop.register_reply_watch(message=query, function=partial(self.register_ebook__file, data))

        assignment.current = True

        DBSession.add(assignment)
        DBSession.commit()

        self.bot.edit_message_text(chat_id=cbquery.message.chat.id, message_id=cbquery.message.message_id, text=f"Registering ebook for  {assignment.book.friendly_name}.")

    def register_ebook__file(self, assignment_id, msg):
        assignment = DBSession.query(BookAssignment).filter(BookAssignment.id == assignment_id).first()
        assignment.ebook_message_id = msg.message_id

        DBSession.add(assignment)
        DBSession.commit()

        self.bot.send_message(chat_id=msg.chat.id, text="Saved!", reply_to_message_id=msg.message_id)
    # endregion

    # region register_audiobook command
    @update_metadata
    def register_audiobook(self, msg, arguments):
        open_books = DBSession.query(BookAssignment).filter(BookAssignment.chat_id == msg.chat.id).filter(BookAssignment.done == False).all()
        if len(open_books) == 0:
            self.bot.send_message(chat_id=msg.chat.id, text="There are no open books.",
                                  reply_to_message_id=msg.message_id)
        elif len(open_books) == 1:
            query = self.bot.send_message(chat_id=msg.chat.id, text="Gimmie that audiobook.",
                                          reply_markup=botapi.ForceReply.create(selective=True), reply_to_message_id=msg.message_id).join().result
            self.update_loop.register_reply_watch(message=query, function=partial(self.register_audiobook__file, open_books[0].id))
        else:
            # TODO: Support a "More" button.
            keyboard_rows = []
            for book_assign in open_books:
                keyboard_rows.append([botapi.InlineKeyboardButton(text=book_assign.book.friendly_name, callback_data=str(book_assign.book.id))])

            keyboard = botapi.InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

            query = self.bot.send_message(chat_id=msg.chat.id, text="Which book do you want to register an audiobook for?",
                                          reply_markup=keyboard, reply_to_message_id=msg.message_id).join().result
            self.update_loop.register_inline_reply(message=query, srcmsg=msg, function=partial(self.register_audiobook__select_book, msg.message_id), permission=Permission.SameUser)

    def register_audiobook__select_book(self, original_msg_id, cbquery, data):
        assignment = DBSession.query(BookAssignment).filter(BookAssignment.id==int(data)).first()

        query = self.bot.send_message(chat_id=cbquery.message.chat.id, text="Gimmie that audiobook.",
                                      reply_markup=botapi.ForceReply.create(selective=True), reply_to_message_id=original_msg_id).join().result
        self.update_loop.register_reply_watch(message=query, function=partial(self.register_audiobook__file, data))

        assignment.current = True

        DBSession.add(assignment)
        DBSession.commit()

        self.bot.edit_message_text(chat_id=cbquery.message.chat.id, message_id=cbquery.message.message_id, text=f"Registering audiobook for  {assignment.book.friendly_name}.")

    def register_audiobook__file(self, assignment_id, msg):
        assignment = DBSession.query(BookAssignment).filter(BookAssignment.id == assignment_id).first()
        assignment.audiobook_message_id = msg.message_id

        DBSession.add(assignment)
        DBSession.commit()

        self.bot.send_message(chat_id=msg.chat.id, text="Saved!", reply_to_message_id=msg.message_id)
    # endregion

    # region set_due_date command
    @update_metadata
    def set_due_date(self, msg, arguments):
        print("Setting Due date! " + msg.text)
    # endregion

    # region start_book command
    @update_metadata
    def start_book(self, msg, arguments):
        open_books = DBSession.query(BookAssignment).filter(BookAssignment.chat_id == msg.chat.id).filter(BookAssignment.done == False).filter(BookAssignment.current == False).all()
        current_book = DBSession.query(BookAssignment).filter(BookAssignment.chat_id == msg.chat.id).filter(BookAssignment.current == True).all()

        if len(open_books) == 0:
            self.bot.send_message(chat_id=msg.chat.id, text="There are no open books to start.",
                                  reply_to_message_id=msg.message_id)
        else:
            reply = ""

            if len(current_book) > 0:
                reply += f"There are currently {len(current_book)} active books. \n"
            reply += "Which book do you want to set as active?"

            # TODO: Support a "More" button.
            keyboard_rows = []
            for book_assign in open_books:
                keyboard_rows.append([botapi.InlineKeyboardButton(text=book_assign.book.friendly_name, callback_data=str(book_assign.id))])

            keyboard = botapi.InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

            query = self.bot.send_message(chat_id=msg.chat.id, text=reply,
                                          reply_markup=keyboard, reply_to_message_id=msg.message_id).join().result
            self.update_loop.register_inline_reply(message=query, srcmsg=msg, function=self.start_book__select_book, permission=Permission.SameUser)

    def start_book__select_book(self, cbquery, data):
        assignment = DBSession.query(BookAssignment).filter(BookAssignment.id==int(data)).first()

        if not assignment:
            self.bot.send_message(chat_id=cbquery.message.chat.id, text="Error starting book, cannot find it in DB.")

        assignment.current = True

        DBSession.add(assignment)
        DBSession.commit()

        self.bot.edit_message_text(chat_id=cbquery.message.chat.id, message_id=cbquery.message.message_id, text=f"Starting book {assignment.book.friendly_name}.")
    # endregion

    # User Commands
    # region get_progress command
    def _send_progress(self, book_assignment_id, edit_message_id=None):
        assignment = DBSession.query(BookAssignment).filter(BookAssignment.id == book_assignment_id).one()

        progress_status = DBSession.query(ProgressUpdate).join(UserParticipation).join(BookAssignment)\
                                   .filter(BookAssignment.id == book_assignment_id)\
                                   .filter(UserParticipation.active == True)\
                                   .order_by(ProgressUpdate.update_date.desc()).all()

        # TODO: Super hacky because I cannot figure out the query right now to do what I want
        progress = {}
        for status in progress_status:
            if status.participation_id not in progress:
                progress[status.participation_id] = status

        update_text = f"Progress for {assignment.book.friendly_name}:\n"

        for status in progress.values():
            update_text += f"{status.participation.user.first_name} {status.participation.user.last_name}: {status.progress}\n"

        if edit_message_id is not None:
            self.bot.edit_message_text(chat_id=assignment.chat_id, message_id=edit_message_id, text=update_text)
        else:
            self.bot.send_message(chat_id=assignment.chat_id, text=update_text)

    @update_metadata
    def get_progress(self, msg, arguments):
        open_books = DBSession.query(BookAssignment) \
            .filter(BookAssignment.chat_id == msg.chat.id) \
            .filter(BookAssignment.current == True).all()

        if len(open_books) == 1:
            self._send_progress(open_books[0].id)
        else:
            reply = "Which book do you want progress for?"

            keyboard_rows = []
            for book_assign in open_books:
                keyboard_rows.append([botapi.InlineKeyboardButton(text=book_assign.book.friendly_name, callback_data=str(book_assign.id))])

            keyboard = botapi.InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

            query = self.bot.send_message(chat_id=msg.chat.id, text=reply,
                                          reply_markup=keyboard, reply_to_message_id=msg.message_id).join().result
            self.update_loop.register_inline_reply(message=query, srcmsg=msg, function=self.get_progress__select_book, permission=Permission.SameUser)

    def get_progress__select_book(self, cbquery, data):
        self._send_progress(int(data), edit_message_id=cbquery.message.message_id)

        # endregion
    # endregion

    # region set_progress command
    def _set_progress(self, participation_id, progress):
        new_progress = ProgressUpdate()
        new_progress.participation_id = participation_id
        new_progress.progress = progress

        DBSession.add(new_progress)
        DBSession.commit()


    @update_metadata
    def set_progress(self, msg, arguments):
        try:
            progress = int(arguments)
        except (ValueError, TypeError):
            progress = None

        user = User.create_or_get(msg.sender)
        joined_books = user.active_participation(chat_id=msg.chat.id)

        if len(joined_books) == 0:
            self.bot.send_message(chat_id=msg.chat.id, text="You are not currently reading any books!", reply_to_message_id=msg.message_id)

        elif len(joined_books) == 1:
            book = joined_books[0].book
            if progress is not None:
                try:
                    self._set_progress(joined_books[0].id, progress)
                    self.bot.send_message(chat_id=msg.chat.id, text=f"Progress set for {book.friendly_name}!", reply_to_message_id=msg.message_id)
                except sqlalchemy.exc.DataError:
                    self.bot.send_message(chat_id=msg.chat.id,
                                          text=f"Error setting progress set for {book.friendly_name}, number may be too large or invalid.",
                                          reply_to_message_id=msg.message_id)
            else:
                query = self.bot.send_message(chat_id=msg.chat.id, text="How far have you read?",
                                              reply_markup=botapi.ForceReply.create(selective=True), reply_to_message_id=msg.message_id).join().result
                self.update_loop.register_reply_watch(message=query, function=partial(self.set_progress__ask_progress, joined_books[0].id))

        else:
            reply = "Which book do you want to set progress on?"

            keyboard_rows = []
            for participation in joined_books:
                keyboard_rows.append([botapi.InlineKeyboardButton(text=participation.book.friendly_name, callback_data=str(participation.id))])

            keyboard = botapi.InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

            query = self.bot.send_message(chat_id=msg.chat.id, text=reply,
                                          reply_markup=keyboard, reply_to_message_id=msg.message_id).join().result
            self.update_loop.register_inline_reply(message=query, srcmsg=msg, function=partial(self.set_progress__select_book, msg.message_id, progress), permission=Permission.SameUser)

    def set_progress__select_book(self, original_msg_id, progress, cbquery, data):
        book = DBSession.query(UserParticipation).filter(UserParticipation.id == data).first().book

        if progress is not None:
            try:
                self._set_progress(int(data), progress)
                self.bot.edit_message_text(chat_id=cbquery.message.chat.id, message_id=cbquery.message.message_id, text=f"Progress set for {book.friendly_name}!")
            except sqlalchemy.exc.DataError:
                self.bot.send_message(chat_id=cbquery.message.chat.id,
                                      text=f"Error setting progress set for {book.friendly_name}, number may be too large or invalid.")
        else:
            query = self.bot.send_message(chat_id=cbquery.message.chat.id, text="How far have you read?",
                                          reply_markup=botapi.ForceReply.create(selective=True), reply_to_message_id=original_msg_id).join().result
            self.bot.edit_message_text(chat_id=cbquery.message.chat.id, message_id=cbquery.message.message_id, text=f"Selected {book.friendly_name}.")
            self.update_loop.register_reply_watch(message=query, function=partial(self.set_progress__ask_progress, data))

    def set_progress__ask_progress(self, participation_id, msg):
        try:
            progress = int(msg.text)
        except (ValueError, TypeError):
            progress = None

        if progress is not None:
            book = DBSession.query(UserParticipation).filter(UserParticipation.id == participation_id).first().book
            try:
                self._set_progress(participation_id, progress)
                self.bot.send_message(chat_id=msg.chat.id, text=f"Progress set for {book.friendly_name}!", reply_to_message_id=msg.message_id)
            except sqlalchemy.exc.DataError: # TODO this code is repeated 3 times, centralize, maybe pass chat info into _set_progress?
                DBSession.rollback()
                self.bot.send_message(chat_id=msg.chat.id,
                                      text=f"Error setting progress set for {book.friendly_name}, number may be too large or invalid.",
                                      reply_to_message_id=msg.message_id)
        else:
            # TODO: They are still sending more garbage.. should we try to strip out any text and just look for a number?
            self.bot.send_message(chat_id=msg.chat.id, text="Sorry, there was an error processing your answer", reply_to_message_id=msg.message_id)

    # endregion

    # region get_due_date command
    @update_metadata
    def get_due_date(self, msg, arguments):
        print("Getting due date! " + msg.text)
    # endregion

    # region get_book command
    @update_metadata
    def get_book(self, msg, arguments):
        print("Getting a book! " + msg.text)
    # endregion

    # region join_book command
    def _join_book(self, user_id, assignment):
        # TODO look to see if we quit the book before and just rejoin
        participation = UserParticipation()
        participation.book_assignment = assignment
        participation.user_id = user_id

        DBSession.add(participation)
        DBSession.commit()

    @update_metadata
    def join_book(self, msg, arguments):
        open_books = DBSession.query(BookAssignment)\
            .filter(BookAssignment.chat_id == msg.chat.id)\
            .filter(BookAssignment.current == True).all()
        user = User.create_or_get(msg.sender)
        current_books = [participation.book_assignment_id for participation in user.active_participation(msg.chat.id)]
        open_books = [book for book in open_books if book.id not in current_books]

        if len(open_books) == 0:
            self.bot.send_message(chat_id=msg.chat.id, text="No books are currently being read that you're not in!", reply_to_message_id=msg.message_id)

        elif len(open_books) == 1:
            self._join_book(assignment=open_books[0], user_id=msg.sender.id)
            self.bot.send_message(chat_id=msg.chat.id,
                                  text=f"@{msg.sender.username} joined book {open_books[0].book.friendly_name}!",
                                  reply_to_message_id=msg.message_id)
        else:
            reply = "Which book do you want to join?"

            keyboard_rows = []
            for book_assign in open_books:
                keyboard_rows.append([botapi.InlineKeyboardButton(text=book_assign.book.friendly_name, callback_data=str(book_assign.book.id))])

            keyboard = botapi.InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

            query = self.bot.send_message(chat_id=msg.chat.id, text=reply,
                                          reply_markup=keyboard, reply_to_message_id=msg.message_id).join().result
            self.update_loop.register_inline_reply(message=query, srcmsg=msg, function=self.join_book__select_book, permission=Permission.SameUser)

    def join_book__select_book(self, cbquery, data):
        assignment = DBSession.query(BookAssignment).filter(BookAssignment.book_id==int(data)).first()

        if not assignment:
            self.bot.answer_callback_query(callback_query_id=cbquery.id, text="Error joining book, cannot find it in DB.")

        self._join_book(assignment=assignment, user_id=cbquery.sender.id)

        self.bot.edit_message_text(chat_id=cbquery.message.chat.id, message_id=cbquery.message.message_id,
                                   text=f"@{cbquery.sender.username} joined book {assignment.book.friendly_name}!")
    # endregion

    # region quit_book command
    @update_metadata
    def quit_book(self, msg, arguments):
        user = User.create_or_get(msg.sender)
        if msg.chat.type == "private":
            books = user.active_participation()
        else:
            books = user.active_participation(msg.chat.id)

        if len(books) == 0:
            self.bot.send_message(chat_id=msg.chat.id, text="You are not reading any books.", reply_to_message_id=msg.message_id)
        else:
            reply = "Which book do you want to quit?"

            keyboard_rows = []
            for participation in books:
                keyboard_rows.append([botapi.InlineKeyboardButton(text=participation.book.friendly_name, callback_data=str(participation.id))])
            keyboard_rows.append([botapi.InlineKeyboardButton(text="Cancel", callback_data="CANCEL")])
            keyboard = botapi.InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

            query = self.bot.send_message(chat_id=msg.chat.id, text=reply,
                                          reply_markup=keyboard, reply_to_message_id=msg.message_id).join().result
            self.update_loop.register_inline_reply(message=query, srcmsg=msg, function=self.quit_book__select_book, permission=Permission.SameUser)

    def quit_book__select_book(self, cbquery, data):
        if data == "CANCEL":
            self.bot.edit_message_text(chat_id=cbquery.message.chat.id, message_id=cbquery.message.message_id,
                                       text=f"Quit canceled.")
        else:
            participation = DBSession.query(UserParticipation).filter(UserParticipation.id==int(data)).first()

            if not participation:
                self.bot.answer_callback_query(callback_query_id=cbquery.id, text="Error quiting book, cannot find it in DB.")

            participation.active = False
            DBSession.add(participation)
            DBSession.commit()

            self.bot.edit_message_text(chat_id=cbquery.message.chat.id, message_id=cbquery.message.message_id,
                                       text=f"@{cbquery.sender.username} has quit book {participation.book.friendly_name}!")
    # endregion

    def run(self):
        self.update_loop.run()  # Run update loop and register as handler

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
