"""
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

        our_effective = our_time_ms + increment_ms
        opp_effective = opp_time_ms + increment_ms             

        if our_effective < opp_effective:
            logger.debug(
                "should_move_now: YES – our effective %d < opp effective %d",
                our_effective,
                opp_effective,
            )
            return True

        soft_limit = self.calculate_soft_limit(
            our_time_ms, opp_time_ms, increment_ms, move_number, last_score_cp, last_score_type
        )
        return False

    def calculate_soft_limit(self, our_time_ms, opp_time_ms, increment_ms=0, move_number=0, last_score_cp=0, last_score_type="cp"):

        usable = max(our_time_ms - self.safety_buffer_ms, 0)

        base = int(usable * self.max_time_fraction)

        phase_factor = self._phase_factor(move_number)

        eval_factor = 1.0
        if last_score_type == "mate":
            if last_score_cp > 0:
                eval_factor = 0.25                              
            else:
                eval_factor = 1.1                                          
        elif last_score_type == "cp":
            if last_score_cp > 300:
                eval_factor = 0.5                             
            elif last_score_cp < -150:
                eval_factor = 1.25                       
            elif -50 <= last_score_cp <= 50:
                eval_factor = 1.1                                        

        allocated = int(base * phase_factor * eval_factor)

        allocated += increment_ms // 2

        hard_cap = int(usable * 0.5)
        allocated = min(allocated, hard_cap)

        allocated = max(allocated, 0)

        logger.debug(
            "soft_limit: usable=%d base=%d phase=%.2f eval=%.2f inc=%d => %d ms",
            usable,
            base,
            phase_factor,
            eval_factor,
            increment_ms,
            allocated,
        )
        return allocated

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
