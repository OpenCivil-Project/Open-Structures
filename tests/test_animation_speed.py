"""Check the real playback clock with deterministic elapsed time and no event loop."""
import contextlib
import io
import math
import unittest
from unittest.mock import Mock

from post.animation import AnimationManager

class _ElapsedClock:
    def __init__(self):
        self.milliseconds = 0

    def elapsed(self):
        return self.milliseconds

class AnimationSpeedTests(unittest.TestCase):
    def setUp(self):
                                                                               
        self.manager = AnimationManager()
        self.clock = _ElapsedClock()
        self.manager.elapsed_timer = self.clock
        with contextlib.redirect_stdout(io.StringIO()):
            self.manager.enable_ltha_mode(120, 0.01)

    def advance(self, milliseconds):
        self.clock.milliseconds += milliseconds
        self.manager._on_tick()

    def test_default_speed_is_one(self):
        self.assertEqual(self.manager.speed_factor, 1.0)
        self.advance(50)
        self.assertEqual(self.manager.ltha_current_step, 5)

    def test_hundred_times_speed_preserves_overshoot_across_multiple_cycles(self):
        self.manager.ltha_current_step = 7
        self.assertTrue(self.manager.set_speed(100))
        self.advance(250)
                                                                        
        self.assertEqual(self.manager.ltha_current_step, (7 + 2500) % 120)
        self.assertAlmostEqual(self.manager.ltha_time_accumulator, 0.0)

    def test_fractional_speed_accumulates_partial_steps(self):
        self.assertTrue(self.manager.set_speed(0.25))
        expected_steps = [0, 1, 1, 2]
        for expected in expected_steps:
            self.advance(20)
            self.assertEqual(self.manager.ltha_current_step, expected)
        self.assertAlmostEqual(self.manager.ltha_time_accumulator, 0.0)

    def test_selected_window_keeps_overshoot_inside_inclusive_range(self):
        self.manager.ltha_playback_start = 10
        self.manager.ltha_playback_end = 19
        self.manager.ltha_current_step = 18
        self.advance(50)
        self.assertEqual(self.manager.ltha_current_step, 13)

    def test_fast_selected_window_wraps_across_multiple_cycles(self):
        self.manager.ltha_playback_start = 10
        self.manager.ltha_playback_end = 20
        self.manager.ltha_current_step = 18
        self.manager.set_speed(100)
        self.advance(250)
        self.assertEqual(self.manager.ltha_current_step, 10 + (18 - 10 + 2500) % 11)

    def test_change_speed_mid_playback_preserves_position(self):
        self.manager.ltha_n_steps = 1000
        self.advance(100)
        self.assertEqual(self.manager.ltha_current_step, 10)
        self.assertTrue(self.manager.set_speed(100.0))
        self.assertEqual(self.manager.ltha_current_step, 10)
        self.advance(250)
        self.assertEqual(self.manager.ltha_current_step, 510)

    def test_numeric_text_is_accepted(self):
        self.assertTrue(self.manager.set_speed("12.75"))
        self.assertEqual(self.manager.speed_factor, 12.75)

    def test_invalid_speed_retains_previous_valid_value(self):
        self.manager.set_speed(3.5)
        for value in (0, -1, math.nan, math.inf, -math.inf, None, "bad"):
            with self.subTest(value=value):
                self.assertFalse(self.manager.set_speed(value))
                self.assertEqual(self.manager.speed_factor, 3.5)

    def test_paused_range_change_seeks_to_start_and_updates_display(self):
        emitted = []
        self.manager.signal_ltha_frame_update.connect(emitted.append)
        self.manager.ltha_time_accumulator = 0.007
        self.assertTrue(self.manager.set_ltha_playback_range(20, 40))
        self.assertEqual(self.manager.ltha_current_step, 20)
        self.assertEqual(emitted, [20])
        self.assertEqual(self.manager.ltha_time_accumulator, 0.0)
        self.assertFalse(self.manager.is_running)
        self.assertFalse(self.manager.timer.isActive())

    def test_range_change_keeps_current_step_and_fraction_when_inside(self):
        emitted = []
        self.manager.signal_ltha_frame_update.connect(emitted.append)
        self.manager.ltha_current_step = 25
        self.manager.ltha_time_accumulator = 0.007
        self.assertTrue(self.manager.set_ltha_playback_range(20, 40))
        self.assertEqual(self.manager.ltha_current_step, 25)
        self.assertEqual(self.manager.ltha_time_accumulator, 0.007)
        self.assertEqual(emitted, [])

    def test_running_range_change_keeps_timer_running(self):
        self.manager.is_running = True
        running_timer = Mock()
        self.manager.timer = running_timer
        self.manager.ltha_current_step = 90
        self.manager.ltha_time_accumulator = 0.007
        self.assertTrue(self.manager.set_ltha_playback_range(20, 40))
        self.assertEqual(self.manager.ltha_current_step, 20)
        self.assertEqual(self.manager.ltha_time_accumulator, 0.0)
        self.assertTrue(self.manager.is_running)
        self.assertEqual(running_timer.mock_calls, [])
        self.advance(50)
        self.assertEqual(self.manager.ltha_current_step, 25)

    def test_repeated_range_does_not_reset_playback(self):
        self.manager.set_ltha_playback_range(20, 40)
        self.manager.ltha_current_step = 25
        self.manager.ltha_time_accumulator = 0.007
        emitted = []
        self.manager.signal_ltha_frame_update.connect(emitted.append)
        self.assertTrue(self.manager.set_ltha_playback_range(20, 40))
        self.assertEqual(self.manager.ltha_current_step, 25)
        self.assertEqual(self.manager.ltha_time_accumulator, 0.007)
        self.assertEqual(emitted, [])

    def test_range_endpoints_clamp_to_available_history(self):
        self.assertTrue(self.manager.set_ltha_playback_range(-50, 20))
        self.assertEqual((self.manager.ltha_playback_start, self.manager.ltha_playback_end),
                         (0, 20))
        self.assertTrue(self.manager.set_ltha_playback_range(150, 200))
        self.assertEqual((self.manager.ltha_playback_start, self.manager.ltha_playback_end),
                         (119, 119))
        self.assertEqual(self.manager.ltha_current_step, 119)

    def test_inverted_and_invalid_ranges_leave_selection_unchanged(self):
        self.manager.set_ltha_playback_range(20, 40)
        self.manager.ltha_current_step = 25
        self.manager.ltha_time_accumulator = 0.007
        for start, end in ((80, 20), (200, 150), (math.nan, 30), (20, math.inf),
                           (20.5, 40), (None, 40), ("bad", 40)):
            with self.subTest(start=start, end=end):
                self.assertFalse(self.manager.set_ltha_playback_range(start, end))
                self.assertEqual((self.manager.ltha_playback_start, self.manager.ltha_playback_end),
                                 (20, 40))
                self.assertEqual(self.manager.ltha_current_step, 25)
                self.assertEqual(self.manager.ltha_time_accumulator, 0.007)

    def test_single_frame_range_holds_that_frame_at_high_speed(self):
        self.assertTrue(self.manager.set_ltha_playback_range(21, 21))
        self.manager.set_speed(100)
        self.advance(250)
        self.assertEqual(self.manager.ltha_current_step, 21)

    def test_full_history_range_clears_selection_without_resetting_current_frame(self):
        self.manager.set_ltha_playback_range(20, 40)
        self.manager.ltha_current_step = 25
        self.manager.ltha_time_accumulator = 0.007
        self.assertTrue(self.manager.set_ltha_playback_range(-50, 200))
        self.assertIsNone(self.manager.ltha_playback_start)
        self.assertIsNone(self.manager.ltha_playback_end)
        self.assertEqual(self.manager.ltha_current_step, 25)
        self.assertEqual(self.manager.ltha_time_accumulator, 0.007)

    def test_range_requires_loaded_time_history(self):
        self.manager.disable_ltha_mode()
        self.assertFalse(self.manager.set_ltha_playback_range(0, 1))

if __name__ == "__main__":
    unittest.main()
