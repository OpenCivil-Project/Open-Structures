from PyQt6.QtCore import QObject, QTimer, pyqtSignal, QElapsedTimer
import math

class AnimationManager(QObject):
    """
    Manages the 'Heartbeat' of the structure.
    Uses Phase Accumulation to allow smooth speed changes.
    
    NEW: Coordinates with Canvas to pre-render ALL geometry frames for buttery smooth playback.
    """
    signal_frame_update = pyqtSignal(float)
    signal_ltha_frame_update = pyqtSignal(int)                                      
    signal_prerender_progress = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._on_tick)
        
        self.fps = 30
        self.base_period = 2.0
        self.speed_factor = 1.0
        
        self.is_running = False
        self.current_phase = 0.0

        self.prerendered_frames = []
        self.is_prerendered = False
        self.current_frame_index = 0
        self.total_frames = 60

        self.ltha_mode = False                                               
        self.ltha_n_steps = 0                                          
        self.ltha_dt = 0.01                                           
        self.ltha_current_step = 0                                 
        self.ltha_prerender_start = None                                         
        self.ltha_prerender_end   = None

        self.canvas = None

        self.elapsed_timer = QElapsedTimer()
        self.last_tick_time = 0
        self.ltha_time_accumulator = 0.0
        
    def set_speed(self, factor):
        """Updates speed multiplier (0.5x to 5.0x)."""
        self.speed_factor = factor

    def enable_ltha_mode(self, n_steps, dt=0.01):
        self.ltha_mode = True
        self.ltha_n_steps = n_steps
        self.ltha_dt = dt
        self.ltha_current_step = 0
        self.ltha_prerender_start = None
        self.ltha_prerender_end   = None
        self.is_prerendered = False
        print(f"[AnimationManager] LTHA mode enabled: {n_steps} steps, dt={dt}s")

    def disable_ltha_mode(self):
        self.ltha_mode = False
        self.ltha_n_steps = 0
        self.ltha_dt = 0.01
        self.ltha_current_step = 0
        self.ltha_prerender_start = None
        self.ltha_prerender_end   = None

    def scrub_to_step(self, t_index):
        """
        Jump to a specific timestep without playing.
        Called by the scrubber slider in the dialog.

        Args:
            t_index (int): Timestep to display.
        """
        if not self.ltha_mode:
            return
        self.ltha_current_step = max(0, min(t_index, self.ltha_n_steps - 1))
        self.signal_ltha_frame_update.emit(self.ltha_current_step)

    def prerender_frames(self, progress_callback=None):
        """
        Pre-generates all animation frames (anim_factor values only).
        
        Args:
            progress_callback: Optional function(percent) called with progress 0-100
            
        This calculates all anim_factor values for one complete breathing cycle.
        We store 60 frames (2 seconds at 30 FPS).
        
        NOTE: This only pre-renders the FACTORS. The Canvas will pre-render 
        the actual GEOMETRY separately.
        """
        self.prerendered_frames.clear()
        self.is_prerendered = False
        
        for frame_idx in range(self.total_frames):
                                                        
            phase = (frame_idx / self.total_frames) * (2 * math.pi)
            
            anim_factor = math.sin(phase)
            
            self.prerendered_frames.append(anim_factor)
            
            if progress_callback:
                percent = int((frame_idx + 1) / self.total_frames * 100)
                progress_callback(percent)
        
        self.is_prerendered = True

    def start_animation(self, progress_callback=None):
        """
        Starts the animation playback.
        In LTHA mode: skips pre-render, just starts the timer stepping through timesteps.
        In normal mode: pre-renders sine frames and geometry as before.
        """
        if self.is_running:
            return

        if self.ltha_mode:
                                                                                 
            n = self.ltha_n_steps
            if self.ltha_prerender_start is not None:
                start = self.ltha_prerender_start
                end = self.ltha_prerender_end
                if not (start <= self.ltha_current_step <= end):
                    self.ltha_current_step = start
            else:
                if self.ltha_current_step >= n:
                    self.ltha_current_step = 0

            if self.canvas:
                self.canvas._ltha_vbo_built = False

            if self.canvas and hasattr(self.canvas, '_clear_static_elements'):
                self.canvas._clear_static_elements()
                
            self.ltha_time_accumulator = 0.0
            self.elapsed_timer.restart()
            self.last_tick_time = self.elapsed_timer.elapsed()
            
            self.is_running = True
            self.timer.start(int(1000 / self.fps))
            return

        if not self.is_prerendered:
            self.prerender_frames()

        if self.canvas:
            self.canvas._needs_anim_vbo_build = True
            self.canvas.update()

        self.elapsed_timer.restart()
        self.last_tick_time = self.elapsed_timer.elapsed()
        self.sine_accumulator = 0.0
        self.is_running = True
        self.current_frame_index = 0
        self.timer.start(int(1000 / self.fps))

    def stop_animation(self):
        self.is_running = False
        self.timer.stop()
        self.current_phase = 0.0

        if self.ltha_mode:
                                                                     
            self.signal_ltha_frame_update.emit(self.ltha_current_step)
        else:
            self.signal_frame_update.emit(0.0)
            if self.canvas and self.canvas.current_model:
                self.canvas.vbo_manager.set_anim_factor(0.0)
                self.canvas.vbo_manager.current_anim_factor = 0.0
                self.canvas._anim_vbo_built = False
                self.canvas._force_draw_model(
                    self.canvas.current_model,
                    self.canvas.selected_element_ids,
                    self.canvas.selected_node_ids
                )

    def invalidate_prerender(self):
        """
        Clears pre-rendered frames.
        Call this when:
        - Deflection scale changes
        - Model changes
        - Results change
        
        NEW: Also tells Canvas to clear its geometry cache
        """
        self.prerendered_frames.clear()
        self.is_prerendered = False
        self.current_frame_index = 0
        
        if self.canvas and hasattr(self.canvas, 'invalidate_animation_cache'):
            self.canvas.invalidate_animation_cache()

    def _on_tick(self):
        """Called every frame by the timer."""
        
        current_time = self.elapsed_timer.elapsed()
        dt_ms = current_time - self.last_tick_time
        self.last_tick_time = current_time

        if self.ltha_mode:
            self.signal_ltha_frame_update.emit(self.ltha_current_step)

            real_seconds_passed = dt_ms / 1000.0
            
            seismic_advance = real_seconds_passed * self.speed_factor
            
            self.ltha_time_accumulator += seismic_advance
            
            steps_to_advance = int(self.ltha_time_accumulator / self.ltha_dt)
            
            if steps_to_advance > 0:
                self.ltha_current_step += steps_to_advance
                                                                                
                self.ltha_time_accumulator -= (steps_to_advance * self.ltha_dt)

            if self.ltha_prerender_start is not None and self.ltha_prerender_end is not None:
                if self.ltha_current_step > self.ltha_prerender_end:
                    self.ltha_current_step = self.ltha_prerender_start
            else:
                if self.ltha_current_step >= self.ltha_n_steps:
                    self.ltha_current_step = 0
            return

        if self.is_prerendered and self.prerendered_frames:
            factor = self.prerendered_frames[self.current_frame_index]
            self.signal_frame_update.emit(factor)
            
            real_seconds_passed = dt_ms / 1000.0
            speed_adj = real_seconds_passed * self.fps * self.speed_factor
            
            if not hasattr(self, 'sine_accumulator'):
                self.sine_accumulator = 0.0
            self.sine_accumulator += speed_adj
            
            step = int(self.sine_accumulator)
            if step > 0:
                self.current_frame_index = (self.current_frame_index + step) % len(self.prerendered_frames)
                self.sine_accumulator -= step
            return
