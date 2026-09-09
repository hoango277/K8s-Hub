"""Chat / NL command endpoints.

TODO:
  POST   /chat/threads                 - tao thread moi
  GET    /chat/threads                 - list threads
  GET    /chat/threads/{id}/messages   - lich su message + tool calls
  POST   /chat/threads/{id}/stream     - SSE: token | tool_call_start | tool_call_end
                                          | plan | approval_required | message_done
"""

from fastapi import APIRouter

router = APIRouter()
