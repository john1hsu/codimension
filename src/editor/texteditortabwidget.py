# -*- coding: utf-8 -*-
#
# codimension - graphics python two-way code editor and analyzer
# Copyright (C) 2010-2017  Sergey Satskiy <sergey.satskiy@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

"""Text editor tab widget"""


import os.path
import logging
from ui.qt import (Qt, QFileInfo, QSize, pyqtSignal, QToolBar, QHBoxLayout,
                   QWidget, QAction, QMenu, QSizePolicy, QToolButton, QDialog,
                   QVBoxLayout, QSplitter)
from ui.mainwindowtabwidgetbase import MainWindowTabWidgetBase
from ui.runparams import RunDialog
from ui.linecounter import LineCounterDialog
from ui.importlist import ImportListWidget
from ui.outsidechanges import OutsideChangeWidget
from utils.pixmapcache import getIcon
from utils.globals import GlobalData
from utils.settings import Settings
from utils.fileutils import isPythonMime
from utils.diskvaluesrelay import getRunParameters, addRunParams
from utils.importutils import (getImportsList, getImportsInLine, resolveImport,
                               getImportedNameDefinitionLine, resolveImports)
from diagram.importsdgm import (ImportsDiagramDialog, ImportDiagramOptions,
                                ImportsDiagramProgress)
from autocomplete.bufferutils import isImportLine
from debugger.modifiedunsaved import ModifiedUnsavedDialog
from profiling.profui import ProfilingProgressDialog
from debugger.bputils import getBreakpointLines
from .flowuiwidget import FlowUIWidget
from .navbar import NavigationBar
from .texteditor import TextEditor


class TextEditorTabWidget(QWidget, MainWindowTabWidgetBase):

    """Plain text editor tab widget"""

    textEditorZoom = pyqtSignal(int)
    reloadRequest = pyqtSignal()
    reloadAllNonModifiedRequest = pyqtSignal()
    sigTabRunChanged = pyqtSignal(bool)

    def __init__(self, parent, debugger):
        MainWindowTabWidgetBase.__init__(self)
        QWidget.__init__(self, parent)

        self.__navigationBar = None
        self.__editor = TextEditor(self, debugger)
        self.__fileName = ""
        self.__shortName = ""

        self.__createLayout()
        self.__editor.zoomTo(Settings()['zoom'])

        self.__editor.redoAvailable.connect(self.__redoAvailable)
        self.__editor.undoAvailable.connect(self.__undoAvailable)
        self.__editor.modificationChanged.connect(self.modificationChanged)
        self.__editor.cflowSyncRequested.connect(self.cflowSyncRequested)

        self.__diskModTime = None
        self.__diskSize = None
        self.__reloadDlgShown = False

        self.__debugMode = False
        self.__breakableLines = None

        self.__vcsStatus = None

    def getNavigationBar(self):
        """Provides a reference to the navigation bar"""
        return self.__navigationBar

    def shouldAcceptFocus(self):
        """True if it can accept the focus"""
        return self.__outsideChangesBar.isHidden()

    def readFile(self, fileName):
        """Reads the text from a file"""
        self.__editor.readFile(fileName)
        self.setFileName(fileName)
        self.__editor.restoreBreakpoints()

        # Memorize the modification date
        path = os.path.realpath(fileName)
        self.__diskModTime = os.path.getmtime(path)
        self.__diskSize = os.path.getsize(path)

    def writeFile(self, fileName):
        """Writes the text to a file"""
        if self.__editor.writeFile(fileName):
            # Memorize the modification date
            path = os.path.realpath(fileName)
            self.__diskModTime = os.path.getmtime(path)
            self.__diskSize = os.path.getsize(path)
            self.setFileName(fileName)
            self.__editor.restoreBreakpoints()
            return True
        return False

    def __createLayout(self):
        """Creates the toolbar and layout"""
        # Buttons
        printButton = QAction(getIcon('printer.png'), 'Print', self)
        printButton.triggered.connect(self.__onPrint)
        printButton.setEnabled(False)
        printButton.setVisible(False)

        printPreviewButton = QAction(getIcon('printpreview.png'),
                                     'Print preview', self)
        printPreviewButton.triggered.connect(self.__onPrintPreview)
        printPreviewButton.setEnabled(False)
        printPreviewButton.setVisible(False)

        # Imports diagram and its menu
        importsMenu = QMenu(self)
        importsDlgAct = importsMenu.addAction(
            getIcon('detailsdlg.png'), 'Fine tuned imports diagram')
        importsDlgAct.triggered.connect(self.onImportDgmTuned)
        self.importsDiagramButton = QToolButton(self)
        self.importsDiagramButton.setIcon(getIcon('importsdiagram.png'))
        self.importsDiagramButton.setToolTip('Generate imports diagram')
        self.importsDiagramButton.setPopupMode(QToolButton.DelayedPopup)
        self.importsDiagramButton.setMenu(importsMenu)
        self.importsDiagramButton.setFocusPolicy(Qt.NoFocus)
        self.importsDiagramButton.clicked.connect(self.onImportDgm)
        self.importsDiagramButton.setEnabled(False)

        # Run script and its menu
        runScriptMenu = QMenu(self)
        runScriptDlgAct = runScriptMenu.addAction(
            getIcon('detailsdlg.png'), 'Set run/debug parameters')
        runScriptDlgAct.triggered.connect(self.onRunScriptSettings)
        self.runScriptButton = QToolButton(self)
        self.runScriptButton.setIcon(getIcon('run.png'))
        self.runScriptButton.setToolTip('Run script')
        self.runScriptButton.setPopupMode(QToolButton.DelayedPopup)
        self.runScriptButton.setMenu(runScriptMenu)
        self.runScriptButton.setFocusPolicy(Qt.NoFocus)
        self.runScriptButton.clicked.connect(self.onRunScript)
        self.runScriptButton.setEnabled(False)

        # Profile script and its menu
        profileScriptMenu = QMenu(self)
        profileScriptDlgAct = profileScriptMenu.addAction(
            getIcon('detailsdlg.png'), 'Set profile parameters')
        profileScriptDlgAct.triggered.connect(self.onProfileScriptSettings)
        self.profileScriptButton = QToolButton(self)
        self.profileScriptButton.setIcon(getIcon('profile.png'))
        self.profileScriptButton.setToolTip('Profile script')
        self.profileScriptButton.setPopupMode(QToolButton.DelayedPopup)
        self.profileScriptButton.setMenu(profileScriptMenu)
        self.profileScriptButton.setFocusPolicy(Qt.NoFocus)
        self.profileScriptButton.clicked.connect(self.onProfileScript)
        self.profileScriptButton.setEnabled(False)

        # Debug script and its menu
        debugScriptMenu = QMenu(self)
        debugScriptDlgAct = debugScriptMenu.addAction(
            getIcon('detailsdlg.png'), 'Set run/debug parameters')
        debugScriptDlgAct.triggered.connect(self.onDebugScriptSettings)
        self.debugScriptButton = QToolButton(self)
        self.debugScriptButton.setIcon(getIcon('debugger.png'))
        self.debugScriptButton.setToolTip('Debug script')
        self.debugScriptButton.setPopupMode(QToolButton.DelayedPopup)
        self.debugScriptButton.setMenu(debugScriptMenu)
        self.debugScriptButton.setFocusPolicy(Qt.NoFocus)
        self.debugScriptButton.clicked.connect(self.onDebugScript)
        self.debugScriptButton.setEnabled(False)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.__undoButton = QAction(getIcon('undo.png'), 'Undo (Ctrl+Z)', self)
        self.__undoButton.setShortcut('Ctrl+Z')
        self.__undoButton.triggered.connect(self.__editor.onUndo)
        self.__undoButton.setEnabled(False)

        self.__redoButton = QAction(getIcon('redo.png'), 'Redo (Ctrl+Y)', self)
        self.__redoButton.setShortcut('Ctrl+Y')
        self.__redoButton.triggered.connect(self.__editor.onRedo)
        self.__redoButton.setEnabled(False)

        self.lineCounterButton = QAction(
            getIcon('linecounter.png'), 'Line counter', self)
        self.lineCounterButton.triggered.connect(self.onLineCounter)

        self.removeTrailingSpacesButton = QAction(
            getIcon('trailingws.png'), 'Remove trailing spaces', self)
        self.removeTrailingSpacesButton.triggered.connect(
            self.onRemoveTrailingWS)
        self.expandTabsButton = QAction(
            getIcon('expandtabs.png'), 'Expand tabs (4 spaces)', self)
        self.expandTabsButton.triggered.connect(self.onExpandTabs)

        # The toolbar
        toolbar = QToolBar(self)
        toolbar.setOrientation(Qt.Vertical)
        toolbar.setMovable(False)
        toolbar.setAllowedAreas(Qt.RightToolBarArea)
        toolbar.setIconSize(QSize(16, 16))
        toolbar.setFixedWidth(28)
        toolbar.setContentsMargins(0, 0, 0, 0)

        toolbar.addAction(printPreviewButton)
        toolbar.addAction(printButton)
        toolbar.addWidget(self.importsDiagramButton)
        toolbar.addWidget(self.runScriptButton)
        toolbar.addWidget(self.profileScriptButton)
        toolbar.addWidget(self.debugScriptButton)
        toolbar.addAction(self.__undoButton)
        toolbar.addAction(self.__redoButton)
        toolbar.addWidget(spacer)
        toolbar.addAction(self.lineCounterButton)
        toolbar.addAction(self.removeTrailingSpacesButton)
        toolbar.addAction(self.expandTabsButton)

        self.__importsBar = ImportListWidget(self.__editor)
        self.__importsBar.hide()

        self.__outsideChangesBar = OutsideChangeWidget(self.__editor)
        self.__outsideChangesBar.reloadRequest.connect(self.__onReload)
        self.__outsideChangesBar.reloadAllNonModifiedRequest.connect(
            self.reloadAllNonModified)
        self.__outsideChangesBar.hide()

        hLayout = QHBoxLayout()
        hLayout.setContentsMargins(0, 0, 0, 0)
        hLayout.setSpacing(0)

        vLayout = QVBoxLayout()
        vLayout.setContentsMargins(0, 0, 0, 0)
        vLayout.setSpacing(0)

        self.__navigationBar = NavigationBar(self.__editor, self)
        vLayout.addWidget(self.__navigationBar)
        vLayout.addWidget(self.__editor)

        hLayout.addLayout(vLayout)
        hLayout.addWidget(toolbar)
        widget = QWidget()
        widget.setLayout(hLayout)

        self.__splitter = QSplitter(Qt.Horizontal, self)
        self.__flowUI = FlowUIWidget(self.__editor, self)
        self.__splitter.addWidget(widget)
        self.__splitter.addWidget(self.__flowUI)

        containerLayout = QHBoxLayout()
        containerLayout.setContentsMargins(0, 0, 0, 0)
        containerLayout.setSpacing(0)
        containerLayout.addWidget(self.__splitter)
        self.setLayout(containerLayout)

        self.__splitter.setSizes(Settings()['flowSplitterSizes'])
        self.__splitter.splitterMoved.connect(self.flowSplitterMoved)
        Settings().sigFlowSplitterChanged.connect(self.otherFlowSplitterMoved)

    # Arguments: pos, index
    def flowSplitterMoved(self, _, __):
        """Splitter has been moved"""
        Settings()['flowSplitterSizes'] = list(self.__splitter.sizes())

    def otherFlowSplitterMoved(self):
        """Other window has changed the splitter position"""
        self.__splitter.setSizes(Settings()['flowSplitterSizes'])

    def updateStatus(self):
        """Updates the toolbar buttons status"""
        self.__updateRunDebugButtons()
        isPythonFile = isPythonMime(self.__editor.mime)
        self.importsDiagramButton.setEnabled(
            isPythonFile and GlobalData().graphvizAvailable)
        self.__editor.diagramsMenu.setEnabled(
            self.importsDiagramButton.isEnabled())
        self.__editor.toolsMenu.setEnabled(self.runScriptButton.isEnabled())
        self.lineCounterButton.setEnabled(isPythonFile)

    def onNavigationBar(self):
        """Triggered when navigation bar focus is requested"""
        if self.__navigationBar.isVisible():
            self.__navigationBar.setFocusToLastCombo()
        return True

    def __onPrint(self):
        """Triggered when the print button is pressed"""
        pass

    def __onPrintPreview(self):
        """triggered when the print preview button is pressed"""
        pass

    def __redoAvailable(self, available):
        """Reports redo ops available"""
        self.__redoButton.setEnabled(available)

    def __undoAvailable(self, available):
        """Reports undo ops available"""
        self.__undoButton.setEnabled(available)

    # Arguments: modified
    def modificationChanged(self, _=None):
        """Triggered when the content is changed"""
        self.__updateRunDebugButtons()

    def __updateRunDebugButtons(self):
        """Enables/disables the run and debug buttons as required"""
        enable = isPythonMime(self.__editor.mime) and \
                 not self.isModified() and \
                 not self.__debugMode and \
                 os.path.isabs(self.__fileName)

        if enable != self.runScriptButton.isEnabled():
            self.runScriptButton.setEnabled(enable)
            self.profileScriptButton.setEnabled(enable)
            self.debugScriptButton.setEnabled(enable)
            self.sigTabRunChanged.emit(enable)

    def isTabRunEnabled(self):
        """Tells the status of run-like buttons"""
        return self.runScriptButton.isEnabled()

    def replaceAll(self, newText):
        """Replaces the current buffer content with a new text"""
        # Unfortunately, the setText() clears the undo history so it cannot be
        # used. The selectAll() and replacing selected text do not suite
        # because after undo the cursor does not jump to the previous position.
        # So, there is an ugly select -> replace manipulation below...
        with self.__editor:
            origLine, origPos = self.__editor.cursorPosition
            self.__editor.setSelection(0, 0, origLine, origPos)
            self.__editor.removeSelectedText()
            self.__editor.insert(newText)
            self.__editor.setCurrentPosition(len(newText))
            line, pos = self.__editor.cursorPosition
            lastLine = self.__editor.lines()
            self.__editor.setSelection(line, pos,
                                       lastLine - 1,
                                       len(self.__editor.text(lastLine - 1)))
            self.__editor.removeSelectedText()
            self.__editor.cursorPosition = origLine, origPos

            # These two for the proper cursor positioning after redo
            self.__editor.insert("s")
            self.__editor.cursorPosition = origLine, origPos + 1
            self.__editor.deleteBack()
            self.__editor.cursorPosition = origLine, origPos

    def onLineCounter(self):
        """Triggered when line counter button is clicked"""
        LineCounterDialog(None, self.__editor).exec_()

    def onRemoveTrailingWS(self):
        """Triggers when the trailing spaces should be wiped out"""
        self.__editor.removeTrailingWhitespaces()

    def onExpandTabs(self):
        """Expands tabs if there are any"""
        self.__editor.expandTabs(4)

    def setFocus(self):
        """Overridden setFocus"""
        if self.__outsideChangesBar.isHidden():
            self.__editor.setFocus()
        else:
            self.__outsideChangesBar.setFocus()

    def onImportDgmTuned(self):
        """Runs the settings dialog first"""
        if self.isModified():
            what = ImportsDiagramDialog.SingleBuffer
            if not os.path.isabs(self.getFileName()):
                logging.warning("Imports diagram can only be generated for "
                                "a file. Save the editor buffer "
                                "and try again.")
                return
        else:
            what = ImportsDiagramDialog.SingleFile
        dlg = ImportsDiagramDialog(what, self.getFileName(), self)
        if dlg.exec_() == QDialog.Accepted:
            # Should proceed with the diagram generation
            self.__generateImportDiagram(what, dlg.options)

    # Arguments: action
    def onImportDgm(self, _=None):
        """Runs the generation process with default options"""
        if self.isModified():
            what = ImportsDiagramDialog.SingleBuffer
            if not os.path.isabs(self.getFileName()):
                logging.warning("Imports diagram can only be generated for "
                                "a file. Save the editor buffer "
                                "and try again.")
                return
        else:
            what = ImportsDiagramDialog.SingleFile
        self.__generateImportDiagram(what, ImportDiagramOptions())

    def __generateImportDiagram(self, what, options):
        """Show the generation progress and display the diagram"""
        if self.isModified():
            progressDlg = ImportsDiagramProgress(what, options,
                                                 self.getFileName(),
                                                 self.__editor.text)
            tooltip = "Generated for modified buffer (" + \
                      self.getFileName() + ")"
        else:
            progressDlg = ImportsDiagramProgress(what, options,
                                                 self.getFileName())
            tooltip = "Generated for file " + self.getFileName()
        if progressDlg.exec_() == QDialog.Accepted:
            GlobalData().mainWindow.openDiagram(progressDlg.scene,
                                                tooltip)

    def onOpenImport(self):
        """Triggered when Ctrl+I is received"""
        if not isPythonMime(self.__editor.mime):
            return True

        # Python file, we may continue
        importLine, lineNo = isImportLine(self.__editor)
        basePath = os.path.dirname(self.__fileName)

        if importLine:
            lineImports, importWhat = getImportsInLine(self.__editor.text,
                                                       lineNo + 1)
            currentWord = self.__editor.getCurrentWord(".")
            if currentWord in lineImports:
                # The cursor is on some import
                path = resolveImport(basePath, currentWord)
                if path != '':
                    GlobalData().mainWindow.openFile(path, -1)
                    return True
                GlobalData().mainWindow.showStatusBarMessage(
                    "The import '" + currentWord + "' is not resolved.")
                return True
            # We are not on a certain import.
            # Check if it is a line with exactly one import
            if len(lineImports) == 1:
                path = resolveImport(basePath, lineImports[0])
                if path == '':
                    GlobalData().mainWindow.showStatusBarMessage(
                        "The import '" + lineImports[0] +
                        "' is not resolved")
                    return True
                # The import is resolved. Check where we are.
                if currentWord in importWhat:
                    # We are on a certain imported name in a resolved import
                    # So, jump to the definition line
                    line = getImportedNameDefinitionLine(path, currentWord)
                    GlobalData().mainWindow.openFile(path, line)
                    return True
                GlobalData().mainWindow.openFile(path, -1)
                return True

            # Take all the imports in the line and resolve them.
            self.__onImportList(basePath, lineImports)
            return True

        # Here: the cursor is not on the import line. Take all the file imports
        # and resolve them
        fileImports = getImportsList(self.__editor.text)
        if not fileImports:
            GlobalData().mainWindow.showStatusBarMessage(
                "There are no imports.")
            return True
        if len(fileImports) == 1:
            path = resolveImport(basePath, fileImports[0])
            if path == '':
                GlobalData().mainWindow.showStatusBarMessage(
                    "The import '" + fileImports[0] + "' is not resolved")
                return True
            GlobalData().mainWindow.openFile(path, -1)
            return True

        self.__onImportList(basePath, fileImports)
        return True

    def __onImportList(self, basePath, imports):
        """Works with a list of imports"""
        # It has already been checked that the file is a Python one
        resolvedList = resolveImports(basePath, imports)
        if not resolvedList:
            GlobalData().mainWindow.showStatusBarMessage(
                "No imports are resolved.")
            return

        # Display the import selection widget
        self.__importsBar.showResolvedList(resolvedList)

    def resizeEvent(self, event):
        """Resizes the import selection dialogue if necessary"""
        self.__editor.hideCompleter()
        QWidget.resizeEvent(self, event)
        self.resizeBars()

    def resizeBars(self):
        """Resize the bars if they are shown"""
        if not self.__importsBar.isHidden():
            self.__importsBar.resize()
        if not self.__outsideChangesBar.isHidden():
            self.__outsideChangesBar.resize()
        self.__editor.resizeCalltip()

    def showOutsideChangesBar(self, allEnabled):
        """Shows the bar for the editor for the user to choose the action"""
        self.setReloadDialogShown(True)
        self.__outsideChangesBar.showChoice(self.isModified(),
                                            allEnabled)

    def __onReload(self):
        """Triggered when a request to reload the file is received"""
        self.reloadRequest.emit()

    def reload(self):
        """Called (from the editors manager) to reload the file"""
        # Re-read the file with updating the file timestamp
        self.readFile(self.__fileName)

        # Hide the bars, just in case both of them
        if not self.__importsBar.isHidden():
            self.__importsBar.hide()
        if not self.__outsideChangesBar.isHidden():
            self.__outsideChangesBar.hide()

        # Set the shown flag
        self.setReloadDialogShown(False)

    def reloadAllNonModified(self):
        """Request to reload all the non-modified files"""
        self.reloadAllNonModifiedRequest.emit()

    @staticmethod
    def onRunScriptSettings():
        """Shows the run parameters dialogue"""
        GlobalData().mainWindow.onRunTabDlg()

    def onProfileScriptSettings(self):
        """Shows the profile parameters dialogue"""
        fileName = self.getFileName()
        params = getRunParameters(fileName)
        termType = Settings()['terminalType']
        profilerParams = Settings().getProfilerSettings()
        debuggerParams = Settings().getDebuggerSettings()
        dlg = RunDialog(fileName, params, termType,
                        profilerParams, debuggerParams, "Profile", self)
        if dlg.exec_() == QDialog.Accepted:
            addRunParams(fileName, dlg.runParams)
            if dlg.termType != termType:
                Settings()['terminalType'] = dlg.termType
            if dlg.profilerParams != profilerParams:
                Settings().setProfilerSettings(dlg.profilerParams)
            self.onProfileScript()

    # Arguments: action
    def onRunScript(self, _=None):
        """Runs the script"""
        GlobalData().mainWindow.onRunTab()

    # Arguments: action
    def onProfileScript(self, _=None):
        """Profiles the script"""
        try:
            ProfilingProgressDialog(self.getFileName(), self).exec_()
        except Exception as exc:
            logging.error(str(exc))

    def onDebugScriptSettings(self):
        """Shows the debug parameters dialogue"""
        if self.__checkDebugPrerequisites():
            fileName = self.getFileName()
            params = getRunParameters(fileName)
            termType = Settings()['terminalType']
            profilerParams = Settings().getProfilerSettings()
            debuggerParams = Settings().getDebuggerSettings()
            dlg = RunDialog(fileName, params, termType,
                            profilerParams, debuggerParams, "Debug", self)
            if dlg.exec_() == QDialog.Accepted:
                addRunParams(fileName, dlg.runParams)
                if dlg.termType != termType:
                    Settings()['terminalType'] = dlg.termType
                if dlg.debuggerParams != debuggerParams:
                    Settings().setDebuggerSettings(dlg.debuggerParams)
                self.onDebugScript()

    def onDebugScript(self):
        """Starts debugging"""
        if self.__checkDebugPrerequisites():
            GlobalData().mainWindow.debugScript(self.getFileName())

    @staticmethod
    def __checkDebugPrerequisites():
        """Returns True if should continue"""
        mainWindow = GlobalData().mainWindow
        editorsManager = mainWindow.editorsManagerWidget.editorsManager
        modifiedFiles = editorsManager.getModifiedList(True)
        if not modifiedFiles:
            return True

        dlg = ModifiedUnsavedDialog(modifiedFiles, "Save and debug")
        if dlg.exec_() != QDialog.Accepted:
            # Selected to cancel
            return False

        # Need to save the modified project files
        return editorsManager.saveModified(True)

    def getCFEditor(self):
        """Provides a reference to the control flow widget"""
        return self.__flowUI

    def cflowSyncRequested(self, absPos, line, pos):
        """Highlight the item closest to the absPos"""
        self.__flowUI.highlightAtAbsPos(absPos, line, pos)

    def passFocusToFlow(self):
        """Sets the focus to the graphics part"""
        if isPythonMime(self.__editor.mime):
            self.__flowUI.setFocus()
            return True
        return False

    # Mandatory interface part is below

    def getEditor(self):
        """Provides the editor widget"""
        return self.__editor

    def isModified(self):
        """Tells if the file is modified"""
        return self.__editor.document().isModified()

    def getRWMode(self):
        """Tells if the file is read only"""
        if not os.path.exists(self.__fileName):
            return None
        return 'RW' if QFileInfo(self.__fileName).isWritable() else 'RO'

    def getMime(self):
        """Provides the buffer mime"""
        return self.__editor.mime

    def getType(self):
        """Tells the widget type"""
        return MainWindowTabWidgetBase.PlainTextEditor

    def getLanguage(self):
        """Tells the content language"""
        editorLanguage = self.__editor.language()
        if editorLanguage:
            return editorLanguage
        return self.__editor.mime if self.__editor.mime else 'n/a'

    def getFileName(self):
        """Tells what file name of the widget content"""
        return self.__fileName

    def setFileName(self, name):
        """Sets the file name"""
        self.__fileName = name
        self.__shortName = os.path.basename(name)

    def getEol(self):
        """Tells the EOL style"""
        return self.__editor.getEolIndicator()

    def getLine(self):
        """Tells the cursor line"""
        line, _ = self.__editor.cursorPosition
        return line

    def getPos(self):
        """Tells the cursor column"""
        _, pos = self.__editor.cursorPosition
        return pos

    def getEncoding(self):
        """Tells the content encoding"""
        if self.__editor.explicitUserEncoding:
            return self.__editor.explicitUserEncoding
        return self.__editor.encoding

    def getShortName(self):
        """Tells the display name"""
        return self.__shortName

    def setShortName(self, name):
        """Sets the display name"""
        self.__shortName = name

    def isDiskFileModified(self):
        """Return True if the loaded file is modified"""
        if not os.path.isabs(self.__fileName):
            return False
        if not os.path.exists(self.__fileName):
            return True
        path = os.path.realpath(self.__fileName)
        return self.__diskModTime != os.path.getmtime(path) or \
               self.__diskSize != os.path.getsize(path)

    def doesFileExist(self):
        """Returns True if the loaded file still exists"""
        return os.path.exists(self.__fileName)

    def setReloadDialogShown(self, value=True):
        """Sets the new value of the flag which tells if the reloading
           dialogue has already been displayed
        """
        self.__reloadDlgShown = value

    def getReloadDialogShown(self):
        """Tells if the reload dialog has already been shown"""
        return self.__reloadDlgShown and \
            not self.__outsideChangesBar.isVisible()

    def updateModificationTime(self, fileName):
        """Updates the modification time"""
        path = os.path.realpath(fileName)
        self.__diskModTime = os.path.getmtime(path)
        self.__diskSize = os.path.getsize(path)

    def setDebugMode(self, debugOn, disableEditing):
        """Called to switch debug/development"""
        skin = GlobalData().skin
        self.__debugMode = debugOn
        self.__breakableLines = None

        if debugOn:
            if disableEditing:
                self.__editor.setMarginsBackgroundColor(
                    skin['marginPaperDebug'])
                self.__editor.setMarginsForegroundColor(
                    skin['marginColorDebug'])
                self.__editor.setReadOnly(True)

                # Undo/redo
                self.__undoButton.setEnabled(False)
                self.__redoButton.setEnabled(False)

                # Spaces/tabs/line
                self.removeTrailingSpacesButton.setEnabled(False)
                self.expandTabsButton.setEnabled(False)
        else:
            self.__editor.setMarginsBackgroundColor(skin['marginPaper'])
            self.__editor.setMarginsForegroundColor(skin['marginColor'])
            self.__editor.setReadOnly(False)

            # Undo/redo
            self.__undoButton.setEnabled(
                self.__editor.document().isUndoAvailable())
            self.__redoButton.setEnabled(
                self.__editor.document().isRedoAvailable())

            # Spaces/tabs
            self.removeTrailingSpacesButton.setEnabled(True)
            self.expandTabsButton.setEnabled(True)

        # Run/debug buttons
        self.__updateRunDebugButtons()

    def isLineBreakable(self, line=None, enforceRecalc=False,
                        enforceSure=False):
        """Returns True if a breakpoint could be placed on the current line"""
        if self.__fileName is None or \
           self.__fileName == "" or \
           not os.path.isabs(self.__fileName):
            return False
        if not isPythonMime(self.getMime()):
            return False

        if line is None:
            line = self.getLine() + 1
        if self.__breakableLines is not None and not enforceRecalc:
            return line in self.__breakableLines

        self.__breakableLines = getBreakpointLines(self.getFileName(),
                                                   self.__editor.text,
                                                   enforceRecalc)

        if self.__breakableLines is None:
            if not enforceSure:
                # Be on the safe side - if there is a problem of
                # getting the breakable lines, let the user decide
                return True
            return False

        return line in self.__breakableLines

    def getVCSStatus(self):
        """Provides the VCS status"""
        return self.__vcsStatus

    def setVCSStatus(self, newStatus):
        """Sets the new VCS status"""
        self.__vcsStatus = newStatus