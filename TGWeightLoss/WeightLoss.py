# Standard Library
import configparser
import logging
import os.path
from functools import wraps, partial

import pytz
import sqlalchemy.exc
from dateutil.parser import parse as dtparse
from datetime import date, timedelta
from sqlalchemy import engine_from_config
from twx import botapi
from twx.botapi.helpers.update_loop import UpdateLoop, Permission

import myfitnesspal
import gspread
from oauth2client.service_account import ServiceAccountCredentials

from TGWeightLoss.models import *


def update_metadata(f):
    @wraps(f)
    def wrapper(*args, **kwds):
        if args[1].chat.type in ['supergroup', 'group']:
            Chat.create_or_get(args[1].chat)
        User.create_or_get(args[1].sender)
        return f(*args, **kwds)
    return wrapper


class WeightLossBot:
    def __init__(self, config):
        self.config = config
        self.logger = logging.Logger("WeightLossBot")

        self.bot = botapi.TelegramBot(token=self.config['WeightLossBot']['bot_token'])
        self.bot.update_bot_info().wait()

        try:
            self.mfp = myfitnesspal.Client(self.config['WeightLossBot']['myfitnesspal.user'], self.config['WeightLossBot']['myfitnesspal.pass'])
        except KeyError:
            self.mfp = None

        self.refresh_gsheet_auth()

        self.update_loop = UpdateLoop(self.bot, self)

        # region command registration
        # Admin Commands
        self.update_loop.register_command(name='add_contest', permission=Permission.Admin, function=self.add_contest)

        # User Commands
        # self.update_loop.register_command(name='join_book', function=self.join_contest)
        # self.update_loop.register_command(name='set_progress', function=self.set_progress)
        # self.update_loop.register_command(name='get_progress', function=self.get_progress)
        # self.update_loop.register_command(name='get_deadline', function=self.get_deadline)
        self.update_loop.register_command(name='mfp_summary', function=self.get_mfp_summary)
        # endregion

    def refresh_gsheet_auth(self):
        scope = ['https://spreadsheets.google.com/feeds']
        credentials = ServiceAccountCredentials.from_json_keyfile_name('gsheets_oauth.json', scope)
        gc = gspread.authorize(credentials)
        self.worksheet = gc.open_by_key(self.config['WeightLossBot']['gsheets.key'])

    # Admin Commands
    # region add_contest command
    @update_metadata
    def add_contest(self, msg, arguments):
        if arguments:
            self.add_contest__set_title(msg, arguments)
        else:
            query = self.bot.send_message(chat_id=msg.chat.id, text="Title of contest to add?",
                                          reply_markup=botapi.ForceReply.create(selective=True), reply_to_message_id=msg.message_id).join().result
            self.update_loop.register_reply_watch(message=query, function=partial(self.add_contest__set_title, query.message_id))

    def add_contest__set_title(self, original_msg_id, msg):
        query = self.bot.send_message(chat_id=msg.chat.id, text="Start Date of Contest?",
                                      reply_markup=botapi.ForceReply.create(selective=True), reply_to_message_id=msg.message_id).join().result
        self.update_loop.register_reply_watch(message=query, function=partial(self.add_contest__set_date_start, msg.text))

    def add_contest__set_date_start(self, contest_title, msg):
        try:
            date_start = pytz.timezone("US/Pacific").localize(dtparse(msg.text))  # TODO: Proper timezone support #westcoastbestcoast
        except ValueError:
            date_start = None

        if date_start is not None:
            query = self.bot.send_message(chat_id=msg.chat.id,
                                          text="What chapter is the next reading deadline through?",
                                          reply_markup=botapi.ForceReply.create(selective=True),
                                          reply_to_message_id=msg.message_id).join().result
            self.update_loop.register_reply_watch(message=query, function=partial(self.add_contest__set_date_end, contest_title, date_start, query.message_id))
        else:
            # TODO: They are still sending more garbage.. Keep asking
            query = self.bot.send_message(chat_id=msg.chat.id, text="Your date could not be processed, try again!",
                                          reply_markup=botapi.ForceReply.create(selective=True),
                                          reply_to_message_id=msg.message_id).join().result
            self.update_loop.register_reply_watch(message=query,
                                                  function=partial(self.add_contest__set_date_start, contest_title))

    def add_contest__set_date_end(self, contest_title, date_start, msg):
        try:
            date_end = pytz.timezone("US/Pacific").localize(dtparse(msg.text))  # TODO: Proper timezone support #westcoastbestcoast
        except ValueError:
            date_end = None

        if date_end is not None:
            contest = Contest()
            contest.title = contest_title
            contest.date_start = date_start
            contest.date_end = date_end
            DBSession.add(contest)
        else:
            # TODO: They are still sending more garbage.. Keep asking
            query = self.bot.send_message(chat_id=msg.chat.id, text="Your date could not be processed, try again!",
                                          reply_markup=botapi.ForceReply.create(selective=True),
                                          reply_to_message_id=msg.message_id).join().result
            self.update_loop.register_reply_watch(message=query,
                                                  function=partial(self.add_contest__set_date_end, contest_title, date_start))

    # endregion


    # User Commands
    # region get_progress command
    """
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

        update_text = f"Progress for {assignment.book.title} (read through {deadline.end} by {deadline.due_date.strftime('%m-%d')})\n"

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
                    self.bot.send_message(chat_id=msg.chat.id, text=f"{user} progress set for {book.title} through {progress}!")

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
                self.bot.edit_message_text(chat_id=cbquery.message.chat.id, message_id=cbquery.message.message_id, text=f"{user} progress set for {book.title} through {progress}!")
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
                                      text=f"{user} progress set for {book.title} through {progress}!")
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
"""

    def get_mfp_summary(self, msg, arguments):
        print("summary")
        try:
            summary_date = pytz.timezone("US/Pacific").localize(dtparse(arguments))  # TODO: Proper timezone support #westcoastbestcoast
        except ValueError:
            summary_date = date.today() - timedelta(1)

        message = f"MFP Summary for {summary_date.strftime('%Y-%m-%d')}:\n\n"

        try:
            users = self._get_participants()
        except:
            self.refresh_gsheet_auth()
            users = self._get_participants()

        message += "```\n"

        for user in users:
            if user['mfp'].strip() == "":
                message += f"{user['name']}: NO MFP SET\n"
            else:
                try:
                    mfp_username = user['mfp'].split('/')[-1]

                    day = self.mfp.get_date(summary_date, username=mfp_username)
                    totals = day.totals
                    message += f"{user['name']} tracked {len(list(day.entries))} entries across {len([x for x in day.meals if len(list(x.entries))>0])} meals:"\
                               f"\n    Cals: {totals['calories']}/{user['goal_calories']} {'❌' if totals['calories'] > int(user['goal_calories']) else '✅'}" \
                               f"\n    NetCarbs: {totals['carbohydrates']-totals['fiber']}/{user['goal_carbs']} {'❌' if totals['carbohydrates']-totals['fiber'] > int(user['goal_carbs']) else '✅'}" \
                               f"\n    Fat: {totals['fat']}/{user['goal_fat']} {'❌' if totals['fat'] > int(user['goal_fat']) else '✅'}" \
                               f"\n    Protein: {totals['protein']}/{user['goal_protein']} {'❌' if totals['protein'] > int(user['goal_protein']) else '✅'}\n"
                except:
                    message += f"{user['name']}: Nothing Logged, FOR SHAME\n"

        message += "```\n"
        print(message)
        self.bot.send_message(chat_id=msg.chat.id, text=message, parse_mode="Markdown")

    def _get_participants(self):
        """
        TODO: This is completely hardcoded to the DM contest... figure out how to make it more flexible
        :return:
        """
        users = []
        for row in range(2, 8):
            users.append({
                'name': self.worksheet.worksheet("Goals").cell(row, '1').value,
                'telegram': self.worksheet.worksheet("Goals").cell(row, '12').value,
                'mfp': self.worksheet.worksheet("Goals").cell(row, '13').value,
                'goal_calories': self.worksheet.worksheet("Goals").cell(row, '8').value,
                'goal_carbs': self.worksheet.worksheet("Goals").cell(row, '9').value,
                'goal_fat': self.worksheet.worksheet("Goals").cell(row, '10').value,
                'goal_protein': self.worksheet.worksheet("Goals").cell(row, '11').value,
            })

        return users

    def run(self):
        self.update_loop.run()  # Run update loop and register as handler


if __name__ == '__main__':
    # Run as script
    if not os.path.exists("config.ini"):
        exit("Config file not found!")
    configfile = configparser.ConfigParser()
    configfile.read('config.ini')

    # engine = engine_from_config(configfile['WeightLossBot'], 'sqlalchemy.')
    # DBSession.configure(bind=engine)
    # Base.metadata.create_all(engine)

    mybot = WeightLossBot(configfile)
    mybot.run()
