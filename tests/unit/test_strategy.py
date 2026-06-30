import pytest
from time_strategy import TimeStrategy

def test_time_strategy_speed_scaling():
    # Test identical remaining game times (e.g. 5 minutes, 1 minute, 10 seconds)
    game_times = [300000, 60000, 10000]
    
    for t in game_times:
        ts1 = TimeStrategy(safety_buffer_ms=2000, speed_mode=1)
        ts2 = TimeStrategy(safety_buffer_ms=2000, speed_mode=2)
        ts3 = TimeStrategy(safety_buffer_ms=2000, speed_mode=3)
        ts4 = TimeStrategy(safety_buffer_ms=2000, speed_mode=4)
        
        limit1 = ts1.calculate_soft_limit(our_time_ms=t, opp_time_ms=t)
        limit2 = ts2.calculate_soft_limit(our_time_ms=t, opp_time_ms=t)
        limit3 = ts3.calculate_soft_limit(our_time_ms=t, opp_time_ms=t)
        limit4 = ts4.calculate_soft_limit(our_time_ms=t, opp_time_ms=t)
        
        # Verify strict ordering limit1 > limit2 > limit3 > limit4
        assert limit1 > limit2 > limit3 > limit4
        
        # Verify safety thresholds trigger earlier (i.e. safety_buffer_ms is smaller at higher speeds)
        assert ts1.safety_buffer_ms == 2000
        assert ts2.safety_buffer_ms == 2000
        assert ts3.safety_buffer_ms == 1500
        assert ts4.safety_buffer_ms == 1000
