"""Parsing and unit detection for user-imported CSV data (e.g. a static-fire
thrust/pressure trace) that the results plot overlays on the simulated curves.

This module is pure Python/NumPy (no Qt) so it can be unit-tested directly.

Unit detection never guesses: a unit is only assigned when the header carries a
recognised unit token. Otherwise the column is flagged ``unit=None`` and the
GUI labels it "(units unknown)" and plots raw values."""

import csv
import io
import os
import re

import numpy as np

import motorlib.units


class ImportedDataError(Exception):
    """Raised for an unusable file; the message is shown to the user as-is."""


# Extra units openMotor's table doesn't carry: token -> (label, base unit, factor to base).
# Base units are openMotor's internal units, so every column can then be
# converted to the user's display unit with motorlib.units.
_EXTRA_UNITS = {
    'kpa': ('kPa', 'Pa', 1e3), 'bar': ('bar', 'Pa', 1e5),
    'kn': ('kN', 'N', 1e3),
    'ms': ('ms', 's', 1e-3), 'min': ('min', 's', 60.0),
}

# Spellings (lower-cased, whitespace removed) -> canonical openMotor unit label.
# 'lbs' is deliberately absent (ambiguous: mass vs force).
_ALIASES = {
    's': 's', 'sec': 's', 'secs': 's', 'second': 's', 'seconds': 's',
    'n': 'N', 'newton': 'N', 'newtons': 'N',
    'lbf': 'lbf',
    'pa': 'Pa', 'mpa': 'MPa', 'psi': 'psi', 'pascal': 'Pa', 'pascals': 'Pa',
    'm': 'm', 'cm': 'cm', 'mm': 'mm', 'in': 'in', 'ft': 'ft',
    'kg': 'kg', 'g': 'g', 'lb': 'lb', 'oz': 'oz',
    'ns': 'Ns', 'n*s': 'Ns', 'n-s': 'Ns', 'lbfs': 'lbfs', 'lbf*s': 'lbfs',
    'm/s': 'm/s', 'cm/s': 'cm/s', 'mm/s': 'mm/s', 'ft/s': 'ft/s', 'in/s': 'in/s',
    'kg/s': 'kg/s', 'g/s': 'g/s', 'lb/s': 'lb/s',
}


def lookupUnit(token):
    """Return ``(baseUnit, factorToBase, label)`` for a unit string, or None if
    it is not a unit we know. ``factorToBase`` multiplies raw values to give
    openMotor's internal unit (``baseUnit``)."""
    key = re.sub(r'\s+', '', str(token)).lower()
    if key in _EXTRA_UNITS:
        label, base, factor = _EXTRA_UNITS[key]
        return base, factor, label
    canon = _ALIASES.get(key)
    if canon is None:
        return None
    if canon in motorlib.units.unitLabels or canon == 's':
        return canon, 1.0, canon
    for base in motorlib.units.unitLabels:
        if canon in motorlib.units.getAllConversions(base):
            return base, 1.0 / motorlib.units.getConversion(base, canon), canon
    return None


_BRACKETS = re.compile(r'[\(\[\{]([^\)\]\}]*)[\)\]\}]')
_TRAILING = re.compile(r'^(.*?)(?:\s+[-–—]\s*|_|\s+)([^\s_]+)$')


def splitHeader(header):
    """Split a column header into ``(name, unitInfo)``. ``unitInfo`` is the
    result of :func:`lookupUnit` or None. Recognised forms: ``Name (unit)``,
    ``Name [unit]``, ``Name (note, unit)``, ``Name - unit``, ``Name_unit``,
    ``Name unit``. The unit text is removed from ``name`` only when recognised."""
    header = header.strip()
    for m in reversed(list(_BRACKETS.finditer(header))):
        for part in reversed(m.group(1).split(',')):
            info = lookupUnit(part)
            if info:
                name = (header[:m.start()] + header[m.end():]).strip(' -_')
                return (name or header), info
    m = _TRAILING.match(header)
    if m:
        info = lookupUnit(m.group(2))
        if info:
            return (m.group(1).strip() or header), info
    return header, None


class ImportedColumn:
    def __init__(self, header, name, values, unitInfo):
        self.header = header          # original header text
        self.name = name              # header without the unit text
        self.values = values          # raw numpy array (as in the file)
        self.unitInfo = unitInfo      # (baseUnit, factorToBase, label) or None

    @property
    def unitKnown(self):
        return self.unitInfo is not None

    @property
    def baseUnit(self):
        return self.unitInfo[0] if self.unitInfo else None

    @property
    def unitLabel(self):
        return self.unitInfo[2] if self.unitInfo else None

    @property
    def displayName(self):
        """Selector text: 'Pressure (psi)' or 'Pressure (units unknown)'."""
        return '{} ({})'.format(self.name, self.unitLabel if self.unitKnown else 'units unknown')

    def converted(self, displayUnit=None):
        """``(values, unitLabel)`` in ``displayUnit`` (a unit openMotor can
        convert the base unit to). An unknown unit gives the raw values and
        label None; an unavailable conversion gives the base-unit values."""
        if not self.unitKnown:
            return self.values, None
        base, factor, _label = self.unitInfo
        vals = self.values * factor
        if displayUnit and displayUnit != base:
            try:
                return vals * motorlib.units.getConversion(base, displayUnit), displayUnit
            except KeyError:
                pass
        return vals, base


class ImportedData:
    def __init__(self, path, timeColumn, columns):
        self.path = path
        self.filename = os.path.basename(path)
        self.timeColumn = timeColumn  # ImportedColumn
        self.columns = columns        # list of ImportedColumn (excluding time)

    def timeSeconds(self):
        """Time in seconds, or the raw values if the time unit is not
        recognised (they are then plotted as-is on the time axis)."""
        return self.timeColumn.converted('s')[0]


def _isTimeName(name):
    n = name.strip().lower()
    return n == 't' or n.startswith('time') or n in ('seconds', 'sec')


def _isNumber(cell):
    try:
        float(cell)
        return True
    except ValueError:
        return False


def parseCsvText(text, path='data.csv'):
    """Parse CSV text into an :class:`ImportedData`. Raises
    :class:`ImportedDataError` with a user-readable message on bad input."""
    text = text.lstrip('﻿')
    delim = ','
    try:
        delim = csv.Sniffer().sniff(text[:4096], delimiters=',;\t').delimiter
    except csv.Error:
        pass
    rows = [r for r in csv.reader(io.StringIO(text), delimiter=delim)
            if any(c.strip() for c in r)]
    if not rows:
        raise ImportedDataError('The file is empty.')
    header = [h.strip() for h in rows[0]]
    if all(_isNumber(h) for h in header if h):
        raise ImportedDataError('The first row looks like data, not column names. '
                                'The file needs a header row (e.g. "Time (s),Thrust (N)").')
    if len(header) < 2:
        raise ImportedDataError('The file has only one column. It needs a time column '
                                'and at least one data column.')
    body = rows[1:]
    if len(body) < 2:
        raise ImportedDataError('The file needs at least two data rows.')
    ncol = len(header)
    data = np.empty((len(body), ncol))
    for i, row in enumerate(body):
        if len(row) != ncol:
            raise ImportedDataError('Data row {} has {} cells but the header has {} columns.'
                                    .format(i + 2, len(row), ncol))
        for j, cell in enumerate(row):
            cell = cell.strip()
            if cell == '':
                data[i, j] = np.nan
                continue
            try:
                data[i, j] = float(cell)
            except ValueError:
                raise ImportedDataError('Non-numeric value "{}" in row {}, column "{}".'
                                        .format(cell, i + 2, header[j]))
    cols = []
    for j, h in enumerate(header):
        name, info = splitHeader(h if h else 'Column {}'.format(j + 1))
        cols.append(ImportedColumn(h, name, data[:, j].copy(), info))
    timeIdx = next((j for j, c in enumerate(cols) if _isTimeName(c.name)), 0)
    timeCol = cols[timeIdx]
    if np.isnan(timeCol.values).any():
        raise ImportedDataError('The time column "{}" has empty cells.'.format(timeCol.header))
    dataCols = [c for j, c in enumerate(cols) if j != timeIdx and not np.isnan(c.values).all()]
    if not dataCols:
        raise ImportedDataError('No data columns with values were found.')
    return ImportedData(path, timeCol, dataCols)


def loadCsv(path):
    """Read and parse a CSV file (UTF-8 with or without BOM, else latin-1)."""
    try:
        with open(path, 'rb') as f:
            raw = f.read()
    except OSError as e:
        raise ImportedDataError('Could not read the file: {}'.format(e))
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = raw.decode('latin-1')
    return parseCsvText(text, path)
