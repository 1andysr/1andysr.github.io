from dataclasses import dataclass
from typing import List, Dict, Any

@dataclass
class PollData:
    question: str
    options: List[str]
    is_anonymous: bool
    type: str
    allows_multiple_answers: bool
    user_id: int

@dataclass
class ConfessionData:
    text: str
    user_id: int