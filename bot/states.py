"""
aiogram 3.x FSM states for the Telegram bot.

Flow per manager:
  1. Manager sends an audio/video file (or voice message)
  2. Bot asks: "Add a comment or skip?"  → WaitingComment state
  3. Manager replies with text (saved as comment) or sends /skip
  4. Bot confirms and enqueues the call for processing

State: WaitingComment
  Entered: after a file is received and temporarily stored
  Exited: when manager sends a comment OR sends /skip

The file info (file_id + project_id) is stored in FSM state data so it is
available when the comment arrives.
"""

from aiogram.fsm.state import State, StatesGroup


class UploadFlow(StatesGroup):
    # Manager has sent a file; bot is waiting for their comment or /skip
    waiting_comment = State()
