# Standard Library
import configparser
import logging
import os.path
from functools import wraps, partial

import pytz
import sqlalchemy.exc
from dateutil.parser import parse as dtparse
from sqlalchemy import engine_from_config
from twx import botapi
from twx.botapi.helpers.update_loop import UpdateLoop, Permission

from TGBookClubBot.goodreads import GoodReadsClient
from TGBookClubBot.models import *


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

        try:
            self.goodreads = GoodReadsClient(self.config['BookClubBot']['goodreads.key'], self.config['BookClubBot']['goodreads.secret'])
        except KeyError:
            self.goodreads = None

        self.update_loop = UpdateLoop(self.bot, self)

        self.update_loop.register_inline_query_handler(self.inline_query)

        # region command registration
        # Admin Commands
        self.update_loop.register_command(name='add_book', permission=Permission.Admin, function=self.add_book)
        self.update_loop.register_command(name='start_book', permission=Permission.Admin, function=self.start_book)
        self.update_loop.register_command(name='register_ebook', permission=Permission.Admin, function=self.register_ebook)
        self.update_loop.register_command(name='register_audiobook', permission=Permission.Admin, function=self.register_audiobook)
        self.update_loop.register_command(name='set_deadline', permission=Permission.Admin, function=self.set_deadline)

        # User Commands
        self.update_loop.register_command(name='get_book', function=self.get_book)
        self.update_loop.register_command(name='join_book', function=self.join_book)
        self.update_loop.register_command(name='quit_book', function=self.quit_book)
        self.update_loop.register_command(name='set_progress', function=self.set_progress)
        self.update_loop.register_command(name='get_progress', function=self.get_progress)
        self.update_loop.register_command(name='get_deadline', function=self.get_deadline)
        # endregion

    # Admin Commands
    # region add_book command
    @update_metadata
    def add_book(self, msg, arguments):
        if arguments:
            self.add_book__set_goodreads(msg, arguments)
        else:
            query = self.bot.send_message(chat_id=msg.chat.id, text="Title of book to add?",
                                          reply_markup=botapi.ForceReply.create(selective=True), reply_to_message_id=msg.message_id).join().result
            self.update_loop.register_reply_watch(message=query, function=partial(self.add_book__set_title, query.message_id))

    def add_book__set_title(self, original_msg_id, msg):
        if self.goodreads:
            self.add_book__set_goodreads(msg, msg.text)
        else:
            # No goodreads integration, just take it as text
            query = self.bot.send_message(chat_id=msg.chat.id, text="Author of book to add?",
                                          reply_markup=botapi.ForceReply.create(selective=True), reply_to_message_id=msg.message_id).join().result
            self.update_loop.register_reply_watch(message=query, function=partial(self.add_book__set_author, msg.text))

    def add_book__set_goodreads(self, original_msg, search):
        # Set typing action for goodreads search
        self.bot.send_chat_action(chat_id=original_msg.chat.id, action="typing")
        possible_books = self.goodreads.search_books(search)

        # TODO: Support a "More" button.
        keyboard_rows = []
        for book in possible_books[:5]:
            title = book['best_book']['title']
            author = book['best_book']['author']['name']
            try:
                year = book['original_publication_year']['#text']
            except KeyError:
                year = "Unk"
            keyboard_rows.append([botapi.InlineKeyboardButton(text=f"{title[:30]+(title[30:] and '..')} - {author} ({year})",
                                                              callback_data=f"GID:{book['best_book']['id']['#text']}")])

        keyboard_rows.append([botapi.InlineKeyboardButton(text=f"As Entered: {search}", callback_data=original_msg.text),
                              botapi.InlineKeyboardButton(text=f"Cancel", callback_data="CANCEL")])

        keyboard = botapi.InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

        query = self.bot.send_message(chat_id=original_msg.chat.id, text="Please select book to add. (search results via GoodReads)", reply_markup=keyboard).join().result
        self.update_loop.register_inline_reply(message=query, srcmsg=original_msg,  function=partial(self.add_book__select_goodreads, original_msg), permission=Permission.SameUser)


    def add_book__select_goodreads(self, msg, cbquery, data):
        if data == "CANCEL":
            self.bot.edit_message_text(chat_id=cbquery.message.chat.id, message_id=cbquery.message.message_id,
                                       text=f"Add canceled.")
        elif data.startswith("GID:"):
            goodreads_id = int(data[4:])

            book = self.goodreads.get_book(goodreads_id)
            try:
                author = book['authors']['author'][0]  # Pull first author, most always right.
            except KeyError:
                author = book['authors']['author']  # Only one author

            author_db = DBSession.query(Author).filter(Author.goodreads_id == author['id']).first()
            if not author_db:
                author_db = Author()
                author_db.name = author['name']
                author_db.goodreads_id = author['id']
                DBSession.add(author_db)

            book_db = DBSession.query(Book).filter(Book.goodreads_id == book['id']).first()
            if not book_db:
                book_db = Book()
                book_db.author = author_db
                book_db.title = book['title']
                book_db.goodreads_id = book['id']
                book_db.isbn = book['isbn']
                book_db.thumb_url = book['small_image_url']
                DBSession.add(book_db)

            assignment = DBSession.query(BookAssignment).filter(BookAssignment.book_id == book_db.id).filter(BookAssignment.chat_id == msg.chat.id).first()
            if not assignment:
                assignment = BookAssignment()
                assignment.book = book_db
                assignment.chat_id = msg.chat.id
                DBSession.add(assignment)
                DBSession.commit()

            text = f"Added `{book_db.friendly_name}`\nfound via [Goodreads]({book['url']})"
            self.bot.edit_message_text(chat_id=cbquery.message.chat.id, message_id=cbquery.message.message_id,
                                       text=text, parse_mode="Markdown")

        else:
            self.add_book__set_author(data, msg)

    def add_book__set_author(self, book_title, msg):
        author_name = msg.text

        author = DBSession.query(Author).filter(Author.name == author_name).first()
        if not author:
            author = Author()
            author.name = author_name
            DBSession.add(author)

        book = DBSession.query(Book).filter(Book.title == book_title).first()
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
        assignment = DBSession.query(BookAssignment).filter(BookAssignment.id == int(data)).first()

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
            self.update_loop.register_inline_reply(message=query, srcmsg=msg, function=partial(self.register_audiobook__select_book, msg.message_id),
                                                   permission=Permission.SameUser)

    def register_audiobook__select_book(self, original_msg_id, cbquery, data):
        assignment = DBSession.query(BookAssignment).filter(BookAssignment.id == int(data)).first()

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

    # region set_deadline command
    def _set_deadline(self, book_assignment_id, deadline, end_progress):
        last_schedule = DBSession.query(BookSchedule).filter(BookSchedule.book_assignment_id == book_assignment_id).order_by(BookSchedule.due_date.desc()).first()

        if last_schedule:
            start = last_schedule.end
        else:
            start = 0

        new_schedule = BookSchedule()
        new_schedule.start = start
        new_schedule.end = end_progress
        new_schedule.due_date = deadline
        new_schedule.book_assignment_id = book_assignment_id

        DBSession.add(new_schedule)
        DBSession.commit()

    @update_metadata
    def set_deadline(self, msg, arguments):
        current_books = DBSession.query(BookAssignment).filter(BookAssignment.chat_id == msg.chat.id).filter(BookAssignment.current == True).all()

        if len(current_books) == 0:
            self.bot.send_message(chat_id=msg.chat.id, text="There are no current books to set the due date for.",
                                  reply_to_message_id=msg.message_id)
        elif len(current_books) == 1:
            self.set_deadline__select_book(original_msg_id=msg.message_id, cbquery=None, data=current_books[0].id)
        else:
            reply = "Which book do you want to set the due date for?"

            keyboard_rows = []
            for book_assign in current_books:
                keyboard_rows.append([botapi.InlineKeyboardButton(text=book_assign.book.friendly_name, callback_data=str(book_assign.id))])

            keyboard = botapi.InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

            query = self.bot.send_message(chat_id=msg.chat.id, text=reply,
                                          reply_markup=keyboard, reply_to_message_id=msg.message_id).join().result
            self.update_loop.register_inline_reply(message=query, srcmsg=msg, function=partial(self.set_deadline__select_book, msg), permission=Permission.SameUser)

    def set_deadline__select_book(self, original_msg_id, cbquery, data):
        book = DBSession.query(BookAssignment).filter(BookAssignment.id == data).first()
        query = self.bot.send_message(chat_id=book.chat_id, text="When is the next reading deadline?",
                                      reply_markup=botapi.ForceReply.create(selective=True), reply_to_message_id=original_msg_id).join().result
        self.update_loop.register_reply_watch(message=query, function=partial(self.set_deadline__select_deadline, data))

    def set_deadline__select_deadline(self, book_assignment_id, msg):
        try:
            deadline = pytz.timezone("US/Pacific").localize(dtparse(msg.text))  # TODO: Proper timezone support #westcoastbestcoast
        except ValueError:
            deadline = None

        if deadline is not None:
            query = self.bot.send_message(chat_id=msg.chat.id, text="What chapter is the next reading deadline?",  # TODO: Support more than chapters in messages
                                          reply_markup=botapi.ForceReply.create(selective=True), reply_to_message_id=msg.message_id).join().result
            self.update_loop.register_reply_watch(message=query, function=partial(self.set_deadline__select_progress, deadline, book_assignment_id, query.message_id))
        else:
            # TODO: They are still sending more garbage..
            self.bot.send_message(chat_id=msg.chat.id, text="Sorry, there was an error processing your answer", reply_to_message_id=msg.message_id)

    def set_deadline__select_progress(self, deadline, book_assignment_id, original_msg_id, msg):
        book = DBSession.query(BookAssignment).filter(BookAssignment.id == book_assignment_id).first().book
        try:
            progress = int(msg.text)  # TODO: Another place to improve progress parsing.
        except ValueError:
            progress = None

        if progress is not None:
            self.bot.send_message(chat_id=msg.chat.id,
                                  text=f"Due date set for {book.friendly_name}: {deadline.strftime('%Y-%m-%d %I:%M %p %Z')}, to read to {progress}.")
            self._set_deadline(book_assignment_id=book_assignment_id, end_progress=progress, deadline=deadline)
        else:
            # TODO: They are still sending more garbage..
            self.bot.send_message(chat_id=msg.chat.id, text="Sorry, there was an error processing your answer", reply_to_message_id=msg.message_id)

    # endregion

    # region start_book command
    @update_metadata
    def start_book(self, msg, arguments):
        open_books = DBSession.query(BookAssignment).filter(BookAssignment.chat_id == msg.chat.id).filter(BookAssignment.done == False).filter(
            BookAssignment.current == False).all()
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
        assignment = DBSession.query(BookAssignment).filter(BookAssignment.id == int(data)).first()

        if not assignment:
            self.bot.send_message(chat_id=cbquery.message.chat.id, text="Error starting book, cannot find it in DB.")

        assignment.current = True

        DBSession.add(assignment)
        DBSession.commit()

        self.bot.edit_message_text(chat_id=cbquery.message.chat.id, message_id=cbquery.message.message_id, text=f"Starting book {assignment.book.friendly_name}.")

    # endregion

    # User Commands
    # region get_progress command
    def _send_progress(self, book_assignment_id, verbose, edit_message_id=None):
        assignment = DBSession.query(BookAssignment).filter(BookAssignment.id == book_assignment_id).one()

        progress_status = DBSession.query(ProgressUpdate).join(UserParticipation).join(BookAssignment) \
            .filter(BookAssignment.id == book_assignment_id) \
            .filter(UserParticipation.active == True) \
            .order_by(ProgressUpdate.update_date.desc()).all()

        deadline = DBSession.query(BookSchedule).filter(BookSchedule.book_assignment_id == book_assignment_id).order_by(BookSchedule.due_date.desc()).first()

        # TODO: Super hacky because I cannot figure out the query right now to do what I want
        progress = {}
        for status in progress_status:
            if status.participation_id not in progress:
                progress[status.participation_id] = status

        update_text = f"Progress for {assignment.book.title} (read to {deadline.end} by {deadline.due_date.strftime('%m-%d')})\n"

        for status in sorted(progress.values(), reverse=True, key=lambda x: x.progress):
            if verbose:
                update_text += f"{status.progress}: {status.participation.user.first_name} {status.participation.user.last_name}" \
                               f" @ {status.update_date.strftime('%Y-%m-%d %I:%M %p %Z')}\n"
            else:
                update_text += f"{status.progress}: {status.participation.user.first_name} {status.participation.user.last_name}\n"

        if edit_message_id is not None:
            self.bot.edit_message_text(chat_id=assignment.chat_id, message_id=edit_message_id, text=update_text)
        else:
            self.bot.send_message(chat_id=assignment.chat_id, text=update_text)

    @update_metadata
    def get_progress(self, msg, arguments):
        open_books = DBSession.query(BookAssignment) \
            .filter(BookAssignment.chat_id == msg.chat.id) \
            .filter(BookAssignment.current == True).all()

        verbose = arguments.strip() == "-v"

        if len(open_books) == 1:
            self._send_progress(open_books[0].id, verbose=verbose)
        else:
            reply = "Which book do you want progress for?"

            keyboard_rows = []
            for book_assign in open_books:
                keyboard_rows.append([botapi.InlineKeyboardButton(text=book_assign.book.friendly_name, callback_data=str(book_assign.id))])

            keyboard = botapi.InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

            query = self.bot.send_message(chat_id=msg.chat.id, text=reply,
                                          reply_markup=keyboard, reply_to_message_id=msg.message_id).join().result
            self.update_loop.register_inline_reply(message=query, srcmsg=msg, function=partial(self.get_progress__select_book, verbose), permission=Permission.SameUser)

    def get_progress__select_book(self, verbose, cbquery, data):
        self._send_progress(int(data), verbose=verbose, edit_message_id=cbquery.message.message_id)

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

                    user = f"@{msg.sender.username}" or f"{msg.sender.first_name} {msg.sender.last_name}"
                    self._set_progress(joined_books[0].id, progress)
                    self.bot.send_message(chat_id=msg.chat.id, text=f"{user} progress set for {book.title} to {progress}!")

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
                                          reply_markup=keyboard).join().result
            self.update_loop.register_inline_reply(message=query, srcmsg=msg, function=partial(self.set_progress__select_book, msg.message_id, progress),
                                                   permission=Permission.SameUser)

    def set_progress__select_book(self, original_msg_id, progress, cbquery, data):
        book = DBSession.query(UserParticipation).filter(UserParticipation.id == data).first().book

        if progress is not None:
            try:
                user = f"@{cbquery.sender.username}" or f"{cbquery.sender.first_name} {cbquery.sender.last_name}"
                self._set_progress(int(data), progress)
                self.bot.edit_message_text(chat_id=cbquery.message.chat.id, message_id=cbquery.message.message_id, text=f"{user} progress set for {book.title} to {progress}!")
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
                user = f"@{msg.sender.username}" or f"{msg.sender.first_name} {msg.sender.last_name}"
                self._set_progress(participation_id, progress)
                self.bot.send_message(chat_id=msg.chat.id,
                                      reply_markup=botapi.ReplyKeyboardRemove.create(),
                                      text=f"{user} progress set for {book.title} to {progress}!")
            except sqlalchemy.exc.DataError:  # TODO this code is repeated 3 times, centralize, maybe pass chat info into _set_progress?
                DBSession.rollback()
                self.bot.send_message(chat_id=msg.chat.id,
                                      text=f"Error setting progress set for {book.title}, number may be too large or invalid.",
                                      reply_to_message_id=msg.message_id)
        else:
            # TODO: They are still sending more garbage.. should we try to strip out any text and just look for a number?
            self.bot.send_message(chat_id=msg.chat.id, text="Sorry, there was an error processing your answer", reply_to_message_id=msg.message_id)

    # endregion

    # region get_deadline command
    def _send_deadline(self, book_assignment_id, edit_message_id=None):
        assignment = DBSession.query(BookAssignment).filter(BookAssignment.id == book_assignment_id).one()
        last_schedule = DBSession.query(BookSchedule).filter(BookSchedule.book_assignment_id == book_assignment_id).order_by(BookSchedule.due_date.desc()).first()

        deadline_text = f"Deadline for {assignment.book.friendly_name} is {last_schedule.end} by {last_schedule.due_date.strftime('%Y-%m-%d %I:%M %p %Z')}"

        if edit_message_id is not None:
            self.bot.edit_message_text(chat_id=assignment.chat_id, message_id=edit_message_id, text=deadline_text)
        else:
            self.bot.send_message(chat_id=assignment.chat_id, text=deadline_text)

    @update_metadata
    def get_deadline(self, msg, arguments):
        current_books = DBSession.query(BookAssignment).filter(BookAssignment.chat_id == msg.chat.id).filter(BookAssignment.current == True).all()

        if len(current_books) == 1:
            self._send_deadline(current_books[0].id)
        else:
            reply = "Which book do you want deadline for?"

            keyboard_rows = []
            for book_assign in current_books:
                keyboard_rows.append([botapi.InlineKeyboardButton(text=book_assign.book.friendly_name, callback_data=str(book_assign.id))])

            keyboard = botapi.InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

            query = self.bot.send_message(chat_id=msg.chat.id, text=reply,
                                          reply_markup=keyboard, reply_to_message_id=msg.message_id).join().result
            self.update_loop.register_inline_reply(message=query, srcmsg=msg, function=self.get_deadline__select_book, permission=Permission.SameUser)

    def get_deadline__select_book(self, cbquery, data):
        self._send_deadline(int(data), edit_message_id=cbquery.message.message_id)

    # endregion

    # region get_book command
    def _send_book_info(self, info_type, book_assignment_id, edit_message_id=None):
        assignment = DBSession.query(BookAssignment).filter(BookAssignment.id == book_assignment_id).one()

        if info_type == "Audiobook":
            self.bot.edit_message_text(chat_id=assignment.chat_id, message_id=edit_message_id, text=f"Forwarding audiobook for {assignment.book.friendly_name}.")
            query = self.bot.forward_message(chat_id=assignment.chat_id, from_chat_id=assignment.chat_id, message_id=assignment.audiobook_message_id).wait()
            if isinstance(query, botapi.Error):
                self.bot.edit_message_text(chat_id=assignment.chat_id, message_id=edit_message_id, text=f"Original message has been deleted, cannot send audiobook.")
                assignment.audiobook_message_id = None
                DBSession.add(assignment)
                DBSession.commit()
        elif info_type == "eBook":
            self.bot.edit_message_text(chat_id=assignment.chat_id, message_id=edit_message_id, text=f"eBook {assignment.book.friendly_name}.")
            query = self.bot.forward_message(chat_id=assignment.chat_id, from_chat_id=assignment.chat_id, message_id=assignment.ebook_message_id)
            if isinstance(query, botapi.Error):
                self.bot.edit_message_text(chat_id=assignment.chat_id, message_id=edit_message_id, text=f"Original message has been deleted, cannot send audiobook.")
                assignment.ebook_message_id = None
                DBSession.add(assignment)
                DBSession.commit()
        elif info_type == "Description":
            book_meta = self.goodreads.get_book(goodreads_id=assignment.book.goodreads_id)
            desc = book_meta['description'].replace('<br />', '\n')
            self.bot.edit_message_text(chat_id=assignment.chat_id, message_id=edit_message_id, parse_mode="markdown", disable_web_page_preview=True,
                                       text=f"*{assignment.book.friendly_name}*\n\n```\n{desc}\n```\nvia [Goodreads]({book_meta['url']})")
        else:
            raise Exception("Unknown Book Info String")  # TODO Handle errors better

    @update_metadata
    def get_book(self, msg, arguments):
        open_books = DBSession.query(BookAssignment) \
            .filter(BookAssignment.chat_id == msg.chat.id) \
            .filter(BookAssignment.current == True).all()

        if len(open_books) == 1:
            self.get_book__info_type(msg, None, open_books[0].id)
        else:
            reply = "Which book do you want info for?"

            keyboard_rows = []
            for book_assign in open_books:
                keyboard_rows.append([botapi.InlineKeyboardButton(text=book_assign.book.friendly_name, callback_data=str(book_assign.id))])

            keyboard = botapi.InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

            query = self.bot.send_message(chat_id=msg.chat.id, text=reply,
                                          reply_markup=keyboard, reply_to_message_id=msg.message_id).join().result
            self.update_loop.register_inline_reply(message=query, srcmsg=msg, function=partial(self.get_book__info_type, msg), permission=Permission.SameUser)

    def get_book__info_type(self, msg, cbquery, data):
        book = DBSession.query(BookAssignment).filter(BookAssignment.id == data).first()
        reply = f"What info would you like for {book.book.friendly_name}?"

        buttons = []
        if book.book.goodreads_id:
            buttons.append("Description")
        if book.ebook_message_id:
            buttons.append("eBook")
        if book.audiobook_message_id:
            buttons.append("Audiobook")

        if len(buttons) == 0:
            reply = f"Current book is {book.book.friendly_name}"
            keyboard = None
        else:
            keyboard_rows = []
            for button in buttons:
                keyboard_rows.append([botapi.InlineKeyboardButton(text=button, callback_data=str(button))])

            keyboard = botapi.InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

        if cbquery is not None:
            query = self.bot.edit_message_text(chat_id=msg.chat.id, text=reply,
                                               reply_markup=keyboard, message_id=cbquery.message.message_id).join().result
        else:
            query = self.bot.send_message(chat_id=msg.chat.id, text=reply,
                                          reply_markup=keyboard).join().result

        self.update_loop.register_inline_reply(message=query, srcmsg=msg, function=partial(self.get_book__select_info_type, data), permission=Permission.SameUser)

    def get_book__select_info_type(self, book_assignment_id, cbquery, data):
        self._send_book_info(data, book_assignment_id, edit_message_id=cbquery.message.message_id)

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
        open_books = DBSession.query(BookAssignment) \
            .filter(BookAssignment.chat_id == msg.chat.id) \
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
        assignment = DBSession.query(BookAssignment).filter(BookAssignment.book_id == int(data)).first()

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
            participation = DBSession.query(UserParticipation).filter(UserParticipation.id == int(data)).first()

            if not participation:
                self.bot.answer_callback_query(callback_query_id=cbquery.id, text="Error quiting book, cannot find it in DB.")

            participation.active = False
            DBSession.add(participation)
            DBSession.commit()

            self.bot.edit_message_text(chat_id=cbquery.message.chat.id, message_id=cbquery.message.message_id,
                                       text=f"@{cbquery.sender.username} has quit book {participation.book.friendly_name}!")

    # endregion

    def inline_query(self, query):
        pass # Commenting out as I do not believe a viable UI is possible with Telegram's API limitations.
        # if query.query.startswith("progress "):
        #     progress = int(re.search(r'\d+', query.query).group())
        #     user = User.create_or_get(query.sender)
        #     books = user.active_participation()
        #
        #     results = []
        #
        #     if len(books) == 0:
        #         pass  # TODO: Some kind of error?
        #     else:
        #         for book in books:
        #             result_text = f"Set progress for {book.book.friendly_name} to {progress} for {book.book_assignment.chat.username or book.book_assignment.chat.title}"
        #             desc_text = f"Group: {book.book_assignment.chat.username or book.book_assignment.chat.title}, Set Progress: {progress}"
        #             keyboard_rows = []
        #             keyboard_rows.append([botapi.InlineKeyboardButton(text=f"test",
        #                                                               callback_data=f"fdgdfg")])
        #
        #             kbd = botapi.InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
        #             results.append(botapi.InlineQueryResultArticle(id=f"{book.id},{progress}",
        #                                                            title=book.book.friendly_name,
        #                                                            description=desc_text,
        #                                                            input_message_content=botapi.InputTextMessageContent(message_text=result_text),
        #                                                            reply_markup=kbd,
        #                                                            thumb_url=book.book.thumb_url
        #                                                            )
        #                            )
        #
        #     self.bot.answer_inline_query(inline_query_id=query.id,
        #                                  results=results,
        #                                  cache_time=0,
        #                                  is_personal=True)

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
