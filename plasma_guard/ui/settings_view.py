"""Settings view: scan options, schedule, behaviour."""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QSpinBox, QTimeEdit, QVBoxLayout, QWidget,
)

from ..icons import icon
from .. import scheduler
from ..config import SettingsManager, ScanSettings

log = logging.getLogger(__name__)


class SettingsView(QWidget):
    """User-facing settings."""

    def __init__(self, settings_manager: SettingsManager,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.sm = settings_manager
        self.s = settings_manager.settings
        self._build_ui()
        self._load_into_ui()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(14)

        title = QLabel("Settings")
        title.setObjectName("titleLabel")
        sub = QLabel("Tune scan options, the scheduler, and the tray.")
        sub.setObjectName("subtitleLabel")
        outer.addWidget(title)
        outer.addWidget(sub)

        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll, stretch=1)

        body = QWidget()
        scroll.setWidget(body)
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(16)

        # ---------------- Scanning ----------------
        scan_box = QGroupBox("Scanning")
        scan_form = QFormLayout(scan_box)
        scan_form.setLabelAlignment(Qt.AlignRight)
        scan_form.setFormAlignment(Qt.AlignTop)
        scan_form.setHorizontalSpacing(16)
        scan_form.setVerticalSpacing(8)

        self.chk_recursive = QCheckBox("Recursive scan (folders)")
        self.chk_archives = QCheckBox("Scan inside archives (zip, tar, …)")
        self.chk_mail = QCheckBox("Scan email files (mbox, mbx)")
        self.chk_heuristics = QCheckBox("Enable heuristic alerts")
        self.chk_logging = QCheckBox("Log to system log")
        for c in (self.chk_recursive, self.chk_archives, self.chk_mail,
                  self.chk_heuristics, self.chk_logging):
            scan_form.addRow(c)

        self.spn_max_size = QSpinBox()
        self.spn_max_size.setRange(0, 100_000)
        self.spn_max_size.setSuffix(" MB")
        self.spn_max_size.setSpecialValueText("Unlimited")
        scan_form.addRow("Max file size:", self.spn_max_size)

        self.spn_max_time = QSpinBox()
        self.spn_max_time.setRange(0, 24 * 3600)
        self.spn_max_time.setSuffix(" s")
        self.spn_max_time.setSpecialValueText("Unlimited")
        scan_form.addRow("Per-file timeout:", self.spn_max_time)

        body_lay.addWidget(scan_box)

        # ---------------- Quarantine ----------------
        quar_box = QGroupBox("Quarantine")
        qf = QFormLayout(quar_box)
        qf.setLabelAlignment(Qt.AlignRight)
        qf.setHorizontalSpacing(16)
        qf.setVerticalSpacing(8)

        self.chk_auto_quar = QCheckBox("Auto-quarantine infected files")
        self.ed_quar_pwd = QLineEdit()
        self.ed_quar_pwd.setEchoMode(QLineEdit.Password)
        self.ed_quar_pwd.setPlaceholderText("ZIP encryption password")
        qf.addRow(self.chk_auto_quar)
        qf.addRow("ZIP password:", self.ed_quar_pwd)
        body_lay.addWidget(quar_box)

        # ---------------- Scheduler ----------------
        sch_box = QGroupBox("Scheduled scans")
        sf = QFormLayout(sch_box)
        sf.setLabelAlignment(Qt.AlignRight)
        sf.setHorizontalSpacing(16)
        sf.setVerticalSpacing(8)

        self.chk_sched = QCheckBox("Enable scheduled scans (systemd user timer)")
        sf.addRow(self.chk_sched)

        self.cmb_freq = QComboBox()
        self.cmb_freq.addItems(["Daily", "Weekly", "Monthly"])
        sf.addRow("Frequency:", self.cmb_freq)

        self.cmb_day_of_week = QComboBox()
        for i, n in enumerate(["Monday", "Tuesday", "Wednesday", "Thursday",
                               "Friday", "Saturday", "Sunday"]):
            self.cmb_day_of_week.addItem(n, i)
        sf.addRow("Day of week:", self.cmb_day_of_week)

        self.spn_dom = QSpinBox()
        self.spn_dom.setRange(1, 28)
        sf.addRow("Day of month:", self.spn_dom)

        self.time_edit = QTimeEdit()
        self.time_edit.setDisplayFormat("HH:mm")
        sf.addRow("Time:", self.time_edit)

        sch_actions = QHBoxLayout()
        self.btn_install_timer = QPushButton("Apply / refresh systemd timer")
        self.btn_install_timer.clicked.connect(self._apply_timer)
        sch_actions.addWidget(self.btn_install_timer)
        self.btn_uninstall_timer = QPushButton("Remove timer")
        self.btn_uninstall_timer.clicked.connect(self._remove_timer)
        sch_actions.addWidget(self.btn_uninstall_timer)
        sch_actions.addStretch()
        sf.addRow(" ", self._wrap(sch_actions))

        self.lbl_timer_status = QLabel("Timer: not installed")
        self.lbl_timer_status.setObjectName("cardSub")
        self.lbl_timer_status.setWordWrap(True)
        sf.addRow("Status:", self.lbl_timer_status)
        self._refresh_timer_status()
        body_lay.addWidget(sch_box)

        # ---------------- Tray / UI ----------------
        ui_box = QGroupBox("Application")
        uf = QFormLayout(ui_box)
        uf.setLabelAlignment(Qt.AlignRight)
        uf.setHorizontalSpacing(16)
        uf.setVerticalSpacing(8)

        self.chk_tray = QCheckBox("Show system tray icon (can cause crashes on some systems)")
        self.chk_start_min = QCheckBox("Start minimized to tray")
        self.chk_close_tray = QCheckBox("Close button hides to tray (instead of exiting)")
        self.chk_notify = QCheckBox("Show desktop notifications")
        self.chk_drop_zone = QCheckBox("Show drop zone in sidebar (drag & drop files to scan)")
        for c in (self.chk_tray, self.chk_start_min, self.chk_close_tray, self.chk_notify, self.chk_drop_zone):
            uf.addRow(c)
        body_lay.addWidget(ui_box)

        body_lay.addStretch()

        # Footer with save/reset
        footer = QHBoxLayout()
        self.btn_diagnose = QPushButton("  Run diagnostics")
        self.btn_diagnose.setIcon(icon("dialog-information"))
        self.btn_diagnose.clicked.connect(self._on_diagnose)
        footer.addWidget(self.btn_diagnose)
        self.btn_reset = QPushButton("  Reset to defaults")
        self.btn_reset.setIcon(icon("edit-undo"))
        self.btn_reset.clicked.connect(self._on_reset)
        footer.addWidget(self.btn_reset)
        footer.addStretch()
        self.btn_save = QPushButton("  Save")
        self.btn_save.setIcon(icon("document-save"))
        self.btn_save.setObjectName("primary")
        self.btn_save.clicked.connect(self._on_save)
        footer.addWidget(self.btn_save)
        outer.addLayout(footer)

    def _wrap(self, lay) -> QWidget:
        w = QWidget()
        w.setLayout(lay)
        return w

    # ------------------------------------------------------------- load/save

    def _load_into_ui(self) -> None:
        s = self.s
        self.chk_recursive.setChecked(s.recursive)
        self.chk_archives.setChecked(s.scan_archives)
        self.chk_mail.setChecked(s.scan_mail)
        self.chk_heuristics.setChecked(s.heuristic_alerts)
        self.chk_logging.setChecked(s.enable_logging)
        self.spn_max_size.setValue(s.max_file_size_mb)
        self.spn_max_time.setValue(s.max_scan_time_s)

        self.chk_auto_quar.setChecked(s.auto_quarantine)
        self.ed_quar_pwd.setText(s.quarantine_password)

        self.chk_sched.setChecked(s.schedule_enabled)
        idx = {"daily": 0, "weekly": 1, "monthly": 2}.get(s.schedule_frequency, 1)
        self.cmb_freq.setCurrentIndex(idx)
        idx_dow = self.cmb_day_of_week.findData(s.schedule_day_of_week)
        if idx_dow >= 0:
            self.cmb_day_of_week.setCurrentIndex(idx_dow)
        self.spn_dom.setValue(s.schedule_day_of_month)
        from PySide6.QtCore import QTime
        self.time_edit.setTime(QTime(s.schedule_hour, s.schedule_minute))

        self.chk_tray.setChecked(s.enable_tray_icon)
        self.chk_start_min.setChecked(s.start_minimized_to_tray)
        self.chk_close_tray.setChecked(s.close_to_tray)
        self.chk_notify.setChecked(s.show_notifications)
        self.chk_drop_zone.setChecked(s.enable_drop_zone)

    def _on_save(self) -> None:
        from PySide6.QtCore import QTime
        t = self.time_edit.time()
        freq = ["daily", "weekly", "monthly"][self.cmb_freq.currentIndex()]
        dow = self.cmb_day_of_week.currentData()
        self.sm.update(
            recursive=self.chk_recursive.isChecked(),
            scan_archives=self.chk_archives.isChecked(),
            scan_mail=self.chk_mail.isChecked(),
            heuristic_alerts=self.chk_heuristics.isChecked(),
            enable_logging=self.chk_logging.isChecked(),
            max_file_size_mb=self.spn_max_size.value(),
            max_scan_time_s=self.spn_max_time.value(),
            auto_quarantine=self.chk_auto_quar.isChecked(),
            quarantine_password=self.ed_quar_pwd.text() or "infected",
            schedule_enabled=self.chk_sched.isChecked(),
            schedule_frequency=freq,
            schedule_day_of_week=int(dow) if dow is not None else 0,
            schedule_day_of_month=self.spn_dom.value(),
            schedule_hour=t.hour(),
            schedule_minute=t.minute(),
            start_minimized_to_tray=self.chk_start_min.isChecked(),
            close_to_tray=self.chk_close_tray.isChecked(),
            show_notifications=self.chk_notify.isChecked(),
            enable_tray_icon=self.chk_tray.isChecked(),
            enable_drop_zone=self.chk_drop_zone.isChecked(),
        )
        QMessageBox.information(self, "Settings", "Settings saved.")
        self._apply_timer(silent=True)

    def _on_reset(self) -> None:
        confirm = QMessageBox.question(
            self, "Reset settings",
            "Reset all settings to their defaults?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        self.sm.reset()
        self._load_into_ui()
        QMessageBox.information(self, "Settings", "Settings reset.")

    def _on_diagnose(self) -> None:
        from .. import diagnose
        report = diagnose.format_report()
        mb = QMessageBox(self)
        mb.setWindowTitle("Plasma Guard diagnostic report")
        mb.setText(report)
        mb.setIcon(QMessageBox.Information)
        mb.setStandardButtons(QMessageBox.Ok)
        # Make the message box wider/taller so the report is readable
        from PySide6.QtWidgets import QTextEdit
        te = QTextEdit()
        te.setPlainText(report)
        te.setReadOnly(True)
        te.setMinimumSize(720, 480)
        mb.layout().addWidget(te, 0, 0)
        # Remove the default detailed text area
        mb.setDetailedText("")
        mb.exec()

    # ------------------------------------------------------------- scheduler

    def _apply_timer(self, silent: bool = False) -> None:
        ok, msg = scheduler.install(self.sm.settings)
        if not silent:
            QMessageBox.information(self, "Scheduler", msg)
        self._refresh_timer_status()

    def _remove_timer(self) -> None:
        ok, msg = scheduler.uninstall()
        QMessageBox.information(self, "Scheduler", msg)
        self._refresh_timer_status()

    def _refresh_timer_status(self) -> None:
        s = scheduler.status()
        active = "active" if s.get("active") else "inactive"
        nr = s.get("next_run", "")
        self.lbl_timer_status.setText(
            f"Status: {active}\n"
            f"Next run: {nr or '—'}\n"
            f"Service: {s.get('service')}\n"
            f"Timer:   {s.get('timer')}"
        )
