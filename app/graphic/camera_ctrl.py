import numpy as np
from PyQt6.QtGui import QVector3D
from PyQt6.QtCore import Qt, QTimer, QVariantAnimation, QEasingCurve, QAbstractAnimation
import math

class ArcballCamera:
    def __init__(self, view_widget):
        self.view = view_widget
        self._model_scale = None
        
        # 60 FPS Smoothing Engine
        self.t_center = None
        self.t_dist = None
        self.t_az = None
        self.t_el = None
        
        self.smooth_timer = QTimer()
        self.smooth_timer.timeout.connect(self._physics_tick)
        self.smooth_timer.start(16) # ~60 FPS
        
        self.anim = QVariantAnimation()
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim.valueChanged.connect(self._on_anim_step)

    def set_model_scale(self, scale: float):
        self._model_scale = max(float(scale), 1e-6)

    def _effective_scale(self) -> float:
        if self._model_scale is not None:
            return self._model_scale
        return max(self.view.opts.get('distance', 10.0) * 0.5, 1e-6)

    def _sync_targets(self):
        """Ensures the smoothing targets match the current view state before interacting."""
        if self.t_center is None:
            self.t_center = QVector3D(self.view.opts['center'])
            self.t_dist = self.view.opts['distance']
            self.t_az = self.view.opts['azimuth']
            self.t_el = self.view.opts['elevation']

    def _physics_tick(self):
        """The 60 FPS loop that smoothly interpolates camera movement."""
        # 1. DO NOT run physics if the View Cube / Standard View animation is playing!
        if self.anim.state() == QAbstractAnimation.State.Running:
            return

        if self.t_center is None: return
        
        lerp_speed = 0.25 
        
        c_c = self.view.opts['center']
        c_d = self.view.opts['distance']
        c_az = self.view.opts['azimuth']
        c_el = self.view.opts['elevation']
        
        # 2. ANTI-RUBBERBAND: If PyQtGraph defaults moved the camera externally, 
        # intercept the new coordinates so the physics engine doesn't snap it back!
        if hasattr(self, 'last_c_az'):
            if abs(c_az - self.last_c_az) > 0.01 or abs(c_el - self.last_c_el) > 0.01:
                self.t_az = c_az
                self.t_el = c_el
                self.t_center = QVector3D(c_c)
                self.t_dist = c_d
        
        diff_c = self.t_center - c_c
        diff_d = self.t_dist - c_d
        
        diff_az = (self.t_az - c_az) % 360
        if diff_az > 180: diff_az -= 360
        
        diff_el = self.t_el - c_el
        
        if diff_c.length() > 0.001 or abs(diff_d) > 0.001 or abs(diff_az) > 0.001 or abs(diff_el) > 0.001:
            self.view.opts['center'] = c_c + (diff_c * lerp_speed)
            self.view.opts['distance'] = c_d + (diff_d * lerp_speed)
            self.view.opts['azimuth'] = c_az + (diff_az * lerp_speed)
            self.view.opts['elevation'] = c_el + (diff_el * lerp_speed)
            self.view.update()
            
        # Store last known state
        self.last_c_az = self.view.opts['azimuth']
        self.last_c_el = self.view.opts['elevation']
        self.last_c_d = self.view.opts['distance']

    def zoom(self, delta, mouse_x, mouse_y, width, height):
        self._sync_targets()
        scale = self._effective_scale()
        min_dist = scale * 0.02
        fly_thresh = scale * 0.12

        # 3. SAP2000 FLY-THROUGH ZOOM: 
        # When you hit the zoom wall, push the pivot point forward so you can traverse infinitely
        if self.t_dist < fly_thresh and delta > 0:
            view_vec = self._view_direction(use_targets=True)
            step = max(self.t_dist * 0.15, min_dist * 0.5)                      
            self.t_center += (view_vec * step)
            return

        factor = 0.85 if delta > 0 else 1.18
        new_dist = max(self.t_dist * factor, min_dist)

        fov = self.view.opts['fov']
        if fov == 0:
            view_h = 2.0 * self.t_dist 
        else:
            view_h = 2.0 * self.t_dist * math.tan(math.radians(fov) / 2.0)
        
        view_w = view_h * (width / height)
        off_x = (mouse_x / width) - 0.5
        off_y = -((mouse_y / height) - 0.5)

        forward = self._view_direction(use_targets=True)
        global_up = QVector3D(0, 0, 1) if abs(forward.z()) < 0.95 else QVector3D(0, 1, 0)
        right = QVector3D.crossProduct(forward, global_up).normalized()
        up = QVector3D.crossProduct(right, forward).normalized()

        shift = 1.0 - factor
        move_vec = (right * (off_x * view_w * shift)) + (up * (off_y * view_h * shift))
        
        self.t_center += move_vec
        self.t_dist = new_dist

    def rotate(self, dx, dy):
        self._sync_targets()
        SENSITIVITY = 0.25 
        
        self.t_el = max(-89.999, min(89.999, self.t_el + dy * SENSITIVITY))
        self.t_az -= dx * SENSITIVITY
        
        if hasattr(self.view, 'show_pivot_dot'):
            self.view.show_pivot_dot(True)

    def pan(self, dx, dy, width, height):
        self._sync_targets()
        fov = self.view.opts['fov']

        if fov == 0:
            visible_h = 2.0 * self.t_dist 
        else:
            visible_h = 2.0 * self.t_dist * math.tan(math.radians(fov) / 2.0)

        scale = visible_h / height                                 
        forward = self._view_direction(use_targets=True)
        
        az_rad = math.radians(self.t_az)
        right = QVector3D(-math.sin(az_rad), math.cos(az_rad), 0.0).normalized()
        up = QVector3D.crossProduct(right, forward).normalized()

        move_vec = (right * (-dx * scale)) + (up * (dy * scale))
        self.t_center += move_vec

    def animate_to(self, target_center=None, target_dist=None, target_az=None, target_el=None):
        self.anim.stop()
        
        self.t_center = target_center if target_center is not None else self.view.opts['center']
        self.t_dist = target_dist if target_dist is not None else self.view.opts['distance']
        self.t_az = target_az if target_az is not None else self.view.opts['azimuth']
        self.t_el = target_el if target_el is not None else self.view.opts['elevation']

        self.anim_start = {
            'c': self.view.opts['center'], 'd': self.view.opts['distance'],
            'a': self.view.opts['azimuth'], 'e': self.view.opts['elevation']
        }
        self.anim_end = {
            'c': self.t_center, 'd': self.t_dist,
            'a': self.t_az, 'e': self.t_el
        }

        # Prevent 300-degree backflips when switching view planes
        az_start = self.anim_start['a']
        az_end = self.anim_end['a']
        if abs(az_end - az_start) > 180:
            if az_end > az_start:
                az_start += 360
            else:
                az_end += 360
        self.anim_start['a'] = az_start

        self.anim.setDuration(400) 
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.start()

    def _view_direction(self, use_targets=False) -> QVector3D:
        az = np.radians(self.t_az if use_targets else self.view.opts['azimuth'])
        el = np.radians(self.t_el if use_targets else self.view.opts['elevation'])
        x = np.cos(el) * np.cos(az)
        y = np.cos(el) * np.sin(az)
        z = np.sin(el)
        return QVector3D(-x, -y, -z)

    def get_view_direction(self) -> QVector3D:
        return self._view_direction()

    def _on_anim_step(self, t):
        s, e = self.anim_start, self.anim_end
        self.view.opts['center'] = s['c'] + (e['c'] - s['c']) * t
        self.view.opts['distance'] = s['d'] + (e['d'] - s['d']) * t
        self.view.opts['azimuth'] = s['a'] + (e['a'] - s['a']) * t
        self.view.opts['elevation'] = s['e'] + (e['e'] - s['e']) * t
        self.view.update()