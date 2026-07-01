import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

class TimeStrategy:

    def __init__(self, safety_buffer_ms=2000, max_time_fraction=0.33, speed_mode=2):
        self.base_safety_buffer_ms = safety_buffer_ms
        self.speed_mode = speed_mode
        
        if speed_mode == 1:
            self.max_time_fraction = 0.40
            self.safety_buffer_ms = safety_buffer_ms
        elif speed_mode == 3:
            self.max_time_fraction = 0.15
            self.safety_buffer_ms = int(safety_buffer_ms * 0.75)
        elif speed_mode == 4:
            self.max_time_fraction = 0.05
            self.safety_buffer_ms = int(safety_buffer_ms * 0.50)
        else: # speed_mode == 2
            self.max_time_fraction = max_time_fraction if max_time_fraction != 0.33 else 0.25
            self.safety_buffer_ms = safety_buffer_ms

    def is_untimed(self, our_time_ms: int, opp_time_ms: int) -> bool:
        # If both clocks are 0, it is an untimed game.
        return our_time_ms == 0 and opp_time_ms == 0

    def get_decision_params(
        self,
        our_time_ms: int,
        opp_time_ms: int,
        increment_ms: int = 0,
        move_number: int = 0,
        last_score_cp: int = 0,
        last_score_type: str = "cp"
    ) -> Tuple[Optional[int], int, str]:
        """
        Calculates the target thinking time (in ms) and target depth for the current position.
        Returns:
            (target_time_ms, target_depth, speed_name)
        """
        # 1. Check if Untimed Game
        if self.is_untimed(our_time_ms, opp_time_ms):
            # Speed 1 (Opening, <= 6 moves)
            if move_number <= 6:
                return 500, 10, "Speed 1 (Opening, Untimed)"
            
            # Speed 2 (Destruction / Crush)
            is_crushing = (last_score_type == "mate" and last_score_cp > 0) or (last_score_type == "cp" and last_score_cp > 400)
            if is_crushing:
                return 1000, 14, "Speed 2 (Destruction, Untimed)"
            
            # Speed 4 (Survival)
            is_losing = (last_score_type == "mate" and last_score_cp < 0) or (last_score_type == "cp" and last_score_cp < -150)
            if is_losing:
                return 4000, 20, "Speed 4 (Survival, Untimed)"
            
            # Speed 3 (Grind)
            return 2000, 18, "Speed 3 (Grind, Untimed)"

        # 2. Check Panic Mode (< 10s remaining)
        if our_time_ms < 10000:
            return 80, 5, "Panic Mode (Clock < 10s)"

        # 3. Speed 1 (Opening, <= 6 moves)
        if move_number <= 6:
            return 200, 99, "Speed 1 (Opening)"

        # 4. Speed 2 (Destruction / Crush)
        is_crushing = (last_score_type == "mate" and last_score_cp > 0) or (last_score_type == "cp" and last_score_cp > 400)
        if is_crushing:
            return 400, 99, "Speed 2 (Destruction)"

        # Determine remaining usable time
        usable = max(our_time_ms - self.safety_buffer_ms, 0)
        if usable <= 0:
            return 50, 5, "Panic Mode (Safety Buffer Exceeded)"

        # Base Grind calculation
        grind_time = usable / 30.0

        # 5. Speed 4 (Survival)
        is_losing = (last_score_type == "mate" and last_score_cp < 0) or (last_score_type == "cp" and last_score_cp < -150)
        if is_losing:
            target_time = grind_time * 1.5
            target_time = min(target_time, usable * 0.20)
            target_time += increment_ms * 0.8
            
            # Scale down if behind opponent on time
            if our_time_ms < opp_time_ms and opp_time_ms > 0:
                scale_factor = our_time_ms / opp_time_ms
                scale_factor = max(0.3, min(1.0, scale_factor))
                target_time *= scale_factor
                
            # Floor of 800ms for Survival to search for defensive resources
            target_time = max(target_time, min(800.0, usable))
            return int(target_time), 99, "Speed 4 (Survival)"

        # 6. Speed 3 (Grind)
        target_time = grind_time
        target_time = min(target_time, usable * 0.20)
        target_time += increment_ms * 0.8
        
        # Scale down if behind opponent on time
        if our_time_ms < opp_time_ms and opp_time_ms > 0:
            scale_factor = our_time_ms / opp_time_ms
            scale_factor = max(0.3, min(1.0, scale_factor))
            target_time *= scale_factor
            
        # Floor of 500ms for Grind to prevent severe blunders
        target_time = max(target_time, min(500.0, usable))
        return int(target_time), 99, "Speed 3 (Grind)"

    def should_move_now(self, our_time_ms, opp_time_ms, increment_ms=0, move_number=0, last_score_cp=0, last_score_type="cp"):
        if self.is_untimed(our_time_ms, opp_time_ms):
            return False
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

        # Apply speed mode multipliers to allocated time
        speed_multipliers = {1: 1.5, 2: 1.0, 3: 0.6, 4: 0.2}
        multiplier = speed_multipliers.get(self.speed_mode, 1.0)
        allocated = int(allocated * multiplier)

        max_limit = int(usable * self.max_time_fraction)
        allocated = min(allocated, max_limit)

        return max(100, allocated)

    def _phase_factor(self, move_number):
        if move_number < 10: return 0.8
        if move_number < 30: return 1.0
        return 1.2

    def get_time_pressure_level(self, our_time_ms: int, opp_time_ms: int) -> str:
        if self.is_untimed(our_time_ms, opp_time_ms):
            return "comfortable"
        if our_time_ms <= self.safety_buffer_ms:
            return "critical"

        ratio = our_time_ms / max(opp_time_ms, 1)
        if ratio < 0.5 or our_time_ms < 10000:
            return "critical"
        elif ratio < 0.85:
            return "low"
        elif ratio <= 1.15:
            return "normal"
        else:
            return "comfortable"
