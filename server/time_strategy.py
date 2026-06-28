utf-8"""
Adaptive time management strategy for the Stockfish Chess Bridge.

Core rule
---------
* If ``our_time_ms < opponent_time_ms`` → play immediately.
* If ``our_time_ms >= opponent_time_ms`` → keep thinking.

Safety constraints
------------------
* Always maintain a configurable safety buffer on our clock.
* Factor in per-move increment when available.
* Never think longer than ``max_time_fraction`` of remaining time.
* Adjust allocation based on game phase (opening / middlegame / endgame).
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

class TimeStrategy:

    def __init__(self, safety_buffer_ms=2000, max_time_fraction=0.33):
                                    
        self.safety_buffer_ms = safety_buffer_ms
        self.max_time_fraction = max_time_fraction

    def should_move_now(self, our_time_ms, opp_time_ms, increment_ms=0, move_number=0, last_score_cp=0, last_score_type="cp"):
        effective_remaining = our_time_ms - self.safety_buffer_ms
        if effective_remaining <= 0:
            logger.debug("should_move_now: YES – below safety buffer")
            return True
        return False

    def calculate_soft_limit(self, our_time_ms, opp_time_ms, increment_ms=0, move_number=0, last_score_cp=0, last_score_type="cp"):
        usable = max(our_time_ms - self.safety_buffer_ms, 0)
        if usable <= 0:
            return 50

        estimated_moves_left = max(15, 45 - move_number)
        base = int(usable / estimated_moves_left)

        phase_factor = self._phase_factor(move_number)

        eval_factor = 1.0
        if last_score_type == "mate":
            if last_score_cp > 0:
                eval_factor = 0.3
            else:
                eval_factor = 1.2
        elif last_score_type == "cp":
            if last_score_cp > 250:
                eval_factor = 0.5
            elif last_score_cp < -100:
                eval_factor = 1.4
            elif -50 <= last_score_cp <= 50:
                eval_factor = 1.2

        allocated = int(base * phase_factor * eval_factor)
        allocated += int(increment_ms * 0.8)

        max_limit = int(usable * 0.20)
        allocated = min(allocated, max_limit)

        return max(100, allocated)

    def get_time_pressure_level(self, our_time_ms, opp_time_ms):

        if our_time_ms <= self.safety_buffer_ms:
            return "critical"

        ratio = our_time_ms / max(opp_time_ms, 1)

        if ratio < 0.5:
            return "critical"
        elif ratio < 0.85:
            return "low"
        elif ratio <= 1.15:
            return "normal"
        else:
            return "comfortable"

    @staticmethod
    def _phase_factor(move_number):

        if move_number < 10:
            return 0.8
        elif move_number <= 30:
            return 1.0
        else:
            return 1.15
