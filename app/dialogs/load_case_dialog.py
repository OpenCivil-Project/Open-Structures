from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QListWidget,
                             QPushButton, QLabel, QComboBox, QTableWidget,
                             QTableWidgetItem, QGroupBox, QSpinBox, QCheckBox,
                             QMessageBox, QHeaderView, QLineEdit, QWidget,
                             QRadioButton, QButtonGroup, QFileDialog,
                             QScrollArea, QFrame)
from PyQt6.QtCore import Qt
from core.model import LoadCase, get_opensees_block, SHEAR_SPRING_UI_DEFAULTS
from core.opensees_port.os_capabilities import is_opensees
from app.dialogs.protocol_dialog import ProtocolGeneratorDialog
from PyQt6.QtWidgets import QApplication

from app.ui.theme import apply_dialog_style      
from core.units import unit_registry        
import copy
from PyQt6.QtWidgets import QFormLayout

def _scroll_layouts(dialog):
    """Give a dialog a scrollable content area with a fixed button row below it.

    Returns (outer, body): add the content to `body` (as before) and the OK/Cancel
    row to `outer`, so the buttons stay visible and the content scrolls instead of
    being squashed when the window is small.
    """
    outer = QVBoxLayout(dialog)
    body_w = QWidget()
    body_w.setObjectName("scrollBody")
    body_w.setStyleSheet("#scrollBody { background: transparent; }")
    body = QVBoxLayout(body_w)
    body.setContentsMargins(0, 0, 0, 0)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.viewport().setAutoFillBackground(False)
    scroll.setWidget(body_w)
    outer.addWidget(scroll, 1)
    return outer, body

def _fit_to_screen(dialog, w, h):
    """Resize to (w, h) but never larger than 92% / 88% of the available screen."""
    try:
        a = dialog.screen().availableGeometry()
        dialog.resize(min(w, int(a.width() * 0.92)), min(h, int(a.height() * 0.88)))
    except Exception:
        dialog.resize(w, h)

class NonlinearParametersDialog(QDialog):
    """Sub-dialog for Nonlinear Solution Control and Target Force Iteration."""
    def __init__(self, case, parent=None, model=None):
        super().__init__(parent)
        self.case = case
        self.opensees = bool(model is not None and is_opensees(model))
        self.setWindowTitle("Nonlinear Parameters (OpenSees)" if self.opensees else "Nonlinear Parameters")
        apply_dialog_style(self)
        try:
            _avail = self.screen().availableGeometry()
            self.resize(min(940, int(_avail.width() * 0.92)), min(640, int(_avail.height() * 0.88)))
        except Exception:
            self.resize(940, 640)

        layout = QVBoxLayout(self)

        body = QWidget(); body.setObjectName("nlBody")
        body.setStyleSheet("#nlBody { background: transparent; }")
        cols = QHBoxLayout(body)
        cols.setContentsMargins(0, 0, 0, 0)
        col_l = QVBoxLayout(); col_r = QVBoxLayout()
        cols.addLayout(col_l, 1); cols.addLayout(col_r, 1)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.viewport().setAutoFillBackground(False)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)

        grp_sol = QGroupBox("Solution Control")
        form_sol = QFormLayout(grp_sol)

        self.in_total_steps = QSpinBox(); self.in_total_steps.setRange(1, 99999); self.in_total_steps.setValue(getattr(self.case, 'max_total_steps', 200))
        self.in_null_steps = QSpinBox(); self.in_null_steps.setRange(1, 9999); self.in_null_steps.setValue(getattr(self.case, 'max_null_steps', 50))
        
        self.cmb_event_stepping = QComboBox(); self.cmb_event_stepping.addItems(["Yes", "No"])
        self.cmb_event_stepping.setCurrentText("Yes" if getattr(self.case, 'use_event_stepping', True) else "No")
        
        self.in_event_tol = QLineEdit(f"{getattr(self.case, 'event_lumping_tol', 0.01):.2f}")
        self.in_max_events = QSpinBox(); self.in_max_events.setRange(1, 999); self.in_max_events.setValue(getattr(self.case, 'max_events_per_step', 24))
        
        self.cmb_iteration = QComboBox(); self.cmb_iteration.addItems(["Yes", "No"])
        self.cmb_iteration.setCurrentText("Yes" if getattr(self.case, 'use_iteration', True) else "No")
        
        self.in_const_iter = QSpinBox(); self.in_const_iter.setRange(0, 999); self.in_const_iter.setValue(getattr(self.case, 'max_const_stiff_iter', 10))
        self.in_nr_iter = QSpinBox(); self.in_nr_iter.setRange(0, 999); self.in_nr_iter.setValue(getattr(self.case, 'max_nr_iter', 40))
        
        self.in_conv_tol = QLineEdit(f"{getattr(self.case, 'iter_conv_tol', 1e-4):.3E}")
        
        self.cmb_line_search = QComboBox(); self.cmb_line_search.addItems(["Yes", "No"])
        self.cmb_line_search.setCurrentText("Yes" if getattr(self.case, 'use_line_search', False) else "No")

        self.cmb_fd_tangent = QComboBox(); self.cmb_fd_tangent.addItems(["Analytical", "Finite Difference"])
        self.cmb_fd_tangent.setCurrentText("Finite Difference" if getattr(self.case, 'use_fd_tangent', False) else "Analytical")

        form_sol.addRow("Maximum Total Steps per Stage", self.in_total_steps)
        form_sol.addRow("Maximum Null (Zero) Steps per Stage", self.in_null_steps)
        form_sol.addRow("Use Event-to-event Stepping", self.cmb_event_stepping)
        form_sol.addRow("Event Lumping Tolerance (Relative)", self.in_event_tol)
        form_sol.addRow("Maximum Events per Step", self.in_max_events)
        form_sol.addRow("Use Iteration", self.cmb_iteration)
        form_sol.addRow("Maximum Constant-Stiff Iterations per Step", self.in_const_iter)
        form_sol.addRow("Maximum Newton-Raphson Iter. per Step", self.in_nr_iter)
        form_sol.addRow("Iteration Convergence Tolerance (Relative)", self.in_conv_tol)
        form_sol.addRow("Use Line Search", self.cmb_line_search)
        form_sol.addRow("Tangent Stiffness Method", self.cmb_fd_tangent)
        col_l.addWidget(grp_sol)
        col_l.addStretch()

        grp_hinge = QGroupBox("Fiber Hinge Behavior")
        form_hinge = QFormLayout(grp_hinge)

        self.cmb_hinge_snap = QComboBox(); self.cmb_hinge_snap.addItems(["Yes", "No"])
        self.cmb_hinge_snap.setCurrentText("Yes" if getattr(self.case, 'hinge_snap', True) else "No")
        self.cmb_snap_scope = QComboBox(); self.cmb_snap_scope.addItems(["Tension Fibers Only", "All Fibers"])
        self.cmb_snap_scope.setCurrentText("All Fibers" if getattr(self.case, 'hinge_snap_scope', 'tension') == 'all' else "Tension Fibers Only")

        self.in_res_floor = QLineEdit(f"{getattr(self.case, 'residual_stiffness', 1e-8):.2E}")
        form_hinge.addRow("Snap Failed Fibers to Zero (Hinge Snap)", self.cmb_hinge_snap)
        form_hinge.addRow("Hinge Snap Applies To", self.cmb_snap_scope)
        form_hinge.addRow("Residual Section Stiffness (Relative)", self.in_res_floor)

        self.cmb_stop_fiber = QComboBox(); self.cmb_stop_fiber.addItems(["No", "Yes"])
        self.cmb_stop_fiber.setCurrentText("Yes" if getattr(self.case, 'stop_on_fiber_failure', False) else "No")
        form_hinge.addRow("Stop at First Fiber Failure", self.cmb_stop_fiber)
        col_r.addWidget(grp_hinge)

        grp_adv = QGroupBox("Advanced Stepping")
        form_adv = QFormLayout(grp_adv)
        self.in_min_step = QLineEdit(f"{getattr(self.case, 'min_step_frac', 1e-4):.2E}")
        self.in_max_probes = QSpinBox(); self.in_max_probes.setRange(1, 999); self.in_max_probes.setValue(getattr(self.case, 'max_event_probes', 12))
        self.cmb_cutback = QComboBox(); self.cmb_cutback.addItems(["Yes", "No"])
        self.cmb_cutback.setCurrentText("Yes" if getattr(self.case, 'auto_cutback', True) else "No")
        self.in_max_attempts = QSpinBox(); self.in_max_attempts.setRange(0, 9999999); self.in_max_attempts.setValue(int(getattr(self.case, 'max_step_attempts', 0) or 0))
        self.in_max_attempts.setSpecialValueText("Automatic")
        form_adv.addRow("Minimum Step Size (Fraction of Planned Step)", self.in_min_step)
        form_adv.addRow("Maximum Event Probes per Step", self.in_max_probes)
        form_adv.addRow("Automatic Step Cutback", self.cmb_cutback)
        form_adv.addRow("Maximum Solve Attempts", self.in_max_attempts)
        col_r.addWidget(grp_adv)

        grp_tf = QGroupBox("Target Force Iteration")
        form_tf = QFormLayout(grp_tf)
        
        self.in_tf_iter = QSpinBox(); self.in_tf_iter.setRange(1, 999); self.in_tf_iter.setValue(getattr(self.case, 'tf_max_iter', 10))
        self.in_tf_tol = QLineEdit(f"{getattr(self.case, 'tf_conv_tol', 0.01):.2f}")
        self.in_tf_accel = QLineEdit(f"{getattr(self.case, 'tf_accel_factor', 1.0):.1f}")
        
        self.cmb_continue = QComboBox(); self.cmb_continue.addItems(["Yes", "No"])
        self.cmb_continue.setCurrentText("Yes" if getattr(self.case, 'continue_if_no_converge', False) else "No")

        form_tf.addRow("Maximum Iterations per Stage", self.in_tf_iter)
        form_tf.addRow("Convergence Tolerance (Relative)", self.in_tf_tol)
        form_tf.addRow("Acceleration Factor", self.in_tf_accel)
        form_tf.addRow("Continue Analysis If No Convergence", self.cmb_continue)
        col_r.addWidget(grp_tf)
        col_r.addStretch()

        if self.opensees:
            self._build_opensees_groups(col_l, (grp_sol, grp_hinge, grp_adv, grp_tf))

        h_btns = QHBoxLayout()
        h_btns.addStretch()
        btn_ok = QPushButton("OK")
        btn_ok.setObjectName("primary")
        btn_ok.clicked.connect(self.accept)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        h_btns.addWidget(btn_ok)
        h_btns.addWidget(btn_cancel)
        layout.addLayout(h_btns)

        for _w, _t in (
            (self.in_total_steps, "Planned number of load increments per stage. Event steps and cutbacks can add more."),
            (self.in_null_steps, "Not wired."),
            (self.cmb_event_stepping, "Locates hinge state changes (cracking, yielding, crushing) and lands steps on them. Active only with fiber hinges and large displacements off."),
            (self.in_event_tol, "Event location precision, as a fraction of the planned step."),
            (self.in_max_events, "Not wired."),
            (self.cmb_iteration, "Not wired."),
            (self.in_const_iter, "Not wired."),
            (self.in_nr_iter, "Maximum Newton-Raphson iterations per step before cutback or failure."),
            (self.in_conv_tol, "Relative residual below which a step is converged."),
            (self.cmb_line_search, "Backtracking line search on each Newton update."),
            (self.cmb_fd_tangent, "Finite-difference tangent in place of the analytical one. Large displacements only."),
            (self.cmb_hinge_snap, "Fibers past their peak on the softening branch drop to zero stress and stiffness from the next step on. P-Delta cases with fiber hinges, monotonic loading."),
            (self.cmb_snap_scope, "Fibers eligible for hinge snap."),
            (self.in_res_floor, "Conditioning floor, as a fraction of gross EA and EI, that keeps the hinge section non-singular once every fiber has failed. Not a physical property."),
            (self.cmb_stop_fiber, "Ends the run at the first fiber failure and keeps results up to that step. P-Delta cases with fiber hinges only."),
            (self.in_min_step, "Smallest allowed load increment, as a fraction of the planned step."),
            (self.in_max_probes, "Maximum trial steps used to locate one hinge event."),
            (self.cmb_cutback, "Halves the step after a non-converged attempt and retries."),
            (self.in_max_attempts, "Cap on total solve attempts. Automatic = 20 x total steps + 500."),
            (self.in_tf_iter, "Not wired."),
            (self.in_tf_tol, "Not wired."),
            (self.in_tf_accel, "Not wired."),
            (self.cmb_continue, "Records a non-converged step as failed and continues instead of stopping with an error."),
        ):
            _w.setToolTip(_t)

        try:
            _avail = self.screen().availableGeometry()
            _h = min(body.sizeHint().height() + 90, int(_avail.height() * 0.88))
            self.resize(self.width(), _h)
        except Exception:
            pass

    def _build_opensees_groups(self, col, native_groups):
        """OpenSees engine: put the OpenSees settings first and grey out the native-solver groups."""
        blk = get_opensees_block(self.case)

        grp_os = QGroupBox("OpenSees Solution Control")
        form_os = QFormLayout(grp_os)
        self.cmb_os_test = QComboBox(); self.cmb_os_test.addItems(["NormDispIncr", "NormUnbalance", "EnergyIncr"])
        self.cmb_os_test.setCurrentText(str(blk["test_type"]))
        self.in_os_tol = QLineEdit(f"{float(blk['tolerance']):.3E}")
        self.in_os_iter = QSpinBox(); self.in_os_iter.setRange(1, 9999); self.in_os_iter.setValue(int(blk["max_iter"]))
        self.cmb_os_algo = QComboBox(); self.cmb_os_algo.addItems(["Newton", "ModifiedNewton", "NewtonLineSearch", "KrylovNewton", "BFGS", "Broyden"])
        self.cmb_os_algo.setCurrentText(str(blk["algorithm"]))
        form_os.addRow("Convergence Test", self.cmb_os_test)
        form_os.addRow("Convergence Tolerance", self.in_os_tol)
        form_os.addRow("Maximum Iterations per Step", self.in_os_iter)
        form_os.addRow("Solution Algorithm", self.cmb_os_algo)
        self.chk_os_relax = QCheckBox("Relax the tolerance as a last resort (flag the step as approximate)")
        self.chk_os_relax.setChecked(bool(blk.get("relax_on_fail", True)))
        self.in_os_relax = QLineEdit(f"{float(blk.get('relax_ceiling', 1e-5)):.3E}")
        form_os.addRow(self.chk_os_relax)
        form_os.addRow("Largest Relaxed Tolerance", self.in_os_relax)

        grp_el = QGroupBox("OpenSees Element Settings")
        form_el = QFormLayout(grp_el)
        self.in_os_nip = QSpinBox(); self.in_os_nip.setRange(2, 20); self.in_os_nip.setValue(int(blk["n_int_pts"]))
        self.in_os_fsr = QSpinBox(); self.in_os_fsr.setRange(1, 999); self.in_os_fsr.setValue(int(blk["fiber_size_ratio"]))
        form_el.addRow("Integration Points per Element", self.in_os_nip)
        form_el.addRow("Fiber Size Ratio", self.in_os_fsr)

        self.cmb_os_integ = QComboBox(); self.cmb_os_integ.addItems(["Lobatto", "HingeRadau"])
        self.cmb_os_integ.setCurrentText(str(blk.get("integration", "Lobatto")))
        self.in_os_lp = QLineEdit(f"{unit_registry.to_display_length(float(blk.get('hinge_length', 0.0) or 0.0)):.6g}")
        self.chk_os_slip = QCheckBox("Include base-slip spring (strain penetration)")
        self.chk_os_slip.setChecked(bool(blk.get("bar_slip", False)))
        self.chk_os_safety = QCheckBox("Stop if vertical reaction drifts from the applied load (0.1%)")
        self.chk_os_safety.setChecked(bool(blk.get("safety_check", True)))
        form_el.addRow("Beam Integration", self.cmb_os_integ)
        form_el.addRow(f"Hinge Length Lp ({unit_registry.length_unit_name}, 0 = auto)", self.in_os_lp)
        form_el.addRow(self.chk_os_slip)
        form_el.addRow(self.chk_os_safety)

        self.cmb_os_slipc = QComboBox(); self.cmb_os_slipc.addItems(["Stiff no-tension (E = Ec/Lsp)", "Full nonlinear (member concrete)",
                                    "Scaled nonlinear (member concrete, strains x Lsp)"])
        self.cmb_os_slipc.setCurrentIndex({"stiff": 0, "full": 1, "scaled": 2}.get(str(blk.get("slip_concrete", "stiff")), 0))
        form_el.addRow("Slip-Section Concrete", self.cmb_os_slipc)
        self._slip_fields = {}
        for _k, _lbl, _tip in (("slip_R", "Slip Pinching Factor R", "Bond_SP01 pinching, 1 = none. Zhao & Sritharan (2007): 0.5."),
                               ("slip_b", "Slip Hardening Ratio b", "Bond_SP01 post-yield stiffness ratio. Zhao & Sritharan (2007): 0.3."),
                               ("slip_sy_mult", "Slip Yield-Slip Scale", "Multiplies the Zhao & Sritharan yield slip. 1.0 = literature."),
                               ("slip_su_mult", "Slip Ultimate/Yield Ratio", "Ultimate slip = ratio x yield slip. Zhao & Sritharan (2007): 35.")):
            _e = QLineEdit(f"{float(blk.get(_k)):.6g}"); _e.setToolTip(_tip); self._slip_fields[_k] = _e; form_el.addRow(_lbl, _e)

        ss = blk.get("shear_spring")
        sd = dict(SHEAR_SPRING_UI_DEFAULTS); sd.update(ss or {})
        self.chk_os_shear = QCheckBox("Include series shear/slip spring at supported column ends")
        self.chk_os_shear.setChecked(bool(ss))
        self._force_factor = unit_registry.to_display_force(1.0) or 1.0                               
        self.in_ss_N = QLineEdit(f"{sd['N'] * self._force_factor:.6g}")
        self._ss_fields = {}
        _ss_rows = [("Vy_scale", "Yield Force Scale (x auto Vc+Vs)"), ("k0_scale", "Stiffness Scale (x auto G*As/L)"),
                    ("alpha", "Post-Yield Stiffness Ratio"), ("pinchX", "Pinch Factor X (deformation)"),
                    ("pinchY", "Pinch Factor Y (force)"), ("damage1", "Damage 1 (ductility)"),
                    ("damage2", "Damage 2 (energy)"), ("beta", "Unloading Stiffness Beta"),
                    ("e3_mult", "Post-Yield Point (x yield deformation)")]
        grp_ss = QGroupBox("Series Shear / Slip Spring (pinching)")
        form_ss = QFormLayout(grp_ss)
        form_ss.addRow(self.chk_os_shear)
        self.cmb_ss_stiff = QComboBox(); self.cmb_ss_stiff.addItems(["Cracked (truss analogy)", "Uncracked (G*As/L)"])
        self.cmb_ss_stiff.setCurrentIndex(0 if str(sd.get("shear_stiffness", "cracked")) == "cracked" else 1)
        self.cmb_ss_stiff.setToolTip("Cracked: after Vc the ties carry shear, k = Av*Es*d/(2*s*L) (45-degree truss, from the section). "
                                     "Uncracked: G*As/L, which adds almost nothing on top of the section's own elastic shear.")
        form_ss.addRow("Shear Stiffness After Cracking", self.cmb_ss_stiff)
        form_ss.addRow(f"Axial Load N on Column ({unit_registry.force_unit_name}, compression +)", self.in_ss_N)
        for _k, _lbl in _ss_rows:
            _e = QLineEdit(f"{float(sd[_k]):.6g}"); self._ss_fields[_k] = _e; form_ss.addRow(_lbl, _e)

        def _sync_shear(_=None):
            on = self.chk_os_shear.isChecked()
            self.in_ss_N.setEnabled(on); self.cmb_ss_stiff.setEnabled(on)
            for _e in self._ss_fields.values(): _e.setEnabled(on)
        self.chk_os_shear.toggled.connect(_sync_shear)
        _sync_shear()
        for _w, _t in (
            (self.cmb_os_slipc, "Concrete used inside the bar-slip section. The slip section is a unit-gauge zero-length element, so the "
                                "member's Concrete04 sees strain = rotation x y and crushes at ~0.7% drift. 'Stiff' is elastic, no tension, "
                                "E = Ec/Lsp with Lsp = 0.022*fy*db. 'Scaled' keeps the member's nonlinear concrete but expresses it per unit gauge "
                                "(strains x Lsp, E / Lsp), so it crushes at the real strains."),
            (self.chk_os_shear, "Pinched lateral spring in series with the fiber member (shear deformation + residual slip). Initial "
                                "stiffness G*As/L and yield force Vc+Vs (ACI 318) come from the section; shape constants are the fields below."),
            (self.in_ss_N, "Axial compression used in the ACI Vc term. 0 = ignored (the converter warns)."),
        ):
            _w.setToolTip(_t)

        def _sync_integ(_=None):
            self.in_os_lp.setEnabled(self.cmb_os_integ.currentText() == "HingeRadau")
            self.in_os_nip.setEnabled(self.cmb_os_integ.currentText() == "Lobatto")
        self.cmb_os_integ.currentTextChanged.connect(_sync_integ)
        _sync_integ()

        for _w, _t in (
            (self.cmb_os_test, "OpenSees convergence test used at every step."),
            (self.in_os_tol, "Tolerance passed to the convergence test."),
            (self.in_os_iter, "Maximum iterations per step."),
            (self.cmb_os_algo, "OpenSees solution algorithm."),
            (self.in_os_nip, "Number of Lobatto integration points along each fiber element (forceBeamColumn)."),
            (self.cmb_os_integ, "Lobatto: Gauss-Lobatto points over the whole element (plastic zone ~ end weight x L, very short). "
                                "HingeRadau: a physical hinge length Lp at each end, elastic-like interior."),
            (self.in_os_lp, "Plastic hinge length per end. 0 = automatic: Priestley k*L, plus 0.022*fy*db when the base-slip "
                            "spring is off. HingeRadau only."),
            (self.chk_os_slip, "Adds a Bond_SP01 zero-length section at column ends on supports (fixed-end rotation from bar slip). "
                               "Softens the initial stiffness; use with HingeRadau."),
            (self.chk_os_relax, "When a step still fails after halving the increment 4 times and trying other algorithms "
                                "(ModifiedNewton -initial, KrylovNewton, NewtonLineSearch, Broyden), the tolerance is relaxed in "
                                "steps of 100x up to the ceiling. Such steps are listed in the log and results as approximate. "
                                "Off = stop at the first step that cannot converge."),
            (self.in_os_relax, "Ceiling for the relaxed tolerance (NormDispIncr / EnergyIncr). Other tests relax by at most 1e4x."),
            (self.chk_os_safety, "Compares the vertical base reaction against its value at the start of the displacement-controlled "
                                 "case and stops the run if they differ by more than 0.1%."),
            (self.in_os_fsr, "Fiber mesh density. The section's largest dimension divided by this number is the target fiber size."),
        ):
            _w.setToolTip(_t)

        col.insertWidget(0, grp_os)
        col.insertWidget(1, grp_el)
        col.insertWidget(2, grp_ss)

        for g in native_groups:
            g.setEnabled(False)
            g.setToolTip("Native solver only - not used while the Analysis Engine is OpenSees.")

    def save_to_case(self):
        """Writes values back to the LoadCase object."""
        if self.opensees:
            blk = get_opensees_block(self.case)
            blk["test_type"] = self.cmb_os_test.currentText()
            try:
                _t = float(self.in_os_tol.text())
                if _t > 0.0: blk["tolerance"] = _t
            except ValueError: pass
            blk["max_iter"] = self.in_os_iter.value()
            blk["algorithm"] = self.cmb_os_algo.currentText()
            blk["relax_on_fail"] = self.chk_os_relax.isChecked()
            try:
                _rc = float(self.in_os_relax.text())
                if _rc > 0.0: blk["relax_ceiling"] = _rc
            except ValueError: pass
            blk["n_int_pts"] = self.in_os_nip.value()
            blk["fiber_size_ratio"] = self.in_os_fsr.value()
            blk["integration"] = self.cmb_os_integ.currentText()
            try:
                blk["hinge_length"] = max(0.0, unit_registry.from_display_length(float(self.in_os_lp.text())))
            except ValueError:
                pass
            blk["bar_slip"] = self.chk_os_slip.isChecked()
            blk["safety_check"] = self.chk_os_safety.isChecked()
            for _k, _e in self._slip_fields.items():
                try:
                    _v = float(_e.text())
                    if _v > 0.0: blk[_k] = _v
                except ValueError: pass
            blk["slip_concrete"] = ("stiff", "full", "scaled")[self.cmb_os_slipc.currentIndex()]
            if self.chk_os_shear.isChecked():
                try:
                    sp = {"k0": "auto", "Vy": "auto", "shear_stiffness": "cracked" if self.cmb_ss_stiff.currentIndex() == 0 else "uncracked",
                          "N": max(0.0, float(self.in_ss_N.text()) / self._force_factor)}
                    for _k, _e in self._ss_fields.items():
                        sp[_k] = float(_e.text())
                    blk["shear_spring"] = sp
                except ValueError:
                    pass                                                                                               
            else:
                blk["shear_spring"] = None
            self.case.opensees = blk
            return
        self.case.max_total_steps = self.in_total_steps.value()
        self.case.max_null_steps = self.in_null_steps.value()
        self.case.use_event_stepping = (self.cmb_event_stepping.currentText() == "Yes")
        try: self.case.event_lumping_tol = float(self.in_event_tol.text())
        except ValueError: pass
        self.case.max_events_per_step = self.in_max_events.value()
        self.case.use_iteration = (self.cmb_iteration.currentText() == "Yes")
        self.case.max_const_stiff_iter = self.in_const_iter.value()
        self.case.max_nr_iter = self.in_nr_iter.value()
        
        try: self.case.iter_conv_tol = float(self.in_conv_tol.text())
        except ValueError: pass
        
        self.case.use_line_search = (self.cmb_line_search.currentText() == "Yes")
        self.case.use_fd_tangent = (self.cmb_fd_tangent.currentText() == "Finite Difference")                
        
        self.case.hinge_snap = (self.cmb_hinge_snap.currentText() == "Yes")
        self.case.stop_on_fiber_failure = (self.cmb_stop_fiber.currentText() == "Yes")
        self.case.hinge_snap_scope = "all" if self.cmb_snap_scope.currentText() == "All Fibers" else "tension"
        try:
            _rf = float(self.in_res_floor.text())
            if 0.0 <= _rf <= 1e-3: self.case.residual_stiffness = _rf
        except ValueError: pass

        try:
            _ms = float(self.in_min_step.text())
            if 0.0 < _ms <= 1.0: self.case.min_step_frac = _ms
        except ValueError: pass
        self.case.max_event_probes = self.in_max_probes.value()
        self.case.auto_cutback = (self.cmb_cutback.currentText() == "Yes")
        self.case.max_step_attempts = self.in_max_attempts.value()

        self.case.tf_max_iter = self.in_tf_iter.value()
        try: self.case.tf_conv_tol = float(self.in_tf_tol.text())
        except ValueError: pass
        try: self.case.tf_accel_factor = float(self.in_tf_accel.text())
        except ValueError: pass
        
        self.case.continue_if_no_converge = (self.cmb_continue.currentText() == "Yes")

class ResultsSavedDialog(QDialog):
    """Sub-dialog for Nonlinear Static 'Results Saved' options (Final State
    Only vs. Multiple States, per-stage saved-state count, and the
    positive-increment filter)."""
    def __init__(self, case, parent=None):
        super().__init__(parent)
        self.case = case
        self.setWindowTitle("Results Saved for Nonlinear Static Load Cases")
        _fit_to_screen(self, 420, 340)
        apply_dialog_style(self)

        outer, layout = _scroll_layouts(self)

        grp_saved = QGroupBox("Results Saved")
        v_saved = QVBoxLayout(grp_saved)
        self.radio_final_only = QRadioButton("Final State Only")
        self.radio_multiple = QRadioButton("Multiple States")
        v_saved.addWidget(self.radio_final_only)
        v_saved.addWidget(self.radio_multiple)
        layout.addWidget(grp_saved)

        current_mode = getattr(self.case, 'results_saved', "Final State Only")
        if current_mode == "Multiple States":
            self.radio_multiple.setChecked(True)
        else:
            self.radio_final_only.setChecked(True)

        self.group_stage = QGroupBox("For Each Stage")
        form_stage = QFormLayout(self.group_stage)
        self.in_min_saved = QSpinBox(); self.in_min_saved.setRange(1, 99999)
        self.in_min_saved.setValue(getattr(self.case, 'min_saved_states', 1))
        self.in_max_saved = QSpinBox(); self.in_max_saved.setRange(1, 99999)
        _mx = int(getattr(self.case, 'max_saved_states', 100) or 0)
        self.in_max_saved.setValue(_mx if _mx > 0 else 100)
        self.btn_all_steps = QPushButton("All Steps")
        self.btn_all_steps.setCheckable(True)
        self.btn_all_steps.setChecked(_mx <= 0)
        self.btn_all_steps.setToolTip(
            "Keep every converged step - no limit on the number of saved states. "
            "Works the same for the native and OpenSees solvers. Many steps on a large "
            "model use a lot of memory and disk.")
        h_max = QHBoxLayout()
        h_max.addWidget(self.in_max_saved, 1)
        h_max.addWidget(self.btn_all_steps)
        form_stage.addRow("Minimum Number of Saved States", self.in_min_saved)
        form_stage.addRow("Maximum Number of Saved States", h_max)
        layout.addWidget(self.group_stage)

        self.chk_positive_only = QCheckBox("Save positive Displacement Increments Only")
        self.chk_positive_only.setChecked(getattr(self.case, 'save_positive_disp_only', False))
        self.chk_positive_only.setToolTip(
            "Not yet implemented by the solver - the setting is saved with "
            "the case but currently has no effect on which states get kept."
        )
        layout.addWidget(self.chk_positive_only)

        self.radio_final_only.toggled.connect(self._update_stage_state)
        self.radio_multiple.toggled.connect(self._update_stage_state)
        self.btn_all_steps.toggled.connect(self._update_stage_state)
        for _w, _t in (
            (self.radio_final_only, "Keeps only the final state."),
            (self.radio_multiple, "Keeps the converged state of each step, for pushover curves and step-by-step results."),
            (self.in_min_saved, "Not wired."),
            (self.in_max_saved, "Maximum states kept per stage. Extra states are dropped evenly."),
        ):
            _w.setToolTip(_t)

        self._update_stage_state()

        h_btns = QHBoxLayout()
        h_btns.addStretch()
        btn_ok = QPushButton("OK")
        btn_ok.setObjectName("primary")
        btn_ok.clicked.connect(self.accept)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        h_btns.addWidget(btn_ok)
        h_btns.addWidget(btn_cancel)
        outer.addLayout(h_btns)

    def _update_stage_state(self):
        enabled = self.radio_multiple.isChecked()
        self.group_stage.setEnabled(enabled)
        self.chk_positive_only.setEnabled(enabled)
        all_on = self.btn_all_steps.isChecked()
        self.in_max_saved.setEnabled(not all_on)
        self.in_min_saved.setEnabled(not all_on)

    def save_to_case(self):
        """Writes values back to the LoadCase object."""
        self.case.results_saved = "Multiple States" if self.radio_multiple.isChecked() else "Final State Only"
        self.case.min_saved_states = self.in_min_saved.value()
        self.case.max_saved_states = 0 if self.btn_all_steps.isChecked() else self.in_max_saved.value()
        self.case.save_positive_disp_only = self.chk_positive_only.isChecked()

class LoadApplicationControlDialog(QDialog):
    """Sub-dialog for Nonlinear Static 'Load Application Control' -
    Full Load (proportional load control, the existing solver behavior)
    vs. Displacement Control (Batoz & Dhatt monitored-DOF partitioning -
    see nl_chaining_and_disp_control.solve_displacement_control_iteration
    for the math this drives)."""
    def __init__(self, model, case, parent=None):
        super().__init__(parent)
        self.model = model
        self.case = case
        self.opensees = is_opensees(model)
        self.setWindowTitle("Load Application Control for Nonlinear Static Analysis")
        if self.opensees:
            _fit_to_screen(self, 560, 820)
        else:
            _fit_to_screen(self, 520, 700)
        apply_dialog_style(self)

        outer, layout = _scroll_layouts(self)

        grp_ctrl = QGroupBox("Load Application Control")
        v_ctrl = QVBoxLayout(grp_ctrl)
        self.radio_full = QRadioButton("Full Load")
        self.radio_disp = QRadioButton("Displacement Control")
        v_ctrl.addWidget(self.radio_full)
        v_ctrl.addWidget(self.radio_disp)
        layout.addWidget(grp_ctrl)

        self.grp_monitor = QGroupBox("Monitored Displacement")
        form_mon = QFormLayout(self.grp_monitor)

        h_dof = QHBoxLayout()
        h_dof.addWidget(QLabel("DOF:"))
        self.combo_dof = QComboBox()
        self.combo_dof.addItems(["U1", "U2", "U3", "R1", "R2", "R3"])
        self.combo_dof.setCurrentText(getattr(case, 'disp_control_dof', 'U1'))
        h_dof.addWidget(self.combo_dof)
        h_dof.addSpacing(12)
        h_dof.addWidget(QLabel("at Joint:"))
        self.spin_joint = QSpinBox()
        self.spin_joint.setRange(1, 999999)
        self.spin_joint.setValue(int(getattr(case, 'disp_control_node_id', 0) or 1))
        h_dof.addWidget(self.spin_joint)
        form_mon.addRow(h_dof)

        self.input_magnitude = QLineEdit(f"{unit_registry.to_display_length(getattr(case, 'disp_control_magnitude', 0.1)):.6g}")
        form_mon.addRow(f"Load to a Monitored Displacement Magnitude of "
                        f"({unit_registry.length_unit_name}):", self.input_magnitude)

        self.input_dc_tol = QLineEdit(f"{getattr(case, 'disp_control_tol', 1e-6):.2E}")
        form_mon.addRow("Displacement Control Tolerance:", self.input_dc_tol)

        self.chk_conjugate = QCheckBox("Use Conjugate Displacement (generalized control)")
        self.chk_conjugate.setChecked(False)
        self.chk_conjugate.setEnabled(False)
        self.chk_conjugate.setToolTip(
            "Not yet implemented by the solver - only single monitored-DOF "
            "control (Batoz & Dhatt partitioning) is available. This "
            "setting is saved with the case but currently has no effect."
        )
        form_mon.addRow(self.chk_conjugate)

        layout.addWidget(self.grp_monitor)

        if self.opensees:
            self._build_opensees_path(layout)
        else:
            self._build_native_path(layout)

        current = getattr(case, 'load_application', 'Full Load')
        if current == "Displacement Control":
            self.radio_disp.setChecked(True)
        else:
            self.radio_full.setChecked(True)
        self.radio_full.toggled.connect(self._update_state)
        self.radio_disp.toggled.connect(self._update_state)
        for _w, _t in (
            (self.radio_full, "Proportional load control."),
            (self.radio_disp, "Controls the displacement of one monitored DOF; the load follows."),
            (self.combo_dof, "Monitored degree of freedom."),
            (self.spin_joint, "Joint whose displacement is controlled."),
            (self.input_magnitude, "Final value of the monitored displacement. The sign sets the direction."),
            (self.input_dc_tol, "Absolute displacement tolerance, in model length units. Applied together with the relative convergence tolerance."),
        ):
            _w.setToolTip(_t)

        self._update_state()

        h_btns = QHBoxLayout()
        h_btns.addStretch()
        btn_ok = QPushButton("OK")
        btn_ok.setObjectName("primary")
        btn_ok.clicked.connect(self.accept)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        h_btns.addWidget(btn_ok)
        h_btns.addWidget(btn_cancel)
        outer.addLayout(h_btns)

    def _build_native_path(self, layout):
        """Native solver: optional displacement history (cyclic path). Off by default -
        'Single Target' keeps the classic monotonic behaviour. The table is stored in the
        same case block the OpenSees engine uses, so one protocol can be run on both engines."""
        blk = get_opensees_block(self.case)
        unit = unit_registry.length_unit_name

        self.grp_nat_path = QGroupBox("Displacement Path")
        v = QVBoxLayout(self.grp_nat_path)
        form = QFormLayout()
        self.cmb_path = QComboBox(); self.cmb_path.addItems(["Single Target", "History Table"])
        self.cmb_path.setCurrentText(str(blk["path_mode"]))
        form.addRow("Displacement Path:", self.cmb_path)
        v.addLayout(form)

        self.tbl_history = QTableWidget(0, 1)
        self.tbl_history.setHorizontalHeaderLabels([f"Target Displacement ({unit})"])
        self.tbl_history.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tbl_history.setMinimumHeight(180)
        for val in blk["disp_history"]:
            self._add_history_row(unit_registry.to_display_length(val))
        v.addWidget(self.tbl_history)

        h = QHBoxLayout()
        h.addStretch()
        self.btn_hist_gen = QPushButton("Generate...")
        self.btn_hist_gen.clicked.connect(self._generate_history)
        self.btn_hist_paste = QPushButton("Paste")
        self.btn_hist_paste.clicked.connect(self._paste_history)
        self.btn_hist_add = QPushButton("Add")
        self.btn_hist_add.clicked.connect(lambda: self._add_history_row(""))
        self.btn_hist_del = QPushButton("Delete")
        self.btn_hist_del.setObjectName("danger")
        self.btn_hist_del.clicked.connect(self._delete_history_row)
        for _b in (self.btn_hist_gen, self.btn_hist_paste, self.btn_hist_add, self.btn_hist_del):
            h.addWidget(_b)
        v.addLayout(h)
        layout.addWidget(self.grp_nat_path)

        for _w, _t in (
            (self.cmb_path, "Single Target: one monitored-displacement magnitude (above). History Table: a "
                            "sequence of targets, e.g. a cyclic protocol. For reversals to matter, the model "
                            "needs fiber hinges with Takeda hysteresis, Hinge Snap = No and P-Delta; set "
                            "Results Saved to Multiple States to get the loop. 'Total Load Steps' counts steps "
                            "over the whole path."),
            (self.tbl_history, "Each row is the next target of the monitored displacement, reached from the "
                               "previous row (the first row from zero). Absolute values, not increments."),
            (self.btn_hist_paste, "Replace the table with numbers copied from a spreadsheet or text "
                                  "(separated by new lines, tabs, commas or spaces)."),
        ):
            _w.setToolTip(_t)
        self.cmb_path.currentTextChanged.connect(lambda _t: self._update_state())

    def _native_inputs_ok(self):
        if not self.radio_disp.isChecked() or self.cmb_path.currentText() != "History Table":
            return True
        hist = self._collect_history()
        if hist is None:
            QMessageBox.warning(self, "History Table", "The history table contains a value that is not a number.")
            return False
        if not any(abs(x) > 0.0 for x in hist):
            QMessageBox.warning(self, "History Table", "Add at least one non-zero target displacement.")
            return False
        return True

    def _save_native_path(self):
        blk = get_opensees_block(self.case)
        blk["path_mode"] = self.cmb_path.currentText()
        hist = self._collect_history()
        if hist is not None:
            blk["disp_history"] = [round(unit_registry.from_display_length(v), 12) for v in hist]
        self.case.opensees = blk

    def _build_opensees_path(self, layout):
        """OpenSees-only: displacement path (single target or a history table) and step size."""
        blk = get_opensees_block(self.case)
        unit = unit_registry.length_unit_name

        self.grp_os_path = QGroupBox("OpenSees Displacement Path")
        v = QVBoxLayout(self.grp_os_path)
        form = QFormLayout()
        self.cmb_path = QComboBox(); self.cmb_path.addItems(["Single Target", "History Table"])
        self.cmb_path.setCurrentText(str(blk["path_mode"]))
        self.input_step = QLineEdit(f"{unit_registry.to_display_length(float(blk['step_size'])):.6g}")
        form.addRow("Displacement Path:", self.cmb_path)
        form.addRow(f"Step Size ({unit}):", self.input_step)
        v.addLayout(form)

        self.tbl_history = QTableWidget(0, 1)
        self.tbl_history.setHorizontalHeaderLabels([f"Target Displacement ({unit})"])
        self.tbl_history.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tbl_history.setMinimumHeight(220)
        for val in blk["disp_history"]:
            self._add_history_row(unit_registry.to_display_length(val))
        v.addWidget(self.tbl_history)

        h = QHBoxLayout()
        h.addStretch()
        self.btn_hist_paste = QPushButton("Paste")
        self.btn_hist_paste.clicked.connect(self._paste_history)
        self.btn_hist_add = QPushButton("Add")
        self.btn_hist_add.clicked.connect(lambda: self._add_history_row(""))
        self.btn_hist_del = QPushButton("Delete")
        self.btn_hist_del.setObjectName("danger")
        self.btn_hist_del.clicked.connect(self._delete_history_row)
        self.btn_hist_gen = QPushButton("Generate...")
        self.btn_hist_gen.clicked.connect(self._generate_history)
        h.addWidget(self.btn_hist_gen)
        h.addWidget(self.btn_hist_paste)
        h.addWidget(self.btn_hist_add)
        h.addWidget(self.btn_hist_del)
        v.addLayout(h)
        layout.addWidget(self.grp_os_path)
        self._build_opensees_load_control(layout, blk)

        for _w, _t in (
            (self.cmb_path, "Single Target: one monitored-displacement magnitude (above). "
                            "History Table: a sequence of targets, e.g. a cyclic protocol."),
            (self.input_step, "Displacement increment per step."),
            (self.tbl_history, "Each row is the next target of the monitored displacement, "
                               "reached from the previous row (the first row from zero). "
                               "Absolute values, not increments."),
            (self.btn_hist_paste, "Replace the table with numbers copied from a spreadsheet or text "
                                  "(separated by new lines, tabs, commas or spaces)."),
        ):
            _w.setToolTip(_t)

        self.cmb_path.currentTextChanged.connect(lambda _t: self._update_state())

    def _build_opensees_load_control(self, layout, blk):
        """OpenSees-only: step count and optional cyclic load-factor path for LOAD-controlled (Full Load) cases."""
        self.grp_os_load = QGroupBox("OpenSees Load Control")
        f = QFormLayout(self.grp_os_load)
        self.spin_load_steps = QSpinBox(); self.spin_load_steps.setRange(1, 100000)
        self.spin_load_steps.setValue(int(blk.get("load_steps", 10)))
        self.spin_load_steps.setToolTip("Increments per unit load factor (1.0 = full load). 10 = the old fixed behaviour.")
        self.cmb_load_path = QComboBox(); self.cmb_load_path.addItems(["Monotonic", "History Table"])
        self.cmb_load_path.setCurrentText(str(blk.get("load_path_mode", "Monotonic")))
        self.cmb_load_path.setToolTip("Monotonic: 0 -> 1.0.  History Table: a sequence of load-factor targets, e.g. a "
                                      "force-controlled cyclic protocol (1.0 = the case's full load; negative reverses it).")
        self.edit_load_hist = QLineEdit(", ".join(f"{v:g}" for v in blk.get("load_history", [])))
        self.edit_load_hist.setToolTip("Absolute load-factor targets separated by commas, e.g. 0.5, -0.5, 1, -1, 0")
        self.btn_load_gen = QPushButton("Generate...")
        self.btn_load_gen.clicked.connect(self._generate_load_history)
        row = QHBoxLayout(); row.addWidget(self.edit_load_hist); row.addWidget(self.btn_load_gen)
        f.addRow("Steps per unit load factor:", self.spin_load_steps)
        f.addRow("Load Path:", self.cmb_load_path)
        f.addRow("Load-factor targets:", row)
        layout.addWidget(self.grp_os_load)
        self.cmb_load_path.currentTextChanged.connect(lambda _t: self._update_state())

    def _generate_history(self):
        dlg = ProtocolGeneratorDialog(self, unit_name=unit_registry.length_unit_name,
                                      title="Generate Displacement History")
        if not dlg.exec():
            return
        self.tbl_history.setRowCount(0)
        for v in dlg.values:
            self._add_history_row(v)
        self.cmb_path.setCurrentText("History Table")

    def _generate_load_history(self):
        dlg = ProtocolGeneratorDialog(self, unit_name="", title="Generate Load-Factor History")
        if not dlg.exec():
            return
        self.edit_load_hist.setText(", ".join(f"{v:g}" for v in dlg.values))
        self.cmb_load_path.setCurrentText("History Table")

    def _collect_load_history(self):
        import re
        try:
            return [float(t) for t in re.split(r"[\s,;]+", self.edit_load_hist.text().strip()) if t]
        except ValueError:
            return None

    def _add_history_row(self, val=""):
        r = self.tbl_history.rowCount()
        self.tbl_history.insertRow(r)
        self.tbl_history.setItem(r, 0, QTableWidgetItem("" if val == "" else f"{float(val):.10g}"))
        self.tbl_history.setCurrentCell(r, 0)

    def _delete_history_row(self):
        """Delete every selected row (Ctrl+A selects all); falls back to the current row."""
        rows = sorted({i.row() for i in self.tbl_history.selectedIndexes()}, reverse=True)
        if not rows:
            r = self.tbl_history.currentRow()
            if r < 0:
                return
            rows = [r]
        if len(rows) == self.tbl_history.rowCount():
            self.tbl_history.setRowCount(0)
            return
        for r in rows:
            self.tbl_history.removeRow(r)

    def _paste_history(self):
        import re
        text = QApplication.clipboard().text()
        vals = []
        for tok in re.split(r"[\s,;]+", text.strip()):
            if not tok:
                continue
            try:
                vals.append(float(tok))
            except ValueError:
                QMessageBox.warning(self, "Paste", f"'{tok}' is not a number. Nothing was pasted.")
                return
        if not vals:
            return
        self.tbl_history.setRowCount(0)
        for v in vals:
            self._add_history_row(v)

    def _collect_history(self):
        """List of target displacements from the table, or None if a cell isn't a number."""
        vals = []
        for r in range(self.tbl_history.rowCount()):
            it = self.tbl_history.item(r, 0)
            txt = it.text().strip() if it else ""
            if not txt:
                continue
            try:
                vals.append(float(txt))
            except ValueError:
                return None
        return vals

    def _opensees_inputs_ok(self):
        if not self.radio_disp.isChecked():
            if self.cmb_load_path.currentText() == "History Table":
                lh = self._collect_load_history()
                if lh is None or not lh:
                    QMessageBox.warning(self, "Load Path", "Enter at least one load-factor target (numbers separated by commas).")
                    return False
            return True
        try:
            if float(self.input_step.text()) <= 0.0:
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, "Step Size", "Step size must be a positive number.")
            return False
        if self.cmb_path.currentText() == "History Table":
            hist = self._collect_history()
            if hist is None:
                QMessageBox.warning(self, "History Table", "The history table contains a value that is not a number.")
                return False
            if not hist:
                QMessageBox.warning(self, "History Table", "Add at least one target displacement to the history table.")
                return False
        return True

    def accept(self):
        if self.opensees and not self._opensees_inputs_ok():
            return
        if not self.opensees and not self._native_inputs_ok():
            return
        super().accept()

    def _save_opensees_path(self):
        blk = get_opensees_block(self.case)
        blk["path_mode"] = self.cmb_path.currentText()
        try:
            _s = float(self.input_step.text())
            if _s > 0.0: blk["step_size"] = unit_registry.from_display_length(_s)
        except ValueError: pass
        hist = self._collect_history()
        if hist is not None:
            blk["disp_history"] = [round(unit_registry.from_display_length(v), 12) for v in hist]
        blk["load_steps"] = int(self.spin_load_steps.value())
        blk["load_path_mode"] = self.cmb_load_path.currentText()
        lh = self._collect_load_history()
        if lh is not None:
            blk["load_history"] = lh
        self.case.opensees = blk

    def _update_state(self):
        disp = self.radio_disp.isChecked()
        self.grp_monitor.setEnabled(disp)
        if self.opensees:
            history = self.cmb_path.currentText() == "History Table"
            self.grp_os_path.setEnabled(disp)
            self.tbl_history.setEnabled(disp and history)
            self.btn_hist_paste.setEnabled(disp and history)
            self.btn_hist_add.setEnabled(disp and history)
            self.btn_hist_del.setEnabled(disp and history)
            self.input_magnitude.setEnabled(not history)
            self.btn_hist_gen.setEnabled(disp and history)
            self.grp_os_load.setEnabled(not disp)
            _lh = self.cmb_load_path.currentText() == "History Table"
            self.edit_load_hist.setEnabled(not disp and _lh)
            self.btn_load_gen.setEnabled(not disp)
            self.input_dc_tol.setEnabled(False)
            self.input_dc_tol.setToolTip("Native solver only - not used while the Analysis Engine is OpenSees.")
        else:
            history = self.cmb_path.currentText() == "History Table"
            self.grp_nat_path.setEnabled(disp)
            for _w in (self.tbl_history, self.btn_hist_gen, self.btn_hist_paste,
                       self.btn_hist_add, self.btn_hist_del):
                _w.setEnabled(disp and history)
            self.input_magnitude.setEnabled(disp and not history)

    def save_to_case(self):
        self.case.load_application = "Displacement Control" if self.radio_disp.isChecked() else "Full Load"
        self.case.disp_control_dof = self.combo_dof.currentText()
        self.case.disp_control_node_id = self.spin_joint.value()
        try:
            self.case.disp_control_magnitude = unit_registry.from_display_length(float(self.input_magnitude.text()))
        except ValueError:
            self.case.disp_control_magnitude = 0.1
        if self.opensees:
            self._save_opensees_path()
        else:
            self._save_native_path()
            try:
                _t = float(self.input_dc_tol.text())
                if _t > 0.0: self.case.disp_control_tol = _t
            except ValueError: pass

class LoadCaseDetailDialog(QDialog):
    """The 'Modify/Show' window for a single load case."""
    def __init__(self, model, case, parent=None, is_new=False):
        super().__init__(parent)
        self.model = model

        self.opensees = is_opensees(model)

        if isinstance(case, dict):
            from core.model import LoadCase
            name  = case.get("name", "Unknown")
            c_type = case.get("type", "Linear Static")
            real_case = LoadCase(name, c_type)
            if c_type == "Response Spectrum":
                func      = case.get("function", "FUNC1")
                direction = case.get("direction", "X")
                dir_map   = {"X": "U1", "Y": "U2", "Z": "U3"}
                u_dir     = dir_map.get(direction, "U1")
                real_case.rsa_loads = [(u_dir, func, 9.81)]
            self.case = real_case
        else:
            self.case = case

        self.original_name = self.case.name
        self.is_new        = is_new

        self.setWindowTitle("Load Case Data - " + self.case.case_type)
        _fit_to_screen(self, 760, 720)

        apply_dialog_style(self)                                                

        outer, layout = _scroll_layouts(self)

        grp_top = QGroupBox("General")
        h_top   = QHBoxLayout(grp_top)

        h_top.addWidget(QLabel("Load Case Name:"))
        self.input_name = QLineEdit(self.case.name)
                                                                                          
        self.input_name.setStyleSheet("font-weight: bold; font-size: 11pt;")
        h_top.addWidget(self.input_name)

        h_top.addSpacing(20)

        h_top.addWidget(QLabel("Load Case Type:"))
        self.combo_type = QComboBox()
        self.combo_type.addItems(["Linear Static", "Nonlinear Static", "Modal", "Response Spectrum", "LTHA", "Buckling"])
        self.combo_type.setCurrentText(self.case.case_type)
        self.combo_type.currentTextChanged.connect(self.on_type_changed)
        h_top.addWidget(self.combo_type)

        layout.addWidget(grp_top)

        self.grp_stiffness = QGroupBox("Stiffness to Use")
        v_stiff = QVBoxLayout(self.grp_stiffness)
        self.radio_zero     = QRadioButton("Zero Initial Conditions - Unstressed State")
        self.radio_continue = QRadioButton("Stiffness at End of Nonlinear Case")
        v_stiff.addWidget(self.radio_zero)
        v_stiff.addWidget(self.radio_continue)

        h_continue = QHBoxLayout()
        h_continue.addSpacing(20)
        h_continue.addWidget(QLabel("Load Case:"))
        self.combo_continue_case = QComboBox()
        prior_nl_cases = [c.name for c in self.model.load_cases.values()
                          if getattr(c, 'case_type', '') == "Nonlinear Static"
                          and c.name != self.original_name] if hasattr(self.model, 'load_cases') else []
        if prior_nl_cases:
            self.combo_continue_case.addItems(prior_nl_cases)
            self.radio_continue.setEnabled(True)
        else:
            self.combo_continue_case.addItem("(no other Nonlinear Static case defined)")
            self.radio_continue.setEnabled(False)
            self.radio_continue.setToolTip(
                "Define another Nonlinear Static load case first, then this "
                "case can continue from its final state."
            )
        self.combo_continue_case.setEnabled(False)
        h_continue.addWidget(self.combo_continue_case)
        v_stiff.addLayout(h_continue)

        existing_continue = getattr(self.case, 'continue_from_case', None)
        if existing_continue and existing_continue in prior_nl_cases:
            self.radio_continue.setChecked(True)
            self.combo_continue_case.setCurrentText(existing_continue)
            self.combo_continue_case.setEnabled(True)
        else:
            self.radio_zero.setChecked(True)

        self.radio_continue.toggled.connect(
            lambda checked: self.combo_continue_case.setEnabled(checked and self.radio_continue.isEnabled())
        )

        layout.addWidget(self.grp_stiffness)

        self.group_loads = QGroupBox("Loads Applied")
        v_loads = QVBoxLayout(self.group_loads)

        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Load Pattern", "Scale Factor"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        v_loads.addWidget(self.table)

        h_tbl_btns = QHBoxLayout()
        self.btn_add_row = QPushButton("Add")
        self.btn_add_row.clicked.connect(self.add_load_row)
        self.btn_del_row = QPushButton("Delete")
        self.btn_del_row.setObjectName("danger")                             
        self.btn_del_row.clicked.connect(self.delete_load_row)
        h_tbl_btns.addStretch()
        h_tbl_btns.addWidget(self.btn_add_row)
        h_tbl_btns.addWidget(self.btn_del_row)
        v_loads.addLayout(h_tbl_btns)

        layout.addWidget(self.group_loads)

        self.group_modal = QGroupBox("Modal Analysis Parameters")
        h_modal_main = QHBoxLayout(self.group_modal)

        v_mod_left = QVBoxLayout()
        grp_method = QGroupBox("Type of Modes")
        v_method   = QVBoxLayout(grp_method)
        self.radio_eigen = QRadioButton("Eigen Vectors")
        self.radio_ritz  = QRadioButton("Ritz Vectors")
        self.radio_eigen.setChecked(True)
        v_method.addWidget(self.radio_eigen)
        v_method.addWidget(self.radio_ritz)
        v_mod_left.addWidget(grp_method)

        grp_nl = QGroupBox("Nonlinear Behavior")
        v_nl = QVBoxLayout(grp_nl)
        self.chk_modal_hinges = QCheckBox("Include fiber hinge stiffness")
        self.chk_modal_hinges.setChecked(bool(getattr(self.case, 'modal_fiber_hinges', False)))
        self.chk_modal_hinges.setToolTip(
            "Uses the unstressed (initial tangent) stiffness of the fibers over each hinge length "
            "instead of the plain elastic section. \n"
            "Models without fiber hinges are unaffected.")
        v_nl.addWidget(self.chk_modal_hinges)
        v_mod_left.addWidget(grp_nl)
        v_mod_left.addStretch()
        h_modal_main.addLayout(v_mod_left)

        v_mod_right = QVBoxLayout()
        grp_num = QGroupBox("Number of Modes")
        f_num   = QVBoxLayout(grp_num)
        h_max   = QHBoxLayout()
        h_max.addWidget(QLabel("Maximum Number of Modes:"))
        self.spin_max_modes = QSpinBox()
        self.spin_max_modes.setRange(1, 999)
        self.spin_max_modes.setValue(getattr(self.case, 'num_modes', 12))
        h_max.addWidget(self.spin_max_modes)
        f_num.addLayout(h_max)
        h_min = QHBoxLayout()
        h_min.addWidget(QLabel("Minimum Number of Modes:"))
        self.spin_min_modes = QSpinBox()
        self.spin_min_modes.setRange(1, 999)
        self.spin_min_modes.setValue(getattr(self.case, 'min_modes', 1))
        h_min.addWidget(self.spin_min_modes)
        f_num.addLayout(h_min)
        v_mod_right.addWidget(grp_num)

        grp_mass = QGroupBox("Mass Source")
        v_mass   = QVBoxLayout(grp_mass)
        self.combo_mass = QComboBox()
        if hasattr(self.model, 'mass_sources'):
            self.combo_mass.addItems(self.model.mass_sources.keys())
        else:
            self.combo_mass.addItem("MSSSRC1")
        self.combo_mass.setCurrentText(getattr(self.case, 'mass_source', 'MSSSRC1'))
        v_mass.addWidget(self.combo_mass)
        v_mod_right.addWidget(grp_mass)
        h_modal_main.addLayout(v_mod_right)
        layout.addWidget(self.group_modal)

        modal_cases = []
        if hasattr(self.model, 'load_cases'):
            for name, c_obj in self.model.load_cases.items():
                c_t = c_obj.get("type", "Linear Static") if isinstance(c_obj, dict) else getattr(c_obj, 'case_type', 'Linear Static')
                if c_t == "Modal":
                    modal_cases.append(name)
        if not modal_cases:
            modal_cases = ["MODAL"]                         

        self.group_rsa = QGroupBox("Response Spectrum Parameters")
        layout_rsa = QVBoxLayout(self.group_rsa)

        h_rsa_modal = QHBoxLayout()
        h_rsa_modal.addWidget(QLabel("Modal Case to Use:"))
        self.combo_modal_rsa = QComboBox()
        self.combo_modal_rsa.addItems(modal_cases)
        if hasattr(self.case, 'modal_case') and self.case.modal_case:
            self.combo_modal_rsa.setCurrentText(self.case.modal_case)
        h_rsa_modal.addWidget(self.combo_modal_rsa)
        h_rsa_modal.addStretch()
        layout_rsa.addLayout(h_rsa_modal)

        h_rsa_top = QHBoxLayout()

        grp_comb = QGroupBox("Modal Combination")
        v_comb   = QVBoxLayout(grp_comb)
        self.radio_cqc  = QRadioButton("CQC")
        self.radio_srss = QRadioButton("SRSS")
        self.radio_cqc.setChecked(True)
        v_comb.addWidget(self.radio_cqc)
        v_comb.addWidget(self.radio_srss)
        h_rsa_top.addWidget(grp_comb)

        grp_dir = QGroupBox("Directional Combination")
        v_dir   = QVBoxLayout(grp_dir)
        self.radio_dir_srss = QRadioButton("SRSS")
        self.radio_dir_abs  = QRadioButton("Absolute")
        self.radio_dir_srss.setChecked(True)
        v_dir.addWidget(self.radio_dir_srss)
        v_dir.addWidget(self.radio_dir_abs)
        h_rsa_top.addWidget(grp_dir)
        layout_rsa.addLayout(h_rsa_top)

        grp_rsa_loads = QGroupBox("Loads Applied")
        v_rsa_loads   = QVBoxLayout(grp_rsa_loads)

        self.table_rsa = QTableWidget()
        self.table_rsa.setColumnCount(3)
        self.table_rsa.setHorizontalHeaderLabels(["Load Name", "Function", f"Scale Factor ({unit_registry.acceleration_unit})"])
        self.table_rsa.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        v_rsa_loads.addWidget(self.table_rsa)

        h_rsa_btns = QHBoxLayout()
        self.btn_rsa_preview = QPushButton("Preview Spectrum")
        self.btn_rsa_preview.clicked.connect(self.preview_spectrum)
        self.btn_rsa_add = QPushButton("Add")
        self.btn_rsa_add.clicked.connect(self.add_rsa_row)
        self.btn_rsa_del = QPushButton("Delete")
        self.btn_rsa_del.setObjectName("danger")                      
        self.btn_rsa_del.clicked.connect(self.delete_rsa_row)
        h_rsa_btns.addWidget(self.btn_rsa_preview)
        h_rsa_btns.addStretch()
        h_rsa_btns.addWidget(self.btn_rsa_add)
        h_rsa_btns.addWidget(self.btn_rsa_del)
        v_rsa_loads.addLayout(h_rsa_btns)

        layout_rsa.addWidget(grp_rsa_loads)
        layout.addWidget(self.group_rsa)

        self.group_buckling = QGroupBox("Buckling Parameters")
        v_buck = QVBoxLayout(self.group_buckling)

        h_buck_modes = QHBoxLayout()
        h_buck_modes.addWidget(QLabel("Number of Buckling Modes:"))
        self.spin_buck_modes = QSpinBox()
        self.spin_buck_modes.setRange(1, 999)
        self.spin_buck_modes.setValue(getattr(self.case, 'num_modes', 6))
        h_buck_modes.addWidget(self.spin_buck_modes)
        h_buck_modes.addStretch()
        v_buck.addLayout(h_buck_modes)

        h_buck_tol = QHBoxLayout()
        h_buck_tol.addWidget(QLabel("Eigenvalue Convergence Tolerance:"))
        tol_val = getattr(self.case, 'eigen_tol', 1e-9)
        self.input_buck_tol = QLineEdit(f"{tol_val:.3E}")
        self.input_buck_tol.setFixedWidth(100)
        h_buck_tol.addWidget(self.input_buck_tol)
        h_buck_tol.addStretch()
        v_buck.addLayout(h_buck_tol)

        h_buck_mass = QHBoxLayout()
        h_buck_mass.addWidget(QLabel("Mass Source:"))
        self.combo_buck_mass = QComboBox()
        if hasattr(self.model, 'mass_sources') and self.model.mass_sources:
            self.combo_buck_mass.addItems(self.model.mass_sources.keys())
        else:
            self.combo_buck_mass.addItem("MSSSRC1")
        self.combo_buck_mass.setCurrentText(getattr(self.case, 'mass_source', 'MSSSRC1'))
        h_buck_mass.addWidget(self.combo_buck_mass)
        h_buck_mass.addStretch()
        v_buck.addLayout(h_buck_mass)

        layout.addWidget(self.group_buckling)

        self.group_ltha = QGroupBox("Linear Time History Parameters")
        v_ltha = QVBoxLayout(self.group_ltha)

        h_ltha_modal = QHBoxLayout()
        h_ltha_modal.addWidget(QLabel("Modal Case to Use:"))
        self.combo_modal_ltha = QComboBox()
        self.combo_modal_ltha.addItems(modal_cases)
        if hasattr(self.case, 'modal_case') and self.case.modal_case:
            self.combo_modal_ltha.setCurrentText(self.case.modal_case)
        h_ltha_modal.addWidget(self.combo_modal_ltha)
        h_ltha_modal.addStretch()
        v_ltha.addLayout(h_ltha_modal)
                                             
        h_ltha_opts = QHBoxLayout()
        h_ltha_opts.addWidget(QLabel("Damping Ratio:"))
        self.input_ltha_damping = QLineEdit()
        self.input_ltha_damping.setText(str(getattr(self.case, 'damping', 0.05)))
        self.input_ltha_damping.setFixedWidth(70)
        h_ltha_opts.addWidget(self.input_ltha_damping)
        h_ltha_opts.addStretch()
        v_ltha.addLayout(h_ltha_opts)

        self.table_ltha = QTableWidget()
        self.table_ltha.setColumnCount(3)
        self.table_ltha.setHorizontalHeaderLabels(["Direction", "Function", f"Scale Factor ({unit_registry.acceleration_unit})"])
        self.table_ltha.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table_ltha.setMaximumHeight(160)
        v_ltha.addWidget(self.table_ltha)

        h_ltha_btns = QHBoxLayout()
        self.btn_ltha_add = QPushButton("Add")
        self.btn_ltha_add.clicked.connect(self.add_ltha_row)
        self.btn_ltha_del = QPushButton("Delete")
        self.btn_ltha_del.setObjectName("danger")                     
        self.btn_ltha_del.clicked.connect(self.delete_ltha_row)
        h_ltha_btns.addStretch()
        h_ltha_btns.addWidget(self.btn_ltha_add)
        h_ltha_btns.addWidget(self.btn_ltha_del)
        v_ltha.addLayout(h_ltha_btns)

        layout.addWidget(self.group_ltha)

        self.group_nonlinear = QGroupBox("Geometric Nonlinearity Parameters")
        v_geom = QVBoxLayout(self.group_nonlinear)
        self.radio_geom_none = QRadioButton("None")
        self.radio_geom_pdelta = QRadioButton("P-Delta")
        self.radio_geom_large = QRadioButton("P-Delta plus Large Displacements")

        self.radio_geom_large.setEnabled(True)
        self.radio_geom_large.setToolTip(
            "Beta: validated on isolated benchmark cases. Known gaps - member "
            "distributed loads (incl. self-weight) and rigid end-offsets are not "
            "yet included in the large-displacement force recovery. Test on a "
            "simple nodal-load-only model before trusting production results."
        )

        h_formulation = QHBoxLayout()
        h_formulation.setContentsMargins(20, 0, 0, 0)
        h_formulation.addWidget(QLabel("Select Formulation:"))
        self.combo_formulation = QComboBox()
        self.combo_formulation.addItems([
            "Corotational",
            "Updated Lagrangian"
        ])
        self.combo_formulation.setToolTip(
            "Corotational: fully implemented large-deflection solver.\n"
            "Updated Lagrangian: selection is saved with the load case; "
            "solver support is not yet implemented."
        )
        h_formulation.addWidget(self.combo_formulation)

        h_corot = QHBoxLayout()
        h_corot.setContentsMargins(20, 0, 0, 0)                     
        h_corot.addWidget(QLabel("Large Deflection Formulation:"))
        self.combo_corot_formulation = QComboBox()
        self.combo_corot_formulation.addItems([
            "Commercial Compatibility",
            "Strict Global Equilibrium (Native)"
        ])
        h_corot.addWidget(self.combo_corot_formulation)
        
        self.radio_geom_none.toggled.connect(self._update_corot_state)
        self.radio_geom_pdelta.toggled.connect(self._update_corot_state)
        self.radio_geom_large.toggled.connect(self._update_corot_state)
        self.combo_formulation.currentTextChanged.connect(self._update_corot_state)

        geom_val = getattr(self.case, 'geom_nonlin', 'None')
        if geom_val == "P-Delta": self.radio_geom_pdelta.setChecked(True)
        elif geom_val == "Large Displacements": self.radio_geom_large.setChecked(True)
        else: self.radio_geom_none.setChecked(True)
        
        current_corot = getattr(self.case, 'corot_type', "Commercial Compatibility")
        self.combo_corot_formulation.setCurrentText(current_corot)

        current_formulation = getattr(self.case, 'formulation', "Corotational")
        self.combo_formulation.setCurrentText(current_formulation)

        v_geom.addWidget(self.radio_geom_none)
        v_geom.addWidget(self.radio_geom_pdelta)
        v_geom.addWidget(self.radio_geom_large)
        v_geom.addLayout(h_formulation)
        v_geom.addLayout(h_corot)
        layout.addWidget(self.group_nonlinear)
        
        self._update_corot_state()

        self.group_other_params = QGroupBox("Other Parameters")
        form_other = QFormLayout(self.group_other_params)
        if self.opensees:
            _note = QLabel("Analysis Engine: OpenSees. Settings that only the native solver uses are disabled.")
            _note.setWordWrap(True)
            form_other.addRow(_note)
        
        btn_mod_load = QPushButton("Modify/Show...")
        btn_mod_load.clicked.connect(self.open_load_application)
        btn_mod_results = QPushButton("Modify/Show...")
        btn_mod_results.clicked.connect(self.open_results_saved)
        btn_mod_nl = QPushButton("Modify/Show...")
        btn_mod_nl.clicked.connect(self.open_nonlinear_params)

        self.lbl_row_load_app = QLabel()
        self._refresh_load_app_label()
        self.lbl_row_results = QLabel()
        self._refresh_results_saved_label()

        form_other.addRow(self.lbl_row_load_app, btn_mod_load)
        form_other.addRow(self.lbl_row_results, btn_mod_results)
        form_other.addRow("Nonlinear Parameters (OpenSees)" if self.opensees else "Nonlinear Parameters (Default)", btn_mod_nl)
        layout.addWidget(self.group_other_params)

        self.group_damping = QGroupBox("Damping Settings")
        v_damp = QVBoxLayout(self.group_damping)
        h_damp = QHBoxLayout()
        self.lbl_damp = QLabel("Constant Modal Damping:")
        self.input_damping = QLineEdit()
        self.input_damping.setText(str(getattr(self.case, 'modal_damping', 0.05)))
        self.input_damping.setPlaceholderText("e.g. 0.05")
        h_damp.addWidget(self.lbl_damp)
        h_damp.addWidget(self.input_damping)
        v_damp.addLayout(h_damp)
        layout.addWidget(self.group_damping)

        h_btns = QHBoxLayout()
        h_btns.addStretch()
        btn_ok = QPushButton("OK")
        btn_ok.setFixedWidth(100)
        btn_ok.setObjectName("primary")                              
        btn_ok.clicked.connect(self.on_ok)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setFixedWidth(100)
        btn_cancel.clicked.connect(self.reject)
        h_btns.addWidget(btn_ok)
        h_btns.addWidget(btn_cancel)
        outer.addLayout(h_btns)

        self.populate_loads()
        self.populate_rsa()
        self.populate_ltha()
        self.on_type_changed(self.combo_type.currentText())

        if hasattr(self.case, 'modal_type'):
            if self.case.modal_type == "Ritz": self.radio_ritz.setChecked(True)
            else: self.radio_eigen.setChecked(True)

        if hasattr(self.case, 'modal_comb'):
            if self.case.modal_comb == "CQC": self.radio_cqc.setChecked(True)
            else: self.radio_srss.setChecked(True)

        if hasattr(self.case, 'dir_comb'):
            if self.case.dir_comb == "Absolute": self.radio_dir_abs.setChecked(True)
            else: self.radio_dir_srss.setChecked(True)

    def _update_corot_state(self):
        """Enables the formulation dropdowns only if Large Displacements is selected.
        The Commercial/Native variant dropdown only applies to the Corotational
        formulation, so it's further gated on that selection."""
        if self.opensees:
            for _c in (self.combo_formulation, self.combo_corot_formulation):
                _c.setEnabled(False)
                _c.setToolTip("Native solver only - not used while the Analysis Engine is OpenSees.")
            return
        is_large = self.radio_geom_large.isChecked()
        self.combo_formulation.setEnabled(is_large)
        is_corot = (self.combo_formulation.currentText() == "Corotational")
        self.combo_corot_formulation.setEnabled(is_large and is_corot)

    def on_type_changed(self, text):
        is_modal     = (text == "Modal")
        is_nonlinear = (text == "Nonlinear Static")
        is_rsa       = (text == "Response Spectrum")
        is_ltha      = (text == "LTHA")
        is_buckling  = (text == "Buckling")

        self.group_loads.setVisible(not is_modal and not is_rsa and not is_ltha)
        self.group_modal.setVisible(is_modal)
        self.group_rsa.setVisible(is_rsa)
        self.group_ltha.setVisible(is_ltha)
        self.group_buckling.setVisible(is_buckling)
        self.grp_stiffness.setVisible(True)
        
        self.group_nonlinear.setVisible(is_nonlinear)
        self.group_other_params.setVisible(is_nonlinear)
        
        self.group_damping.setVisible(is_rsa)
        
        self.setWindowTitle("Load Case Data - " + text)

    def populate_loads(self):
        self.table.setRowCount(0)
        for pat, scale in self.case.loads:
            row = self.table.rowCount()
            self.table.insertRow(row)
            cmb = QComboBox()
            cmb.addItems(self.model.load_patterns.keys())
            cmb.setCurrentText(pat)
            self.table.setCellWidget(row, 0, cmb)
            self.table.setItem(row, 1, QTableWidgetItem(str(scale)))

    def add_load_row(self):
        row = self.table.rowCount()
        self.table.insertRow(row)
        cmb = QComboBox()
        cmb.addItems(self.model.load_patterns.keys())
        self.table.setCellWidget(row, 0, cmb)
        self.table.setItem(row, 1, QTableWidgetItem("1.0"))

    def delete_load_row(self):
        cr = self.table.currentRow()
        if cr >= 0: self.table.removeRow(cr)

    def add_ltha_row(self):
        if self.table_ltha.rowCount() >= 3:
            QMessageBox.information(self, "Limit Reached",
                                    "Maximum 3 ground motion functions (X, Y, Z).")
            return
        row = self.table_ltha.rowCount()
        self.table_ltha.insertRow(row)
        cmb_dir = QComboBox()
        cmb_dir.addItems(["X", "Y", "Z"])
        used = [self.table_ltha.cellWidget(r, 0).currentText()
                for r in range(row)
                if self.table_ltha.cellWidget(r, 0)]
        for d in ["X", "Y", "Z"]:
            if d not in used:
                cmb_dir.setCurrentText(d)
                break
        self.table_ltha.setCellWidget(row, 0, cmb_dir)
        cmb_func = QComboBox()
        th_funcs = getattr(self.model, 'th_functions', {})
        if th_funcs:
            cmb_func.addItems(th_funcs.keys())
        else:
            cmb_func.addItem("(No functions defined)")
        self.table_ltha.setCellWidget(row, 1, cmb_func)
        self.table_ltha.setItem(row, 2, QTableWidgetItem("1.0"))

    def delete_ltha_row(self):
        cr = self.table_ltha.currentRow()
        if cr >= 0: self.table_ltha.removeRow(cr)

    def populate_ltha(self):
        self.table_ltha.setRowCount(0)
        ltha_loads = getattr(self.case, 'ltha_loads', [])
        th_funcs   = getattr(self.model, 'th_functions', {})
        for direction, func_name, scale in ltha_loads:
            row = self.table_ltha.rowCount()
            self.table_ltha.insertRow(row)
            cmb_dir = QComboBox()
            cmb_dir.addItems(["X", "Y", "Z"])
            cmb_dir.setCurrentText(direction)
            self.table_ltha.setCellWidget(row, 0, cmb_dir)
            cmb_func = QComboBox()
            if th_funcs:
                cmb_func.addItems(th_funcs.keys())
            else:
                cmb_func.addItem("(No functions defined)")
            cmb_func.setCurrentText(func_name)
            self.table_ltha.setCellWidget(row, 1, cmb_func)
            
            display_scale = unit_registry.to_display_acceleration(scale)
            self.table_ltha.setItem(row, 2, QTableWidgetItem(f"{display_scale:.4f}"))

    def on_ok(self):
        new_name = self.input_name.text().strip()
        if not new_name:
            QMessageBox.warning(self, "Error", "Name cannot be empty.")
            return
        if new_name != self.original_name and new_name in self.model.load_cases:
            QMessageBox.warning(self, "Error",
                                f"Load Case '{new_name}' already exists.\nPlease choose a unique name.")
            return
        if self.combo_type.currentText() == "Response Spectrum":
            if not self.validate_rsa_loads():
                return
        self.accept()

    def get_data(self):
        c = LoadCase(self.input_name.text().strip(), self.combo_type.currentText())
        
        if hasattr(self, 'radio_geom_large') and self.radio_geom_large.isChecked():
            c.geom_nonlin = "Large Displacements"
        elif hasattr(self, 'radio_geom_pdelta') and self.radio_geom_pdelta.isChecked():
            c.geom_nonlin = "P-Delta"
        else:
            c.geom_nonlin = "None"
        
        c.max_total_steps = getattr(self.case, 'max_total_steps', 200)
        c.max_null_steps = getattr(self.case, 'max_null_steps', 50)
        c.use_event_stepping = getattr(self.case, 'use_event_stepping', True)
        c.event_lumping_tol = getattr(self.case, 'event_lumping_tol', 0.01)
        c.max_events_per_step = getattr(self.case, 'max_events_per_step', 24)
        c.use_iteration = getattr(self.case, 'use_iteration', True)
        c.max_const_stiff_iter = getattr(self.case, 'max_const_stiff_iter', 10)
        c.max_nr_iter = getattr(self.case, 'max_nr_iter', 40)
        c.iter_conv_tol = getattr(self.case, 'iter_conv_tol', 1e-4)
        c.use_line_search = getattr(self.case, 'use_line_search', False)
        c.tf_max_iter = getattr(self.case, 'tf_max_iter', 10)
        c.tf_conv_tol = getattr(self.case, 'tf_conv_tol', 0.01)
        c.tf_accel_factor = getattr(self.case, 'tf_accel_factor', 1.0)
        c.continue_if_no_converge = getattr(self.case, 'continue_if_no_converge', False)
        c.use_fd_tangent = getattr(self.case, 'use_fd_tangent', False)  
        c.formulation = self.combo_formulation.currentText()
        c.corot_type = self.combo_corot_formulation.currentText()
        c.results_saved = getattr(self.case, 'results_saved', "Final State Only")
        c.min_saved_states = getattr(self.case, 'min_saved_states', 1)
        c.max_saved_states = getattr(self.case, 'max_saved_states', 100)
        c.save_positive_disp_only = getattr(self.case, 'save_positive_disp_only', False)
        c.hinge_snap = getattr(self.case, 'hinge_snap', True)
        c.hinge_snap_scope = getattr(self.case, 'hinge_snap_scope', 'tension')
        c.stop_on_fiber_failure = getattr(self.case, 'stop_on_fiber_failure', False)
        c.residual_stiffness = getattr(self.case, 'residual_stiffness', 1e-8)
        c.min_step_frac = getattr(self.case, 'min_step_frac', 1e-4)
        c.max_event_probes = getattr(self.case, 'max_event_probes', 12)
        c.auto_cutback = getattr(self.case, 'auto_cutback', True)
        c.max_step_attempts = getattr(self.case, 'max_step_attempts', 0)

        if hasattr(self, 'radio_continue') and self.radio_continue.isChecked() and self.radio_continue.isEnabled():
            c.continue_from_case = self.combo_continue_case.currentText()
        else:
            c.continue_from_case = None

        c.opensees = get_opensees_block(self.case)
        c.load_application = getattr(self.case, 'load_application', "Full Load")
        c.disp_control_node_id = getattr(self.case, 'disp_control_node_id', None)
        c.disp_control_dof = getattr(self.case, 'disp_control_dof', "U1")
        c.disp_control_magnitude = getattr(self.case, 'disp_control_magnitude', 0.1)
        c.disp_control_tol = getattr(self.case, 'disp_control_tol', 1e-6)
                                                                                           
        try:
            c.modal_damping = float(self.input_damping.text()) if hasattr(self, 'input_damping') else 0.05
        except ValueError:
            c.modal_damping = 0.05

        if c.case_type == "Modal":
            c.num_modes   = self.spin_max_modes.value()
            c.min_modes   = self.spin_min_modes.value()
            c.mass_source = self.combo_mass.currentText()
            c.modal_type  = "Ritz" if self.radio_ritz.isChecked() else "Eigen"
            c.modal_fiber_hinges = self.chk_modal_hinges.isChecked()

        elif c.case_type == "Response Spectrum":
            c.modal_case = self.combo_modal_rsa.currentText()
            c.modal_comb = "CQC" if self.radio_cqc.isChecked() else "SRSS"
            c.dir_comb   = "SRSS" if self.radio_dir_srss.isChecked() else "Absolute"
            c.rsa_loads  = []
            for r in range(self.table_rsa.rowCount()):
                cmb_name   = self.table_rsa.cellWidget(r, 0)
                cmb_func   = self.table_rsa.cellWidget(r, 1)
                item_scale = self.table_rsa.item(r, 2)
                if cmb_name and cmb_func and item_scale:
                    try: val = float(item_scale.text())
                    except: val = 1.0
                    c.rsa_loads.append((cmb_name.currentText(), cmb_func.currentText(), val))

        elif c.case_type == "LTHA":
            c.modal_case = self.combo_modal_ltha.currentText()
            try: c.damping = float(self.input_ltha_damping.text())
            except ValueError: c.damping = 0.05
            c.ltha_loads = []
            for r in range(self.table_ltha.rowCount()):
                cmb_dir    = self.table_ltha.cellWidget(r, 0)
                cmb_func   = self.table_ltha.cellWidget(r, 1)
                item_scale = self.table_ltha.item(r, 2)
                if cmb_dir and cmb_func and item_scale:
                    try: scale = float(item_scale.text())
                    except ValueError: scale = 1.0
                    c.ltha_loads.append((cmb_dir.currentText(), cmb_func.currentText(), scale))

        elif c.case_type == "Buckling":
            c.num_modes = self.spin_buck_modes.value()
            try: c.eigen_tol = float(self.input_buck_tol.text())
            except ValueError: c.eigen_tol = 1e-9
            c.mass_source = self.combo_buck_mass.currentText()
            c.loads = []
            for r in range(self.table.rowCount()):
                cmb = self.table.cellWidget(r, 0)
                if not cmb: continue
                try: scale = float(self.table.item(r, 1).text())
                except: scale = 1.0
                c.loads.append((cmb.currentText(), scale))

        else:
                                             
            for r in range(self.table.rowCount()):
                cmb = self.table.cellWidget(r, 0)
                if not cmb: continue
                try: scale = float(self.table.item(r, 1).text())
                except: scale = 1.0
                c.loads.append((cmb.currentText(), scale))

        return c
    
    def validate_rsa_loads(self):
        warnings = []
        for r in range(self.table_rsa.rowCount()):
            cmb_name = self.table_rsa.cellWidget(r, 0)
            cmb_func = self.table_rsa.cellWidget(r, 1)
            if cmb_name and cmb_func:
                load_dir  = cmb_name.currentText()
                func_name = cmb_func.currentText()
                if func_name in self.model.functions:
                    func_data     = self.model.functions[func_name]
                    spectrum_dir  = func_data.get('Direction', 'Horizontal')
                    if load_dir in ["U1", "U2"] and spectrum_dir == "Vertical":
                        warnings.append(f"⚠ Row {r+1}: '{func_name}' is Vertical but applied to {load_dir} (Horizontal)")
                    elif load_dir == "U3" and spectrum_dir == "Horizontal":
                        warnings.append(f"⚠ Row {r+1}: '{func_name}' is Horizontal but applied to U3 (Vertical)")
        if warnings:
            msg  = "Direction Mismatches Found:\n\n" + "\n".join(warnings)
            msg += "\n\nTypically:\n• U1/U2 → Horizontal Spectrum\n• U3 → Vertical Spectrum"
            QMessageBox.warning(self, "Check Spectrum Directions", msg)
            return False
        return True

    def add_rsa_row(self):
        row = self.table_rsa.rowCount()
        self.table_rsa.insertRow(row)
        cmb_name = QComboBox()
        cmb_name.addItems(["U1", "U2", "U3"])
        self.table_rsa.setCellWidget(row, 0, cmb_name)
        cmb_func = QComboBox()
        if hasattr(self.model, 'functions'):
            cmb_func.addItems(self.model.functions.keys())
        else:
            cmb_func.addItem("FUNC1")
        self.table_rsa.setCellWidget(row, 1, cmb_func)
        self.table_rsa.setItem(row, 2, QTableWidgetItem("9.81"))

    def delete_rsa_row(self):
        cr = self.table_rsa.currentRow()
        if cr >= 0: self.table_rsa.removeRow(cr)

    def populate_rsa(self):
        self.table_rsa.setRowCount(0)
        rsa_loads = getattr(self.case, 'rsa_loads', [])
        for load_name, func_name, scale in rsa_loads:
            row = self.table_rsa.rowCount()
            self.table_rsa.insertRow(row)
            cmb_name = QComboBox()
            cmb_name.addItems(["U1", "U2", "U3"])
            cmb_name.setCurrentText(load_name)
            self.table_rsa.setCellWidget(row, 0, cmb_name)
            cmb_func = QComboBox()
            if hasattr(self.model, 'functions'):
                cmb_func.addItems(self.model.functions.keys())
            cmb_func.setCurrentText(func_name)
            self.table_rsa.setCellWidget(row, 1, cmb_func)
            
            display_scale = unit_registry.to_display_acceleration(scale)
            self.table_rsa.setItem(row, 2, QTableWidgetItem(f"{display_scale:.4f}"))

    def preview_spectrum(self):
        cr = self.table_rsa.currentRow()
        if cr < 0:
            QMessageBox.information(self, "No Selection", "Please select a row first.")
            return
        cmb_func = self.table_rsa.cellWidget(cr, 1)
        if not cmb_func: return
        func_name = cmb_func.currentText()
        if func_name not in self.model.functions:
            QMessageBox.warning(self, "Not Found", f"Function '{func_name}' doesn't exist.")
            return
        from app.dialogs.response_spectrum_dialog import ResponseSpectrumDialog
        dlg = ResponseSpectrumDialog(self)
        dlg.setWindowTitle(f"Preview: {func_name}")
        data = self.model.functions[func_name]
        dlg.input_name.setText(data.get('name', ''))
        dlg.input_name.setReadOnly(True)
        dlg.in_ss.setText(str(data.get('Ss', 0.55)))
        dlg.in_s1.setText(str(data.get('S1', 0.22)))
        dlg.in_tl.setText(str(data.get('TL', 6.0)))
        dlg.in_R.setText(str(data.get('R', 8.0)))
        dlg.in_D.setText(str(data.get('D', 3.0)))
        dlg.in_I.setText(str(data.get('I', 1.0)))
        dlg.combo_site.setCurrentText(data.get('SiteClass', 'ZB'))
        dlg.combo_dir.setCurrentText(data.get('Direction', 'Horizontal'))
        dlg.in_damp.setText(str(data.get('Damping', 0.05)))
        dlg.btn_ok.setText("Close")
        dlg.btn_cancel.setVisible(False)
        dlg.update_graph()
        dlg.exec()

    def open_nonlinear_params(self):
        dlg = NonlinearParametersDialog(self.case, self, model=self.model)
        if dlg.exec():
            dlg.save_to_case()

    def _refresh_load_app_label(self):
        mode = getattr(self.case, 'load_application', "Full Load")
        self.lbl_row_load_app.setText(f"Load Application ({mode})")

    def open_load_application(self):
        dlg = LoadApplicationControlDialog(self.model, self.case, self)
        if dlg.exec():
            dlg.save_to_case()
            self._refresh_load_app_label()

    def _refresh_results_saved_label(self):
        mode = getattr(self.case, 'results_saved', "Final State Only")
        if mode == "Multiple States" and int(getattr(self.case, 'max_saved_states', 100) or 0) <= 0:
            mode = "All Steps"
        self.lbl_row_results.setText(f"Results Saved ({mode})")

    def open_results_saved(self):
        dlg = ResultsSavedDialog(self.case, self)
        if dlg.exec():
            dlg.save_to_case()
            self._refresh_results_saved_label()

class LoadCaseManagerDialog(QDialog):
    """The Main List Window (Define Load Cases)"""
    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self.setWindowTitle("Define Load Cases")
        self.resize(500, 300)

        apply_dialog_style(self)                             

        layout = QHBoxLayout(self)

        self.list_widget = QListWidget()
        self.refresh_list()
        layout.addWidget(self.list_widget)

        v_btns = QVBoxLayout()

        btn_add = QPushButton("Add New Case...")
        btn_add.clicked.connect(self.add_case)

        btn_copy = QPushButton("Add Copy of Load Case...")
        btn_copy.clicked.connect(self.copy_case)

        btn_mod = QPushButton("Modify/Show Case...")
        btn_mod.clicked.connect(self.modify_case)

        btn_del = QPushButton("Delete Case")
        btn_del.clicked.connect(self.delete_case)

        v_btns.addWidget(btn_add)
        v_btns.addWidget(btn_copy)
        v_btns.addWidget(btn_mod)
        v_btns.addWidget(btn_del)
        v_btns.addStretch()

        btn_ok = QPushButton("OK")
        btn_ok.setObjectName("primary")                              
        btn_ok.clicked.connect(self.accept)
        v_btns.addWidget(btn_ok)

        layout.addLayout(v_btns)

    def refresh_list(self):
        self.list_widget.clear()
        for name, case in self.model.load_cases.items():
            c_type = case.get("type", "Linear Static") if isinstance(case, dict) else case.case_type
            self.list_widget.addItem(f"{name}  ({c_type})")

    def add_case(self):
        idx = 1
        while f"CASE{idx}" in self.model.load_cases:
            idx += 1
        temp_case = LoadCase(f"CASE{idx}", "Linear Static")
        dlg = LoadCaseDetailDialog(self.model, temp_case, self, is_new=True)
        if dlg.exec():
            final_case = dlg.get_data()
            self.model.load_cases[final_case.name] = final_case
            self.refresh_list()

    def copy_case(self):
        item = self.list_widget.currentItem()
        if not item: 
            return
            
        old_name = item.text().split("  (")[0]
        
        if old_name in self.model.load_cases:
            original_case = self.model.load_cases[old_name]
            
            copied_case = copy.deepcopy(original_case)
            
            new_name = f"{old_name} (Copy)"
            idx = 1
            while new_name in self.model.load_cases:
                new_name = f"{old_name} (Copy {idx})"
                idx += 1
                
            copied_case.name = new_name
            
            dlg = LoadCaseDetailDialog(self.model, copied_case, self, is_new=True)
            if dlg.exec():
                final_case = dlg.get_data()
                self.model.load_cases[final_case.name] = final_case
                self.refresh_list()

    def modify_case(self):
        item = self.list_widget.currentItem()
        if not item: return
        old_name = item.text().split("  (")[0]
        if old_name in self.model.load_cases:
            original_case = self.model.load_cases[old_name]
            dlg = LoadCaseDetailDialog(self.model, original_case, self, is_new=False)
            if dlg.exec():
                new_case = dlg.get_data()
                if new_case.name != old_name:
                    del self.model.load_cases[old_name]
                self.model.load_cases[new_case.name] = new_case
                self.refresh_list()

    def delete_case(self):
        item = self.list_widget.currentItem()
        if not item: return
        name = item.text().split("  (")[0]
        if name == "DEAD":
            QMessageBox.warning(self, "Error", "Cannot delete default DEAD case.")
            return
        del self.model.load_cases[name]
        self.refresh_list()
