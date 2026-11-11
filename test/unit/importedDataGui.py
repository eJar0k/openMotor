import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest

try:
    from PyQt6.QtWidgets import QApplication
    import motorlib.motor
    import motorlib.grains
    import motorlib.propellant
    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False


def _ensureUi():
    """The *_ui.py files are generated (gitignored); build any that are missing."""
    from PyQt6 import uic
    views = os.path.join(os.path.dirname(__file__), '..', '..', 'uilib', 'views')
    forms = os.path.join(views, 'forms')
    for name in os.listdir(forms):
        if name.endswith('.ui'):
            out = os.path.join(views, name[:-3] + '_ui.py')
            if not os.path.isfile(out):
                with open(out, 'w', encoding='utf-8') as f:
                    uic.compileUi(os.path.join(forms, name), f)


def _simResult():
    from uilib.fileIO import loadFile, fileTypes
    path = os.path.join(os.path.dirname(__file__), '..', 'data', 'regression', 'c', 'motor.ric')
    return motorlib.motor.Motor(loadFile(path, fileTypes.MOTOR)).runSimulation()


@unittest.skipUnless(HAVE_QT, 'PyQt6 not available')
class TestImportedOverlay(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        if not hasattr(cls.app, 'isDarkMode'):   # openMotor's app subclass provides this
            cls.app.isDarkMode = lambda: False

    def test_load_toggle_draw_clear(self):
        _ensureUi()
        from uilib.widgets.resultsWidget import ResultsWidget
        from uilib.preferencesManager import Preferences
        w = ResultsWidget(None)
        w.setPreferences(Preferences())
        sel = w.importedSelector
        errors = []
        sel._showError = errors.append  # no modal box offscreen

        with tempfile.TemporaryDirectory() as d:
            good = os.path.join(d, 'good.csv')
            with open(good, 'w') as f:
                f.write('Time (s),Thrust (N),Pressure (psi),Mystery\n0,0,0,1\n1,500,400,2\n2,0,0,3\n')
            bad = os.path.join(d, 'bad.csv')
            with open(bad, 'w') as f:
                f.write('time,a\n0,1\n1,x\n')

            self.assertTrue(sel.loadFile(good))
            self.assertEqual(len(sel.childChecks), 3)
            self.assertFalse(sel.loadFile(bad))   # bad file: message, previous data kept
            self.assertEqual(len(errors), 1)
            self.assertEqual(len(sel.childChecks), 3)

            w.showData(_simResult())
            ax = w.ui.widgetGraph.plot
            nAll = len(ax.lines)
            labels = [t.get_text() for t in ax.get_legend().get_texts()]
            self.assertTrue(any('Imported: Mystery - (units unknown)' in t for t in labels))
            self.assertTrue(any(t.startswith('Imported: Pressure - ') for t in labels))

            sel.childChecks[2].setChecked(False)   # toggle a child
            self.assertEqual(len(ax.lines), nAll - 1)
            sel.parentCheck.setChecked(False)
            self.assertEqual(len(ax.lines), nAll - 3)
            sel.parentCheck.setChecked(True)       # data kept: no dialog
            self.assertEqual(len(ax.lines), nAll - 1)

            # Persists across re-simulation.
            w.resetPlot()
            w.showData(_simResult())
            self.assertEqual(len(w.ui.widgetGraph.plot.lines), nAll - 1)

            sel.clear()
            self.assertIsNone(sel.data)
            self.assertEqual(len(w.ui.widgetGraph.plot.lines), nAll - 3)

    def test_saved_image_includes_the_overlay(self):
        """File > Export > Image File draws the imported curves exactly as the results plot does."""
        _ensureUi()
        from types import SimpleNamespace
        from PyQt6.QtGui import QIcon
        from uilib.widgets.resultsWidget import ResultsWidget
        from uilib.preferencesManager import Preferences
        from uilib.converters.imageExporter import ImageExporter
        self.app.icon = QIcon()   # the export dialog reads the app icon
        w = ResultsWidget(None)
        w.setPreferences(Preferences())
        w.importedSelector._showError = lambda *_: None
        simRes = _simResult()
        w.showData(simRes)
        manager = SimpleNamespace(
            simRes=simRes,
            app=SimpleNamespace(window=SimpleNamespace(ui=SimpleNamespace(resultsWidget=w))))
        exporter = ImageExporter(manager)
        graph = w.ui.widgetGraph

        # Record what is on the axes at the moment savefig is called.
        saved = []
        realSave = graph.figure.savefig

        def spy(path, *a, **k):
            ax = graph.plot
            saved.append(([l.get_linestyle() for l in ax.lines],
                          [t.get_text() for t in ax.get_legend().get_texts()]))
            return realSave(path, *a, **k)
        graph.figure.savefig = spy

        with tempfile.TemporaryDirectory() as d:
            plain = os.path.join(d, 'plain.png')
            exporter.doConversion(plain, ['time', ['pressure', 'force'], [0]])
            self.assertEqual(len(saved[-1][0]), 2)
            self.assertFalse(any(t.startswith('Imported') for t in saved[-1][1]))

            csv = os.path.join(d, 'good.csv')
            with open(csv, 'w') as f:
                f.write('Time (s),Thrust (N),Pressure (psi),Mystery\n0,0,0,1\n1,500,400,2\n2,0,0,3\n')
            self.assertTrue(w.importedSelector.loadFile(csv))
            w.drawGraphs()
            screen = ([l.get_linestyle() for l in graph.plot.lines][-3:],
                      [t.get_text() for t in graph.plot.get_legend().get_texts()][-3:])

            withOverlay = os.path.join(d, 'overlay.png')
            exporter.doConversion(withOverlay, ['time', ['pressure', 'force'], [0]])
            styles, labels = saved[-1]
            self.assertEqual(len(styles), 5)
            # the three imported curves are dashed and labelled exactly as on screen
            self.assertEqual((styles[-3:], labels[-3:]), screen)
            self.assertEqual(styles[-3:], ['--'] * 3)
            self.assertTrue(all(t.startswith('Imported: ') for t in labels[-3:]))
            self.assertNotEqual(os.path.getsize(plain), os.path.getsize(withOverlay))

            # only the columns ticked on screen are exported
            w.importedSelector.childChecks[2].setChecked(False)
            exporter.doConversion(os.path.join(d, 'two.png'), ['time', ['pressure', 'force'], [0]])
            self.assertEqual(len(saved[-1][0]), 4)

            # the on-screen plot is left as it was (savefig clears only after drawing)
            self.assertEqual(w.importedOverlay()[1], w.importedSelector.getSelectedColumns())
            exporter.doConversion(os.path.join(d, 'x.png'), ['time', ['pressure'], [0]])
            self.assertEqual(len(saved[-1][0]), 1 + 2)


if __name__ == '__main__':
    unittest.main()
