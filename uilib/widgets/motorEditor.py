from PyQt6.QtWidgets import QLabel, QComboBox, QHBoxLayout, QWidget
from PyQt6.QtWidgets import QCheckBox, QSizePolicy
from PyQt6.QtCore import pyqtSignal

import motorlib.grain
import motorlib.nozzle
import motorlib.motor
import motorlib.taper
import motorlib.properties

from .collectionEditor import CollectionEditor
from .propertyEditor import PropertyEditor
from .grainPreviewWidget import GrainPreviewWidget
from .nozzlePreviewWidget import NozzlePreviewWidget
from .solverConfigController import SolverConfigController

class MotorEditor(CollectionEditor):

    # Emitted on Apply when editing the motor config (grain-table 'Config' row):
    # MotorConfig values, per-solver config overrides, the selected library
    # pyrogen NAME, and the igniter-chamber values. Pyrogen + igniter are
    # populated only for igniter-capable solvers (srm_1d); '' / {} otherwise.
    motorConfigApplied = pyqtSignal(dict, dict, str, dict)
    # Emitted when the config editor's solver dropdown changes, to couple the
    # active solver (wired to PreferencesManager by the main window).
    activeSolverChanged = pyqtSignal(str)

    def __init__(self, parent):
        super().__init__(parent, True)

        # Solver selector shown only while editing the motor config (the
        # grain-table 'Config' row). Inserted above the property form.
        self.solverSelector = QComboBox()
        selectorRow = QHBoxLayout()
        selectorRow.addWidget(QLabel('Solver:'))
        selectorRow.addWidget(self.solverSelector)
        selectorRow.addStretch()
        self.solverSelectorContainer = QWidget()
        self.solverSelectorContainer.setLayout(selectorRow)
        self.solverSelectorContainer.hide()
        self.layout().insertWidget(0, self.solverSelectorContainer)
        self.solverSelector.currentTextChanged.connect(self._solverChanged)

        # Pyrogen picker shown in the config screen for igniter-capable solvers
        # (srm_1d). Selecting a library pyrogen copies it into the motor's
        # embedded material on apply (mirrors the grain propellant picker).
        self.pyrogenSelector = QComboBox()
        pyroRow = QHBoxLayout()
        pyroRow.addWidget(QLabel('Pyrogen:'))
        pyroRow.addWidget(self.pyrogenSelector)
        pyroRow.addStretch()
        self.pyrogenSelectorContainer = QWidget()
        self.pyrogenSelectorContainer.setLayout(pyroRow)
        self.pyrogenSelectorContainer.hide()
        self.layout().insertWidget(0, self.pyrogenSelectorContainer)

        self.expRatioLabel = QLabel("Expansion ratio: -")
        self.expRatioLabel.hide()
        self.stats.addWidget(self.expRatioLabel)

        self.grainPreview = GrainPreviewWidget()
        self.grainPreview.hide()
        self.stats.addWidget(self.grainPreview)

        self.nozzlePreview = NozzlePreviewWidget()
        self.nozzlePreview.hide()
        self.stats.addWidget(self.nozzlePreview)

        self.objType = None
        self.configMotor = None     # set while editing the motor config
        self.controller = None
        self._pyrogenNames = []
        # Axial-taper editor state (set only while editing a perforated grain).
        # None signals "no taper controls active" so getProperties / preview
        # leave non-grain objects untouched.
        self._taperAftEditors = None
        self._odWidgets = None       # OD/end-taper controls, per end ('fwd'/'aft')
        self._odSyncing = False      # reentrancy guard for the coupled OD fields
        self._buildingGrainForm = False  # suppress preview rebuilds during build

    # Igniter-chamber fields that only apply to one injection topology.
    _IGNITER_PLENUM_ONLY = ('throat_area', 'volume')
    _IGNITER_BASKET_ONLY = ('basket_fill_fraction', 'pellet_packing_fraction')
    # Chamber fields whose -1 sentinel means "auto-size" (backend derives it).
    # Presented as "auto" at the spin minimum (0); any value <= 0 maps to -1.
    _IGNITER_AUTO_FIELDS = ('mass', 'throat_area', 'volume', 'burn_area',
                            'cartridge_length_m')

    def _setFieldVisible(self, key, visible):
        ed = self.propertyEditors.get(key)
        if ed is not None:
            self.form.setRowVisible(ed, visible)

    def _applyIgniterFieldRules(self):
        """Show only the chamber inputs relevant to the chosen injection
        topology: forward_plenum uses the orifice/plenum fields; the basket
        topologies use the basket packing fields."""
        ed = self.propertyEditors.get('injection_topology')
        if ed is None:
            return
        plenum = ed.getValue() == 'forward_plenum'
        for key in self._IGNITER_PLENUM_ONLY:
            self._setFieldVisible(key, plenum)
        for key in self._IGNITER_BASKET_ONLY:
            self._setFieldVisible(key, not plenum)

    def _setupIgniterFormExtras(self):
        """After the igniter-chamber section is rendered (config screen): show
        the -1 "auto" sentinels and apply the topology field rules."""
        for key in self._IGNITER_AUTO_FIELDS:
            ed = self.propertyEditors.get(key)
            if ed is not None and hasattr(ed.editor, 'setSpecialValueText'):
                ed.editor.setMinimum(0.0)
                ed.editor.setSpecialValueText('auto')
                if ed.editor.value() <= 0.0:
                    ed.editor.setValue(0.0)
        self._applyIgniterFieldRules()

    def propertyUpdate(self):
        # While _loadGrainProperties builds the taper form, each field/toggle it
        # adds would otherwise rebuild the grain and spawn a preview thread.
        # Suppress those; one update runs once the form is complete.
        if self._buildingGrainForm:
            return
        if 'injection_topology' in self.propertyEditors:
            # Igniter-chamber form (config screen, srm_1d): drive field
            # relevance off the topology dropdown.
            self._applyIgniterFieldRules()
            return
        if self.objType is None:
            return
        if issubclass(self.objType, motorlib.nozzle.Nozzle):
            exitDia = self.propertyEditors['exit'].getValue()
            throatDia = self.propertyEditors['throat'].getValue()
            if throatDia == 0:
                self.expRatioLabel.setText('Expansion ratio: -')
            else:
                self.expRatioLabel.setText('Expansion ratio: {:.3f}'.format((exitDia / throatDia) ** 2))
            nozzle = self.objType()
            nozzle.setProperties(self.getProperties())
            self.nozzlePreview.loadNozzle(nozzle)

        if issubclass(self.objType, motorlib.grain.PerforatedGrain):
            # Build the grain from the current form (taper included); the
            # preview renders the selected end's cross-section for the
            # face/regression images and the slice-averaged burn area on the
            # area tab.
            testGrain = self.objType()
            testGrain.setProperties(self.getProperties())
            side = 'Forward'
            if (self._taperAftEditors is not None
                    and getattr(self, 'taperEnable', None) is not None
                    and self.taperEnable.isChecked()):
                side = self.taperPreviewSide.currentText()
            self.grainPreview.loadGrain(testGrain, side)

    def getProperties(self):
        """Grain editing: fold the inline taper controls into the emitted
        property dict (so it round-trips via setProperties). Emits an enabled
        taper with only the aft values that differ from the start, or an
        explicit ``{'enabled': False}`` so toggling off clears an existing
        taper. No-op for non-grain objects."""
        props = super().getProperties()
        if self._taperAftEditors is not None and getattr(self, 'taperEnable', None) is not None:
            if self.taperEnable.isChecked():
                overrides = {name: ed.getValue()
                             for name, ed in self._taperAftEditors.items()
                             if name in props and ed.getValue() != props[name]}
                taper = motorlib.taper.build_bore_taper_def(
                    overrides, profile=self.taperProfile.currentText().lower())
            else:
                taper = {'enabled': False}
            od_ends = self._odEnds()
            if od_ends:
                taper['od'] = {'enabled': True, 'ends': od_ends}
            props['taper'] = taper
        return props

    def setPreferences(self, pref):
        super().setPreferences(pref)
        # The grain preview's longitudinal OD view honors the length unit.
        self.grainPreview.setPreferences(pref)

    def _alignedCell(self, widget, left=5):
        """Wrap a raw field widget (checkbox / combo) so its left edge and row
        height match the PropertyEditor fields (5px content margins) — i.e. the
        same placement as a vanilla BooleanProperty checkbox (e.g. Inverted
        Fins), which sits ~2px left of the spinbox content."""
        cell = QWidget()
        lay = QHBoxLayout(cell)
        lay.setContentsMargins(left, 5, 5, 5)
        lay.addWidget(widget)
        lay.addStretch()
        return cell

    def loadObject(self, obj):
        self.configMotor = None
        self.controller = None
        self.solverSelectorContainer.hide()
        self.pyrogenSelectorContainer.hide()
        self.objType = type(obj)
        if issubclass(self.objType, motorlib.grain.PerforatedGrain):
            self._loadGrainProperties(obj)
        else:
            self.loadProperties(obj)

        if issubclass(self.objType, motorlib.grain.PerforatedGrain):
            self.grainPreview.show()
            self.nozzlePreview.hide()
            self.expRatioLabel.hide()
            self.propertyUpdate()

        if issubclass(self.objType, motorlib.nozzle.Nozzle):
            self.expRatioLabel.show()
            self.nozzlePreview.show()
            self.grainPreview.hide()

        if issubclass(self.objType, motorlib.motor.MotorConfig):
            self.expRatioLabel.hide()
            self.nozzlePreview.hide()
            self.grainPreview.hide()

    def _loadGrainProperties(self, grain):
        """Render a grain's property form with an inline axial-taper editor:
        each taperable cross-section property gets a second 'aft' field beside
        its start value, plus an enable checkbox, a Profile dropdown, and a
        forward/aft preview toggle. The aft column / profile are shown only
        when the taper is enabled (mirrors the igniter conditional-field
        pattern). Taper assembly/parsing lives in motorlib.taper so it is
        shared and headlessly testable."""
        self.cleanup()

        # Grains that opt out of tapering (e.g. Conical, already an axial bore
        # taper) render as a plain property form.
        if not getattr(grain, 'isTaperable', True):
            self.loadProperties(grain)
            return

        self._buildingGrainForm = True
        try:
            self._populateGrainForm(grain)
        finally:
            self._buildingGrainForm = False
        self.propertyUpdate()

    def _populateGrainForm(self, grain):
        """Build the taper form rows for ``grain``. Called inside the
        _buildingGrainForm guard so the field/toggle wiring it sets up does not
        trigger a preview rebuild per row; loadObject renders once afterward."""
        self._taperAftEditors = {}

        taperable = set(motorlib.taper.taperable_property_names(grain))
        aftVals = motorlib.taper.aft_props_from_grain(grain)
        taperDef = grain.getTaperDef()
        enabled = bool(taperDef.get('enabled'))
        profile = (taperDef.get('bore', {}) or {}).get('profile', 'linear')

        # Column headers over the [ Forward port | Aft Port ] composite fields;
        # shown only while the bore taper is enabled (toggled in _taperToggled).
        self.taperColHeader = QWidget()
        hrow = QHBoxLayout(self.taperColHeader)
        hrow.setContentsMargins(0, 5, 5, 0)   # match the composite field (left=0)
        hrow.setSpacing(4)
        _fwdHdr = QLabel('Forward port')
        _aftHdr = QLabel('Aft port')
        # Both labels land ~3px right of their column's spinbox; the aft column
        # sits ~4px further left, so it needs the larger indent to even out.
        _fwdHdr.setIndent(8)
        _aftHdr.setIndent(12)
        hrow.addWidget(_fwdHdr, 1)
        hrow.addWidget(_aftHdr, 1)
        headerInserted = False

        for name, prop in grain.props.items():
            if name == 'taper':
                continue
            startEd = PropertyEditor(self, prop, self.preferences)
            startEd.valueChanged.connect(self.propertyUpdate)
            self.propertyEditors[name] = startEd
            label = QLabel('{}:'.format(prop.dispName))
            label.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
            if name in taperable:
                if not headerInserted:           # directly above the first pair
                    self.form.addRow(QLabel(''), self.taperColHeader)
                    headerInserted = True
                # Composite field: equal-width [ start | aft ] under the headers.
                aftProp = type(prop)(prop.dispName, prop.unit, prop.min, prop.max)
                aftProp.setValue(aftVals.get(name, prop.getValue()))
                aftEd = PropertyEditor(self, aftProp, self.preferences)
                aftEd.valueChanged.connect(self.propertyUpdate)
                self._taperAftEditors[name] = aftEd
                field = QWidget()
                row = QHBoxLayout(field)
                row.setContentsMargins(0, 0, 0, 0)
                row.setSpacing(4)
                row.addWidget(startEd, 1)
                row.addWidget(aftEd, 1)
                self.form.addRow(label, field)
            else:
                self.form.addRow(label, startEd)

        # Enable + Profile control row.
        self.taperEnable = QCheckBox('Taper grain')
        self.taperEnable.setChecked(enabled)
        self.taperEnable.toggled.connect(self._taperToggled)
        self.taperProfileLabel = QLabel('Profile:')
        self.taperProfile = QComboBox()
        self.taperProfile.addItems(['Linear'])
        self.taperProfile.setCurrentText(profile.capitalize()
                                         if profile.capitalize() in ('Linear',)
                                         else 'Linear')
        ctrl = QWidget()
        crow = QHBoxLayout(ctrl)
        crow.setContentsMargins(5, 5, 5, 5)   # match vanilla checkbox + row height
        crow.addWidget(self.taperEnable)
        crow.addSpacing(12)
        crow.addWidget(self.taperProfileLabel)
        crow.addWidget(self.taperProfile)
        crow.addStretch()
        self.form.addRow(QLabel('Axial taper:'), ctrl)

        # Forward/aft preview toggle (drives which cross-section the 2-D grain
        # preview renders; the results slice viewer shows the full axial taper).
        self.taperPreviewSide = QComboBox()
        self.taperPreviewSide.addItems(['Forward', 'Aft'])
        self.taperPreviewSide.currentTextChanged.connect(self.propertyUpdate)
        self.taperPreviewRow = QWidget()
        prow = QHBoxLayout(self.taperPreviewRow)
        prow.setContentsMargins(5, 5, 5, 5)   # align + match row height
        prow.addWidget(self.taperPreviewSide)
        prow.addStretch()
        self.form.addRow(QLabel('Preview end:'), self.taperPreviewRow)

        self._buildOdControls(grain)

        self._taperToggled(enabled)
        self._odToggled()
        if self.buttons:
            self.applyButton.show()
            self.cancelButton.show()
        # No propertyUpdate() here: _loadGrainProperties renders once after the
        # _buildingGrainForm guard is cleared (and loadObject again once shown).

    def _buildOdControls(self, grain):
        """OD / end-taper section: a master enable, then per end (fwd/aft) a
        profile + length + endDiameter + a profile-dependent companion (a
        half-angle for Linear, an end fraction for Elliptical). The companion
        couples live to endDiameter via motorlib.taper helpers."""
        od_def = (grain.getTaperDef() or {}).get('od') or {}
        ends_by = {e.get('end'): e for e in od_def.get('ends', [])
                   if isinstance(e, dict)}
        full_d = grain.getProperty('diameter') or 1.0
        grain_len = grain.getProperty('length') or 1.0

        # Indent the OD sub-rows under the section (a few px, two levels), so
        # the hierarchy reads without leading-space hacks.
        def _ind(text, px):
            lbl = QLabel(text)
            lbl.setIndent(px)
            return lbl

        self.odEnable = QCheckBox()
        self.odEnable.setChecked(bool(od_def.get('enabled')))
        self.odEnable.toggled.connect(lambda _on: self._odToggled())
        self.form.addRow(QLabel('End taper (OD):'),
                         self._alignedCell(self.odEnable))

        def _fProp(name, unit, lo, hi, val):
            p = motorlib.properties.FloatProperty(name, unit, lo, hi)
            p.setValue(val)
            return PropertyEditor(self, p, self.preferences)

        self._odWidgets = {}
        for end in ('fwd', 'aft'):
            e = ends_by.get(end, {})
            tag = 'Forward OD' if end == 'fwd' else 'Aft OD'

            enable = QCheckBox()
            enable.setChecked(bool(e))
            enable.toggled.connect(lambda _on: self._odToggled())
            enableCell = self._alignedCell(enable)

            profile = QComboBox()
            profile.addItems(['Linear', 'Elliptical'])
            prof = str(e.get('profile', 'linear')).capitalize()
            profile.setCurrentText(prof if prof in ('Linear', 'Elliptical') else 'Linear')
            profileCell = self._alignedCell(profile)

            lengthEd = _fProp('Length', 'm', 0.0, grain_len, float(e.get('length', 0.0)))
            endDiaEd = _fProp('End diameter', 'm', 0.0, full_d,
                              float(e.get('endDiameter', full_d)))
            angleEd = _fProp('Angle', 'deg', 0.0, 89.0, 0.0)
            fracEd = _fProp('End fraction', '', 0.0, 1.0, 1.0)

            self.form.addRow(_ind(tag, 12), enableCell)
            self.form.addRow(_ind('Profile:', 24), profileCell)
            self.form.addRow(_ind('Length:', 24), lengthEd)
            self.form.addRow(_ind('End diameter:', 24), endDiaEd)
            self.form.addRow(_ind('Angle:', 24), angleEd)
            self.form.addRow(_ind('End fraction:', 24), fracEd)

            self._odWidgets[end] = dict(enable=enable, enableCell=enableCell,
                                        profile=profile, profileCell=profileCell,
                                        length=lengthEd, endDiameter=endDiaEd,
                                        angle=angleEd, fraction=fracEd)

            self._odSync(end, 'init')   # seed companions from endDiameter
            profile.currentTextChanged.connect(lambda _t, en=end: self._odSync(en, 'profile'))
            lengthEd.valueChanged.connect(lambda en=end: self._odSync(en, 'length'))
            endDiaEd.valueChanged.connect(lambda en=end: self._odSync(en, 'endDiameter'))
            angleEd.valueChanged.connect(lambda en=end: self._odSync(en, 'angle'))
            fracEd.valueChanged.connect(lambda en=end: self._odSync(en, 'fraction'))

        # Resync OD companions when the grain's outer diameter changes.
        if 'diameter' in self.propertyEditors:
            self.propertyEditors['diameter'].valueChanged.connect(self._odResyncAll)

    def _odResyncAll(self):
        if self._odWidgets:
            self._odSync('fwd', 'diameter')
            self._odSync('aft', 'diameter')

    def _odSync(self, end, changed):
        """Recompute the coupled OD fields for one end. endDiameter is the
        canonical value; the half-angle (Linear) / end fraction (Elliptical)
        are derived from it, and edits to a companion update endDiameter."""
        if self._odSyncing or not self._odWidgets:
            return
        self._odSyncing = True
        try:
            w = self._odWidgets[end]
            full_d = self.propertyEditors['diameter'].getValue()
            length = w['length'].getValue()
            if changed == 'angle':
                end_d = motorlib.taper.od_end_diameter_from_angle(
                    full_d, length, w['angle'].getValue())
            elif changed == 'fraction':
                end_d = motorlib.taper.od_end_diameter_from_fraction(
                    full_d, w['fraction'].getValue())
            else:
                end_d = w['endDiameter'].getValue()
            end_d = min(full_d, max(0.0, end_d))
            w['endDiameter'].setValue(end_d)
            w['angle'].setValue(
                motorlib.taper.od_angle_from_end_diameter(full_d, length, end_d))
            w['fraction'].setValue(
                motorlib.taper.od_fraction_from_end_diameter(full_d, end_d))
        finally:
            self._odSyncing = False
        self._odToggled()

    def _odToggled(self):
        """Show OD rows per the master enable, each end's enable, and the
        profile (angle for Linear, end-fraction for Elliptical)."""
        if not self._odWidgets:
            return
        on = self.odEnable.isChecked()
        for end in ('fwd', 'aft'):
            w = self._odWidgets.get(end)
            if w is None:                       # mid-construction
                continue
            self.form.setRowVisible(w['enableCell'], on)
            end_on = on and w['enable'].isChecked()
            lin = w['profile'].currentText().lower() == 'linear'
            self.form.setRowVisible(w['profileCell'], end_on)
            self.form.setRowVisible(w['length'], end_on)
            self.form.setRowVisible(w['endDiameter'], end_on)
            self.form.setRowVisible(w['angle'], end_on and lin)
            self.form.setRowVisible(w['fraction'], end_on and not lin)
        self.propertyUpdate()

    def _odEnds(self):
        """The enabled OD end-taper entries from the current form (or [])."""
        if not self._odWidgets or not self.odEnable.isChecked():
            return []
        ends = []
        for end in ('fwd', 'aft'):
            w = self._odWidgets.get(end)
            if w is None:                       # mid-construction
                continue
            if w['enable'].isChecked():
                ends.append({'end': end,
                             'length': w['length'].getValue(),
                             'endDiameter': w['endDiameter'].getValue(),
                             'profile': w['profile'].currentText().lower()})
        return ends

    def _taperToggled(self, on):
        """Show the aft column + profile + preview toggle only when the taper
        is enabled."""
        on = bool(on)
        for editor in (self._taperAftEditors or {}).values():
            editor.setVisible(on)
        if hasattr(self, 'taperColHeader'):
            self.form.setRowVisible(self.taperColHeader, on)
        if hasattr(self, 'taperProfile'):
            self.taperProfile.setVisible(on)
            self.taperProfileLabel.setVisible(on)
        if hasattr(self, 'taperPreviewRow'):
            self.form.setRowVisible(self.taperPreviewRow, on)
        self.propertyUpdate()

    def loadMotorConfig(self, motor, activeSolver, pyrogenNames=None):
        """Edit the motor's config (grain-table 'Config' row): the solver-aware
        layout (shared + the active solver's settings) plus, for igniter-capable
        solvers (srm_1d), a Pyrogen picker and the Igniter-chamber section.
        Mirrors the Preferences screen; scoped to this motor."""
        self.configMotor = motor
        self.objType = motorlib.motor.MotorConfig
        self._pyrogenNames = list(pyrogenNames or [])
        self.expRatioLabel.hide()
        self.nozzlePreview.hide()
        self.grainPreview.hide()

        self.controller = SolverConfigController(
            self, motor.config, motor.solverConfigs, igniterSource=motor.igniter)

        self.solverSelector.blockSignals(True)
        self.solverSelector.clear()
        self.solverSelector.addItems(self.controller.solverNames())
        if activeSolver in self.controller.specificColls:
            self.solverSelector.setCurrentText(activeSolver)
        self.solverSelector.blockSignals(False)

        self._showConfigPage(self.solverSelector.currentText())
        self.solverSelectorContainer.show()

    def _showConfigPage(self, name):
        """Render the config page for solver ``name``; set up the igniter
        extras (pyrogen picker + auto/conditional chamber fields) if it uses
        an igniter, else hide the pyrogen picker."""
        self.controller.show(name)
        if self.controller.usesIgniter(name):
            current = self.configMotor.igniterPyrogen.getProperty('name')
            names = list(self._pyrogenNames)
            if current and current not in names:
                names.insert(0, current)
            self.pyrogenSelector.blockSignals(True)
            self.pyrogenSelector.clear()
            self.pyrogenSelector.addItems(names)
            if current in names:
                self.pyrogenSelector.setCurrentText(current)
            self.pyrogenSelector.blockSignals(False)
            self.pyrogenSelectorContainer.show()
            self._setupIgniterFormExtras()
        else:
            self.pyrogenSelectorContainer.hide()

    def setActiveSolver(self, name):
        """Sync the dropdown when the active solver changes elsewhere (no-op
        unless the config editor is open)."""
        if self.configMotor is None or name not in self.controller.specificColls:
            return
        if self.solverSelector.currentText() != name:
            self.solverSelector.setCurrentText(name)

    def _solverChanged(self, name):
        if self.controller is not None and self.configMotor is not None:
            self._showConfigPage(name)
        if name and self.configMotor is not None:
            self.activeSolverChanged.emit(name)

    def apply(self):
        if self.configMotor is not None:
            general, solverConfigs = self.controller.extract()
            usesIgniter = self.controller.usesIgniter(
                self.solverSelector.currentText())
            igniterProps = (self.controller.igniterProps() or {}) if usesIgniter else {}
            pyrogenName = self.pyrogenSelector.currentText() if usesIgniter else ''
            # "auto" (spin at 0, or any non-positive entry) -> -1 sentinel.
            for key in self._IGNITER_AUTO_FIELDS:
                if key in igniterProps and igniterProps[key] <= 0.0:
                    igniterProps[key] = -1.0
            self.configMotor = None
            self.controller = None
            self.solverSelectorContainer.hide()
            self.pyrogenSelectorContainer.hide()
            self.cleanup()
            self.motorConfigApplied.emit(general, solverConfigs, pyrogenName,
                                         igniterProps)
            self.closed.emit()
        else:
            super().apply()

    def close(self):
        # Canceling/closing the config editor must drop the config state and
        # hide the solver/pyrogen selectors, so they don't linger above the
        # grain area (and can't re-open config when the dropdown is changed).
        self.configMotor = None
        self.controller = None
        self.solverSelectorContainer.hide()
        self.pyrogenSelectorContainer.hide()
        super().close()

    def cleanup(self):
        self.expRatioLabel.hide()
        self.grainPreview.hide()
        self.nozzlePreview.hide()
        self.grainPreview.cleanup()
        # Drop taper-editor state so getProperties / preview don't act on a
        # stale grain after switching to a nozzle/config object.
        self._taperAftEditors = None
        self._odWidgets = None
        super().cleanup()
