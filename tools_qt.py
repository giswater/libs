"""This file is part of Giswater
The program is free software: you can redistribute it and/or modify it under the terms of the GNU
General Public License as published by the Free Software Foundation, either version 3 of the License,
or (at your option) any later version.
"""

# -*- coding: utf-8 -*-
import inspect
import operator
import os
import subprocess
import sys
import traceback
import webbrowser
from encodings.aliases import aliases
from functools import partial
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union
from warnings import warn

from qgis.core import QgsExpression
from qgis.gui import QgsDateTimeEdit
from qgis.PyQt.QtCore import (
    QCoreApplication,
    QDate,
    QDateTime,
    QLocale,
    QPersistentModelIndex,
    QRegularExpression,
    QSortFilterProxyModel,
    QStringListModel,
    Qt,
    QTime,
    QTranslator,
    pyqtSignal,
)
from qgis.PyQt.QtGui import (
    QDoubleValidator,
    QFont,
    QIcon,
    QPixmap,
    QRegularExpressionValidator,
    QStandardItem,
    QStandardItemModel,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
)
from qgis.PyQt.QtSql import QSqlTableModel
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QAction,
    QApplication,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDateEdit,
    QDateTimeEdit,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSpacerItem,
    QSpinBox,
    QTableView,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QTimeEdit,
    QToolBox,
    QToolButton,
    QWidget,
)
from qgis.PyQt.sip import isdeleted
from qgis.utils import iface

from . import lib_vars, tools_db, tools_log, tools_os, tools_qgis
from .ui.ui_manager import ShowInfoUi

translator = QTranslator()
dlg_info = ShowInfoUi()


class GwExtendedQLabel(QLabel):
    clicked = pyqtSignal()

    def __init(self, parent):
        QLabel.__init__(self, parent)

    def mouseReleaseEvent(self, ev):  # noqa: N802
        self.clicked.emit()


class GwHyperLinkLabel(QLabel):
    clicked = pyqtSignal()

    def __init__(self):
        QLabel.__init__(self)
        self.setStyleSheet("QLabel{color:blue; text-decoration: underline;}")

    def mouseReleaseEvent(self, ev):  # noqa: N802
        self.clicked.emit()
        self.setStyleSheet("QLabel{color:purple; text-decoration: underline;}")


class GwHyperLinkLineEdit(QLineEdit):
    clicked = pyqtSignal()

    def __init__(self):
        QLabel.__init__(self)
        self.setStyleSheet("QLineEdit{color:blue; text-decoration: underline;}")

    def mouseReleaseEvent(self, ev):  # noqa: N802
        if self.isReadOnly():
            self.clicked.emit()
            self.setStyleSheet(
                "QLineEdit { background: rgb(242, 242, 242); color:purple; text-decoration: underline; border: none;}"
            )  # noqa: E501


class GwEditDialog(QDialog):
    """Dialog with just one widget (QLineEdit, QTextEdit, QComboBox, QCheckBox).

    Use example:
    ```
        edit_dialog = GwEditDialog(dialog, title=f"Edit {header}",
                                   label_text=f"Set new '{header}' value for result '{result_id}':",
                                   widget_type="QTextEdit", initial_value=value)
        if edit_dialog.exec_() == QDialog.DialogCode.Accepted:
            new_value = edit_dialog.get_value()
            self._update_data(result_id, columnname, new_value)
    ```
    """

    def __init__(
        self, parent=None, title="Edit", label_text="", widget_type="QLineEdit", options=None, initial_value=None
    ):
        super(GwEditDialog, self).__init__(parent)

        self.setWindowTitle(title)

        self.layout = QGridLayout(self)

        # Add the label
        self.label = QLabel(label_text, self)
        self.layout.addWidget(self.label, 0, 0, 1, 2)

        # Create the widget based on the type
        if widget_type == "QLineEdit":
            self.widget = QLineEdit(self)
        elif widget_type == "QTextEdit":
            self.widget = QTextEdit(self)
        elif widget_type == "QComboBox":
            try:
                from ..core.utils.async_combo import GwAsyncComboBox
                self.widget = GwAsyncComboBox(self)
            except ImportError:
                self.widget = QComboBox(self)
            if options:
                try:
                    self.widget.addItems(options)
                except Exception:
                    fill_combo_values(self.widget, options)
        elif widget_type == "QCheckBox":
            self.widget = QCheckBox(self)
        else:
            raise ValueError("Unsupported widget type")

        self.layout.addWidget(self.widget, 1, 0, 1, 2)

        if initial_value is not None:
            self.set_value(initial_value)

        # Add buttons
        self.accept_button = QPushButton("Accept", self)
        self.cancel_button = QPushButton("Cancel", self)

        self.accept_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)

        self.layout.addWidget(self.accept_button, 2, 0)
        self.layout.addWidget(self.cancel_button, 2, 1)

    def get_value(self):
        if isinstance(self.widget, QLineEdit):
            return self.widget.text()
        elif isinstance(self.widget, QTextEdit):
            return self.widget.toPlainText()
        elif isinstance(self.widget, QComboBox):
            return get_combo_value(self, self.widget)
        elif isinstance(self.widget, QCheckBox):
            return is_checked(self, self.widget)
        else:
            return None

    def set_value(self, value):
        set_widget_text(self, self.widget, value)


QtMatchFlag = Literal["starts", "contains", "ends", "exact", "regex"]
match_flags: Dict[QtMatchFlag, Qt.MatchFlag] = {
    "starts": Qt.MatchFlag.MatchStartsWith,
    "contains": Qt.MatchFlag.MatchContains,
    "ends": Qt.MatchFlag.MatchEndsWith,
    "exact": Qt.MatchFlag.MatchExactly,
    "regex": Qt.MatchFlag.MatchRegularExpression,
}


def fill_combo_box(dialog, widget, rows, allow_nulls=True, clear_combo=True):  # noqa: C901
    warn("This method is deprecated, use fill_combo_values instead.", DeprecationWarning, stacklevel=2)

    if rows is None:
        return
    if type(widget) is str:
        widget = dialog.findChild(QComboBox, widget)
    if clear_combo:
        widget.clear()
    if allow_nulls:
        widget.addItem("")
    for row in rows:
        if len(row) > 1:
            elem = row[0]
            user_data = row[1]
        else:
            elem = row[0]
            user_data = None
        if elem is not None:
            try:
                if type(elem) is int or type(elem) is float:
                    widget.addItem(str(elem), user_data)
                else:
                    widget.addItem(elem, user_data)
            except Exception:
                widget.addItem(str(elem), user_data)


def fill_combo_box_list(dialog, widget, list_object, allow_nulls=True, clear_combo=True):
    if type(widget) is str:
        widget = dialog.findChild(QComboBox, widget)
    if widget is None:
        return None

    if clear_combo:
        widget.clear()
    if allow_nulls:
        widget.addItem("")
    for elem in list_object:
        widget.addItem(str(elem))


def get_calendar_date(dialog, widget, date_format="yyyy/MM/dd", datetime_format="yyyy/MM/dd hh:mm:ss"):
    date = None
    if type(widget) is str:
        widget = dialog.findChild(QWidget, widget)
    if widget is None:
        return
    if type(widget) is QDateEdit:
        date = widget.date().toString(date_format)
    elif type(widget) is QDateTimeEdit:
        date = widget.dateTime().toString(datetime_format)
    elif isinstance(widget, QgsDateTimeEdit) and widget.displayFormat() in (
        "dd/MM/yyyy",
        "yyyy/MM/dd",
        "dd-MM-yyyy",
        "yyyy-MM-dd",
    ):
        date = widget.dateTime().toString(date_format)
    elif isinstance(widget, QgsDateTimeEdit) and widget.displayFormat() in (
        "dd/MM/yyyy hh:mm:ss",
        "yyyy/MM/dd hh:mm:ss",
    ):
        date = widget.dateTime().toString(datetime_format)

    return date


def set_calendar(dialog, widget, date, default_current_date=True):
    if type(widget) is str:
        widget = dialog.findChild(QWidget, widget)
    if widget is None:
        return

    if lib_vars.date_format in ("dd/MM/yyyy", "dd-MM-yyyy", "yyyy/MM/dd", "yyyy-MM-dd"):
        widget.setDisplayFormat(lib_vars.date_format)
    if type(widget) is QDateEdit or (
        isinstance(widget, QgsDateTimeEdit)
        and widget.displayFormat() in ("dd/MM/yyyy", "yyyy/MM/dd", "dd-MM-yyyy", "yyyy-MM-dd")
    ):
        if date is None:
            if default_current_date:
                date = QDate.currentDate()
            else:
                date = QDate.fromString("01-01-2000", "dd-MM-yyyy")
        widget.setDate(date)
    elif type(widget) is QDateTimeEdit or (
        isinstance(widget, QgsDateTimeEdit)
        and widget.displayFormat()
        in ("dd/MM/yyyy hh:mm:ss", "yyyy/MM/dd hh:mm:ss", "dd-MM-yyyy hh:mm:ss", "yyyy-MM-dd hh:mm:ss")
    ):
        if date is None:
            date = QDateTime.currentDateTime()
        widget.setDateTime(date)


def get_listwidget_values(dialog, widget, role=Qt.ItemDataRole.UserRole):
    """Returns a list of all values in a QListWidget.
    :param dialog: The parent dialog in which to search for the widget.
    :param widget: The QListWidget or its objectName (str).
    :param role: The role of the data to get from the items.
    :return: list of values (strings) or None if widget not found.
    """
    values = None
    if type(widget) is str:
        widget = dialog.findChild(QWidget, widget)
    if widget is None:
        return
    if isinstance(widget, QListWidget):
        values = []
        for i in range(widget.count()):
            item = widget.item(i)
            if item is not None:
                values.append(item.data(role))
    return values


def set_time(dialog, widget, time):
    if type(widget) is str:
        widget = dialog.findChild(QWidget, widget)
    if not widget:
        return
    if type(widget) is QTimeEdit:
        if time is None:
            time = QTime(00, 00, 00)
        widget.setTime(time)


def get_widget(dialog, widget):
    if isdeleted(dialog):
        return None

    if type(widget) is str:
        widget = dialog.findChild(QWidget, widget)
    return widget


def get_widget_type(dialog, widget):
    if isdeleted(dialog):
        return None

    if type(widget) is str:
        widget = dialog.findChild(QWidget, widget)
    if widget is None:
        return None
    return type(widget)


def get_widget_value(dialog, widget):
    value = None

    if isdeleted(dialog):
        return value

    if type(widget) is str:
        widget = dialog.findChild(QWidget, widget)
    if widget is None:
        return value

    if type(widget) in (QDoubleSpinBox, QLineEdit, QSpinBox, QTextEdit, GwHyperLinkLineEdit):
        value = get_text(dialog, widget, return_string_null=False)
    elif isinstance(widget, QComboBox):
        value = get_combo_value(dialog, widget, 0)
    elif type(widget) is QCheckBox:
        value = is_checked(dialog, widget)
        if value is not None:
            value = str(value).lower()
    elif isinstance(widget, QgsDateTimeEdit):
        value = get_calendar_date(dialog, widget)
    elif isinstance(widget, QListWidget):
        value = get_listwidget_values(dialog, widget)

    return value


def get_text(dialog, widget, add_quote=False, return_string_null=True):
    """Get text from widget"""
    if isdeleted(dialog):
        return None

    if type(widget) is str:
        widget = dialog.findChild(QWidget, widget)

    if widget is None:
        return "null" if return_string_null else ""

    text = None
    if type(widget) in (QLineEdit, QPushButton, QLabel, GwHyperLinkLabel, GwHyperLinkLineEdit):
        text = _get_text_from_line_edit(widget)
    elif type(widget) in (QDoubleSpinBox, QSpinBox):
        text = _get_text_from_spinbox(widget)
    elif type(widget) in (QTextEdit, QPlainTextEdit):
        text = _get_text_from_text_edit(widget)
    elif isinstance(widget, QComboBox):
        text = _get_text_from_combo(widget)
    elif type(widget) is QCheckBox:
        text = _get_text_from_checkbox(dialog, widget)
    else:
        return None

    return _handle_null_text(text, add_quote, return_string_null)


def set_widget_text(dialog, widget, text, msg_params=None):
    """Set text to widget"""
    try:
        if type(widget) is str:
            widget = dialog.findChild(QWidget, widget)
        if widget is None:
            return

        if type(widget) in (QLabel, QLineEdit, QTextEdit, QPushButton, QTextBrowser, QPlainTextEdit):
            _set_text_for_text_widgets(widget, text, msg_params)
        elif type(widget) in (QDoubleSpinBox, QSpinBox):
            _set_text_for_spinbox(widget, text)
        elif isinstance(widget, QComboBox):
            set_selected_item(dialog, widget, text)
        elif type(widget) is QTimeEdit:
            set_time(dialog, widget, text)
        elif type(widget) is QCheckBox:
            set_checked(dialog, widget, text)
    except RuntimeError:
        pass


def is_checked(dialog, widget):
    if type(widget) is str:
        widget = dialog.findChild(QCheckBox, widget)
        if widget is None:
            widget = dialog.findChild(QRadioButton, widget)
    checked = False
    if widget:
        state = widget.checkState()
        if state == 0:
            checked = False
        elif state == 1:
            checked = None
        elif state == 2:
            checked = True
    return checked


def set_checked(dialog, widget, checked=True):
    if str(checked) in ("true", "t", "True"):
        checked = True
    elif str(checked) in ("false", "f", "False"):
        checked = False

    if type(widget) is str:
        widget = dialog.findChild(QWidget, widget)
    if not widget:
        return
    if type(widget) is QCheckBox or type(widget) is QRadioButton:
        widget.setChecked(bool(checked))


def get_selected_item(dialog, widget, return_string_null=True):
    if type(widget) is str:
        widget = dialog.findChild(QComboBox, widget)
    if return_string_null:
        widget_text = "null"
    else:
        widget_text = ""
    if widget:
        if widget.currentText():
            widget_text = widget.currentText()
    return widget_text


def set_selected_item(dialog, widget, text):
    if type(widget) is str:
        widget = dialog.findChild(QComboBox, widget)
    if widget:
        index = widget.findText(text)
        if index == -1:
            index = 0
        widget.setCurrentIndex(index)


def set_current_index(dialog, widget, index):
    if type(widget) is str:
        widget = dialog.findChild(QComboBox, widget)
    if widget:
        if index == -1:
            index = 0
        widget.setCurrentIndex(index)


def set_widget_visible(dialog, widget, visible=True):
    if type(widget) is str:
        widget = dialog.findChild(QWidget, widget)
    if widget:
        widget.setVisible(visible)


def set_widget_enabled(dialog, widget, enabled=True):
    if type(widget) is str:
        widget = dialog.findChild(QWidget, widget)
    if widget:
        widget.setEnabled(enabled)


def add_image(dialog, widget, path_img):
    """Set pictures for UD"""
    if type(widget) is str:
        widget = dialog.findChild(QWidget, widget)
    if widget is None:
        return
    if type(widget) is QLabel:
        # Check if file exists
        if not os.path.exists(path_img):
            return

        pixmap = QPixmap(path_img)

        if pixmap.isNull():
            return

        # Set the pixmap
        widget.setPixmap(pixmap)

        # Ensure the label is visible and properly sized
        widget.setVisible(True)
        widget.show()

        # Force update
        widget.update()


def set_autocompleter(combobox, list_items=None):
    """Iterate over the items in the QCombobox, create a list,
    create the model, and set the model according to the list
    """
    if list_items is None:
        list_items = [combobox.itemText(i) for i in range(combobox.count())]

    proxy_model = QSortFilterProxyModel(combobox)
    _set_model_by_list(list_items, proxy_model)
    combobox.editTextChanged.connect(partial(filter_by_list, combobox, proxy_model))

    # Set up the completer without changing the combobox's model
    completer = QCompleter(proxy_model, combobox)
    completer.setCompletionColumn(0)
    completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
    combobox.setCompleter(completer)


def filter_by_list(combobox, proxy_model, text):
    """Filter the list based on the text input"""
    proxy_model.setFilterFixedString(text)
    if combobox.completer():
        combobox.completer().complete()
        combobox.completer().popup().hide()


def get_combo_value(dialog, widget, index=0, add_quote=False):
    """Get item data of current index of the @widget"""
    value = -1
    if add_quote:
        value = ""
    if type(widget) is str:
        widget = dialog.findChild(QWidget, widget)
    if widget:
        if isinstance(widget, QComboBox):
            current_index = widget.currentIndex()
            elem = widget.itemData(current_index)
            if index == -1:
                return elem
            value = elem[index]
            if add_quote:
                value = _handle_null_text(value, True, False)

    return value


def set_combo_value(combo, value, index, add_new=True):
    """Set text to combobox populate with more than 1 item for row
    :param combo: QComboBox widget to manage
    :param value: element to show
    :param index: index to compare
    :param add_new: if True it will add the value even if it's not in the combo
    """
    if combo is None:
        return False

    # Async combos (GwAsyncComboBox) load their items in a background task.
    # If the rows haven't arrived yet we record a pending selection and let
    # the widget apply it as soon as the data is in. Detection is done by
    # duck-typing to avoid pulling a core/utils import into libs.
    if getattr(combo, "_gw_is_async_combo", False) and not combo.property("rows_loaded"):
        try:
            combo.set_pending_selection(value, index)
        except AttributeError:
            pass
        return True

    for i in range(0, combo.count()):
        elem = combo.itemData(i)
        if elem is not None and str(value) == str(elem[index]):
            combo.setCurrentIndex(i)
            return True

    # Add new value if @value not in combo
    if add_new and value not in ("", None, "None", "none", "-1", -1):
        new_elem = []
        # Control if the QComboBox has been previously filled
        if combo.count() > 0:
            for _x in range(len(combo.itemData(0))):
                new_elem.append("")
        else:
            new_elem.append("")
            new_elem.append("")

        new_elem[0] = value
        new_elem[1] = f"({value})"
        combo.addItem(new_elem[1], new_elem)
        combo.setCurrentIndex(combo.count() - 1)
    return False


def fill_combo_values(  # noqa: C901
    combo,
    rows,
    index_to_show=1,
    combo_clear=True,
    sort_combo=True,
    sort_by=1,
    add_empty=False,
    selected_id=None,
    index_to_compare=None,
):
    """Populate @combo with list @rows and show field @index_to_show
    :param combo: QComboBox widget to fill (QComboBox)
    :param rows: the data that'll fill the combo
    :param index_to_show: the index of the row to show (int)
    :param combo_clear: whether it should clear the combo or not (bool)
    :param sort_combo: whether it should sort the items or not (bool)
    :param sort_by: sort combo by this column (int)
    :param add_empty: add an empty element as first item (bool)
    :param selected_id: The value to be set as selected in the ComboBox (str or int)
    :param index_to_compare: Index to compare `selected_id` with the id or value in this combo widget (int).
    """
    records = []
    if rows is None:
        rows = [["", ""]]

    if sort_by > len(rows[0]) - 1:
        sort_by = 1

    for row in rows:
        elem = []
        for x in range(0, len(row)):
            elem.append(row[x])
        records.append(elem)

    signals_blocked = combo.blockSignals(True)
    try:
        if combo_clear:
            combo.clear()
        records_sorted = records
        try:
            if sort_combo:
                records_sorted = sorted(records, key=operator.itemgetter(sort_by))
        except Exception:
            pass
        if add_empty:
            records_sorted.insert(0, ["", ""])

        if getattr(combo, "_gw_is_async_combo", False) and hasattr(combo, "apply_rows"):
            combo.blockSignals(True)
            try:
                rows = []
                for record in records_sorted:
                    if not record:
                        continue
                    row_id = "" if record[0] is None else str(record[0])
                    if index_to_show < len(record):
                        idval = str(record[index_to_show])
                    else:
                        idval = row_id
                    rows.append((row_id, idval))
                combo.apply_rows(rows)
            finally:
                combo.blockSignals(False)
            if None not in (selected_id, index_to_compare):
                set_combo_value(combo, selected_id, index_to_compare)
            return

        for record in records_sorted:
            combo.addItem(str(record[index_to_show]), record)

        if None not in (selected_id, index_to_compare):
            set_combo_value(combo, selected_id, index_to_compare)
    finally:
        combo.blockSignals(signals_blocked)


def set_combo_item_unselectable_by_id(qcombo, list_id=None):
    """Make items of QComboBox visibles but not selectable"""
    if list_id is None:
        list_id = []
    for x in range(0, qcombo.count()):
        if x in list_id:
            index = qcombo.model().index(x, 0)
            qcombo.model().setData(index, 0, Qt.ItemDataRole.UserRole - 1)


def set_combo_item_selectable_by_id(qcombo, list_id=None):
    """Make items of QComboBox selectable"""
    if list_id is None:
        list_id = []
    for x in range(0, qcombo.count()):
        if x in list_id:
            index = qcombo.model().index(x, 0)
            qcombo.model().setData(index, (1 | 32), Qt.ItemDataRole.UserRole - 1)


def set_combo_item_select_unselectable(qcombo, list_id=None, column=0, opt=0):
    """Make items of QComboBox visibles but not selectable
    :param qcombo: QComboBox widget to manage (QComboBox)
    :param list_id: list of strings to manage ex. ['1','3','...'] or ['word1', 'word3','...'] (list)
    :param column: column where to look up the values in the list (int)
    :param opt: 0 -> item not selectable // (1 | 32) -> item selectable (int)
    """
    if list_id is None:
        list_id = []
    for x in range(0, qcombo.count()):
        elem = qcombo.itemData(x)
        if str(elem[column]) in list_id:
            index = qcombo.model().index(x, 0)
            qcombo.model().setData(index, opt, Qt.ItemDataRole.UserRole - 1)


def remove_tab(tab_widget, tab_name):
    """Look in @tab_widget for a tab with @tab_name and remove it"""
    for x in range(0, tab_widget.count()):
        if tab_widget.widget(x).objectName() == tab_name:
            tab_widget.removeTab(x)
            break


def enable_tab_by_tab_name(tab_widget, tab_name, enable):
    """Look in @tab_widget for a tab with @tab_name and remove it"""
    for x in range(0, tab_widget.count()):
        if tab_widget.widget(x).objectName() == tab_name:
            tab_widget.setTabEnabled(x, enable)
            break


def double_validator(
    widget, min_=-9999999, max_=9999999, decimals=2, notation=QDoubleValidator.Notation.StandardNotation, locale=None
):
    """Create and apply a validator for doubles to ensure the number is within a maximum and minimum values
    :param widget: Widget to apply the validator
    :param min_: Minimum value (int)
    :param max_: Maximum value (int)
    :param decimals: Number of decimals (int)
    :param notation: StandardNotation or ScientificNotation
    :param locale: Locale to define decimal separator and more (QLocale)
    """
    validator = QDoubleValidator(min_, max_, decimals)
    validator.setNotation(notation)
    if locale is None:
        locale = QLocale("en_US")
    validator.setLocale(locale)
    widget.setValidator(validator)


def enable_dialog(dialog, enable, ignore_widgets=None):
    if ignore_widgets is None:
        ignore_widgets = ["", None]

    widget_list = dialog.findChildren(QWidget)
    for widget in widget_list:
        if str(widget.objectName()) not in ignore_widgets:
            if type(widget) in (QSpinBox, QDoubleSpinBox, QLineEdit):
                widget.setReadOnly(not enable)
                if enable:
                    widget.setStyleSheet(None)
                else:
                    widget.setStyleSheet("QWidget { background: rgb(242, 242, 242); color: rgb(100, 100, 100)}")
            elif isinstance(widget, (QComboBox, QCheckBox, QPushButton, QgsDateTimeEdit, QTableView)):
                widget.setEnabled(enable)


def set_tableview_config(
    widget,
    selection=QAbstractItemView.SelectionBehavior.SelectRows,
    edit_triggers=QTableView.EditTrigger.NoEditTriggers,
    section_resize_mode=QHeaderView.ResizeMode.ResizeToContents,
    stretch_last_section=True,
    sorting_enabled=True,
    selection_mode=QAbstractItemView.SelectionMode.ExtendedSelection,
):
    """Set QTableView configurations"""
    widget.setSelectionBehavior(selection)
    widget.setSelectionMode(selection_mode)
    widget.horizontalHeader().setSectionResizeMode(section_resize_mode)
    widget.horizontalHeader().setStretchLastSection(stretch_last_section)
    widget.horizontalHeader().setMinimumSectionSize(100)
    widget.setEditTriggers(edit_triggers)
    widget.setSortingEnabled(sorting_enabled)


def get_col_index_by_col_name(qtable, column_name):
    """Return column index searching by column name"""
    model = qtable.model()
    columns_dict = qtable.property("columns")
    if not columns_dict:
        columns_dict = {
            model.headerData(i, Qt.Orientation.Horizontal): model.headerData(i, Qt.Orientation.Horizontal)
            for i in range(model.columnCount())
        }  # noqa: E501
        qtable.setProperty("columns", columns_dict)
    column_index = -1
    try:
        record = model.record(0)
        column_index = record.indexOf(column_name)
    except AttributeError:
        for x in range(0, model.columnCount()):
            header = model.headerData(x, Qt.Orientation.Horizontal)
            name = columns_dict.get(header)
            if name is None:
                if header and (not isinstance(header, str) or header.strip()):
                    name = header  # column not in dict: use header as column name
                else:
                    try:
                        name = model.record(0).fieldName(x)
                    except (AttributeError, IndexError):
                        pass
            if name == column_name:
                column_index = x
                break

    if column_index == -1:
        column_index = None

    return column_index


def get_tab_index_by_tab_name(qtabwidget: QTabWidget, tab_name: str) -> Optional[int]:
    """Return tab index searching by tab name"""
    tab_index = -1

    try:
        for idx in range(qtabwidget.count()):
            if qtabwidget.widget(idx).objectName() == tab_name:
                tab_index = idx
                break
    except Exception:
        msg = "Tab not found."
        tools_log.log_error(msg, parameter=tab_name)

    if tab_index == -1:
        tab_index = None

    return tab_index


def get_page_index_by_page_name(qtoolbox: QToolBox, page_name: str) -> Optional[int]:
    """Return page index searching by page name"""
    page_index = -1

    try:
        for idx in range(qtoolbox.count()):
            if qtoolbox.widget(idx).objectName() == page_name:
                page_index = idx
                break
    except Exception:
        msg = "Page not found."
        tools_log.log_error(msg, parameter=page_name)

    if page_index == -1:
        page_index = None

    return page_index


def onCellChanged(table, row, column):  # noqa: N802
    """Function to be connected to a QTableWidget cellChanged signal.
    Note: row & column parameters are passed by the signal
    """
    # Add a new row if the edited row is the last one
    if row >= (table.rowCount() - 1):
        headers = [n for n in range(0, table.rowCount() + 1)]
        table.insertRow(table.rowCount())
        table.setVerticalHeaderLabels(headers)
    # Remove "last" row (empty one) if the real last row is empty
    elif row == (table.rowCount() - 2):
        for n in range(0, table.columnCount()):
            item = table.item(row, n)
            if item is not None:
                if item.data(0) not in (None, ""):
                    return
        table.setRowCount(table.rowCount() - 1)


def set_completer_object(
    completer: QCompleter,
    model: Union[QStandardItemModel, QStringListModel],
    widget: QLineEdit,
    list_items: Union[List[str], List[Dict[str, Any]]],
    max_visible: int = 10,
) -> None:
    """Attach a QCompleter to a QLineEdit using the provided model and list_items.

    Each QLineEdit must have its own QCompleter and QStringListModel/QStandardItemModel instance.
    This function is typically used to provide autocomplete for fields like <table_object>_id,
    where the completion list is derived from the selected table_object.
    """
    completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    completer.setMaxVisibleItems(max_visible)
    completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)

    # --- Store the selected ID on completion ---
    def on_completion(text: str):
        for row in range(model.rowCount()):
            item = model.item(row)
            if item.text() == text:
                selected_id = item.data(Qt.ItemDataRole.UserRole)
                widget.setProperty("selected_id", selected_id)  # store the ID
                break

    # Optional: clear selected_id if user changes the text manually
    def on_text_changed(text: str):
        widget.setProperty("selected_id", None)

    if isinstance(model, QStandardItemModel):
        seen = set()
        model.clear()

        for item_dict in list_items:
            idval = str(item_dict["idval"])
            if idval in seen:
                continue  # skip duplicates
            seen.add(idval)

            idkey = item_dict["id"]
            item = QStandardItem(idval)
            item.setData(idkey, Qt.ItemDataRole.UserRole)
            model.appendRow(item)

        if isinstance(completer, QComboBox):
            completer.textActivated.connect(on_completion)
        else:
            completer.activated.connect(on_completion)

    elif isinstance(model, QStringListModel):
        model.setStringList(list_items)  # Not recommended for idval/id cases

    completer.setModel(model)
    widget.setCompleter(completer)

    widget.textEdited.connect(on_text_changed)


def set_action_checked(action, enabled, dialog=None):
    if type(action) is str and dialog is not None:
        action = dialog.findChild(QAction, action)
    try:
        action.setChecked(enabled)
    except RuntimeError:
        pass


def set_calendar_empty(widget):
    """Set calendar empty when click inner button of QgsDateTimeEdit because aesthetically it looks better"""
    widget.displayNull(True)


def add_horizontal_spacer():
    widget = QSpacerItem(10, 10, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
    return widget


def add_verticalspacer():
    widget = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
    return widget


def check_expression_filter(expr_filter, log_info=False):
    """Check if expression filter @expr is valid"""
    if log_info:
        tools_log.log_info(expr_filter)
    expr = QgsExpression(expr_filter)
    if expr.hasParserError():
        msg = "Expression Error"
        tools_log.log_warning(msg, parameter=expr_filter)
        return False, expr

    return True, expr


def check_date(widget, button=None, regex_type=1):
    """Set QRegularExpression in order to validate QLineEdit(widget) field type date.
    Also allow to enable or disable a QPushButton(button), like typical accept button
    @Type=1 (yyy-mm-dd), @Type=2 (dd-mm-yyyy)
    """
    reg_exp = ""
    placeholder = "yyyy-mm-dd"
    if regex_type == 1:
        widget.setPlaceholderText("yyyy-mm-dd")
        placeholder = "yyyy-mm-dd"
        reg_exp = QRegularExpression(
            r"(((\d{4})([-])(0[13578]|10|12)([-])(0[1-9]|[12][0-9]|3[01]))|"
            r"((\d{4})([-])(0[469]|11)([-])([0][1-9]|[12][0-9]|30))|"
            r"((\d{4})([-])(02)([-])(0[1-9]|1[0-9]|2[0-8]))|"
            r"(([02468][048]00)([-])(02)([-])(29))|"
            r"(([13579][26]00)([-])(02)([-])(29))|"
            r"(([0-9][0-9][0][48])([-])(02)([-])(29))|"
            r"(([0-9][0-9][2468][048])([-])(02)([-])(29))|"
            r"(([0-9][0-9][13579][26])([-])(02)([-])(29)))"
        )
    elif regex_type == 2:
        widget.setPlaceholderText("dd-mm-yyyy")
        placeholder = "dd-mm-yyyy"
        reg_exp = QRegularExpression(
            r"(((0[1-9]|[12][0-9]|3[01])([-])(0[13578]|10|12)([-])(\d{4}))|"
            r"(([0][1-9]|[12][0-9]|30)([-])(0[469]|11)([-])(\d{4}))|"
            r"((0[1-9]|1[0-9]|2[0-8])([-])(02)([-])(\d{4}))|"
            r"((29)(-)(02)([-])([02468][048]00))|"
            r"((29)([-])(02)([-])([13579][26]00))|"
            r"((29)([-])(02)([-])([0-9][0-9][0][48]))|"
            r"((29)([-])(02)([-])([0-9][0-9][2468][048]))|"
            r"((29)([-])(02)([-])([0-9][0-9][13579][26])))"
        )
    elif regex_type == 3:
        widget.setPlaceholderText("yyyy/mm/dd")
        placeholder = "yyyy/mm/dd"
        reg_exp = QRegularExpression(
            r"(((\d{4})([/])(0[13578]|10|12)([/])(0[1-9]|[12][0-9]|3[01]))|"
            r"((\d{4})([/])(0[469]|11)([/])([0][1-9]|[12][0-9]|30))|"
            r"((\d{4})([/])(02)([/])(0[1-9]|1[0-9]|2[0-8]))|"
            r"(([02468][048]00)([/])(02)([/])(29))|"
            r"(([13579][26]00)([/])(02)([/])(29))|"
            r"(([0-9][0-9][0][48])([/])(02)([/])(29))|"
            r"(([0-9][0-9][2468][048])([/])(02)([/])(29))|"
            r"(([0-9][0-9][13579][26])([/])(02)([/])(29)))"
        )
    elif regex_type == 4:
        widget.setPlaceholderText("dd/mm/yyyy")
        placeholder = "dd/mm/yyyy"
        reg_exp = QRegularExpression(
            r"(((0[1-9]|[12][0-9]|3[01])([/])(0[13578]|10|12)([/])(\d{4}))|"
            r"(([0][1-9]|[12][0-9]|30)([/])(0[469]|11)([/])(\d{4}))|"
            r"((0[1-9]|1[0-9]|2[0-8])([/])(02)([/])(\d{4}))|"
            r"((29)(-)(02)([/])([02468][048]00))|"
            r"((29)([/])(02)([/])([13579][26]00))|"
            r"((29)([/])(02)([/])([0-9][0-9][0][48]))|"
            r"((29)([/])(02)([/])([0-9][0-9][2468][048]))|"
            r"((29)([/])(02)([/])([0-9][0-9][13579][26])))"
        )

    widget.setValidator(QRegularExpressionValidator(reg_exp))
    widget.textChanged.connect(partial(check_regex, widget, reg_exp, button, placeholder))


def check_regex(widget, reg_exp, button, placeholder, text):
    is_valid = False
    if reg_exp.exactMatch(text) is True:
        widget.setStyleSheet(None)
        is_valid = True
    elif str(text) == "":
        widget.setStyleSheet(None)
        widget.setPlaceholderText(placeholder)
        is_valid = True
    elif reg_exp.exactMatch(text) is False:
        widget.setStyleSheet("border: 1px solid red")
        is_valid = False

    if button is not None and type(button) is QPushButton:
        if is_valid is False:
            button.setEnabled(False)
        else:
            button.setEnabled(True)


def fill_table(
    qtable,
    table_name,
    expr_filter=None,
    edit_strategy=QSqlTableModel.EditStrategy.OnManualSubmit,
    sort_order=Qt.SortOrder.AscendingOrder,
    schema_name=None,
):
    """Set a model with selected filter. Attach that model to selected table
    :param qtable: tableview where set the model (QTableView)
    :param table_name: database table name or view name (String)
    :param expr_filter: expression to filter the model (String)
    :param edit_strategy: (QSqlTableModel.EditStrategy.OnFieldChange,
        QSqlTableModel.EditStrategy.OnManualSubmit, QSqlTableModel.EditStrategy.OnRowChange)
    :param sort_order: can be 0 or 1 (Qt.SortOrder.AscendingOrder or Qt.SortOrder.AscendingOrder)
    :return:
    """
    if not schema_name and lib_vars.schema_name and lib_vars.schema_name not in table_name:
        table_name = f"{lib_vars.schema_name}.{table_name}"

    # Set model
    model = QSqlTableModel(db=lib_vars.qgis_db_credentials)
    model.setTable(table_name)
    model.setEditStrategy(edit_strategy)
    model.setSort(0, sort_order)
    if expr_filter is not None:
        model.setFilter(expr_filter)
    model.select()

    # Check for errors
    if model.lastError().isValid():
        if "Unable to find table" in model.lastError().text():
            tools_db.reset_qsqldatabase_connection()
        else:
            msg = "Fill table"
            tools_qgis.show_warning(msg, parameter=model.lastError().text())

    # Attach model to tableview
    qtable.setModel(model)


def set_lazy_init(widget, lazy_widget=None, lazy_init_function=None):
    """Apply the init function related to the model. It's necessary
    a lazy init because model is changed everytime is loaded.
    """
    if lazy_widget is None:
        return
    if widget != lazy_widget:
        return
    lazy_init_function(lazy_widget)


def filter_by_id(dialog, widget_table, widget_txt, table_object, field_object_id="id"):
    object_id = get_text(dialog, widget_txt)
    if object_id != "null":
        expr = f"{field_object_id}::text ILIKE '%{object_id}%'"
        # Refresh model with selected filter
        widget_table.model().setFilter(expr)
        widget_table.model().select()
    else:
        fill_table(widget_table, lib_vars.schema_name + "." + table_object)


def set_selection_behavior(dialog):
    # Get objects of type: QTableView
    widget_list = dialog.findChildren(QTableView)
    for widget in widget_list:
        widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        widget.horizontalHeader().setStretchLastSection(True)


def get_folder_path(dialog, widget):
    """Get folder path"""
    # Check if selected folder exists. Set default value if necessary
    folder_path = get_text(dialog, widget)
    if folder_path is None or folder_path == "null" or not os.path.exists(folder_path):
        folder_path = os.path.expanduser("~")

    # Open dialog to select folder
    os.chdir(folder_path)
    file_dialog = QFileDialog()
    file_dialog.setFileMode(QFileDialog.FileMode.Directory)
    message = "Select folder"
    folder_path = file_dialog.getExistingDirectory(parent=None, caption=tr(message), directory=folder_path)
    if folder_path:
        set_widget_text(dialog, widget, str(folder_path))


def get_file(title: str, subtitle: str, extension: str) -> Optional[Path]:
    """Get file path"""
    result = QFileDialog.getOpenFileName(None, title, subtitle, extension)
    file_path_str: str = result[0]
    if file_path_str:
        return Path(file_path_str)
    return None


def get_save_file_path(
    dialog: Any,
    widget: Union[str, QWidget],
    extension: str = "",
    message: str = "",
    default_path: str = "",
    file_name: str = "",
) -> str:
    """Get file path"""
    file = get_text(dialog, widget)
    # Set default value if necessary
    if file in (None, "null", ""):
        if default_path != "":
            file = default_path
        else:
            file = lib_vars.plugin_dir

    if not file:
        return ""

    # Get directory of that file
    folder_path = os.path.dirname(file)
    if not os.path.exists(folder_path):
        folder_path = os.path.dirname(__file__)
    os.chdir(folder_path)
    file, _ = QFileDialog.getSaveFileName(None, tr(message), os.path.join(folder_path, file_name), extension)
    set_widget_text(dialog, widget, file)

    return file


def get_open_file_path(
    dialog: Any, widget: Union[str, QWidget], extension: str = "", message: str = "", default_path: str = ""
) -> str:
    """Get file path"""
    file = get_text(dialog, widget)
    # Set default value if necessary
    if file in (None, "null", ""):
        if default_path != "":
            file = default_path
        else:
            file = lib_vars.plugin_dir

    if not file:
        return ""

    # Get directory of that file
    folder_path = os.path.dirname(file)
    if not os.path.exists(folder_path):
        folder_path = os.path.dirname(__file__)
    os.chdir(folder_path)
    file, _ = QFileDialog.getOpenFileName(None, tr(message), "", extension)
    set_widget_text(dialog, widget, file)

    return file


def get_open_files_path(message: str = "", file_types: str = "") -> List[str]:
    """Get file path"""
    files_path, _ = QFileDialog.getOpenFileNames(None, tr(message), "", file_types)
    return files_path


def hide_void_groupbox(dialog):
    """Rceives a dialog, searches it all the QGroupBox, looks 1 to 1 if the grb have widgets, if it does not have
     (if it is empty), hides the QGroupBox
    :param dialog: QDialog or QMainWindow
    :return: Dictionario with names of hidden QGroupBox
    """
    grb_list = {}
    grbox_list = dialog.findChildren(QGroupBox)
    for grbox in grbox_list:
        widget_list = grbox.findChildren(QWidget)
        if len(widget_list) == 0:
            grb_list[grbox.objectName()] = 0
            grbox.setVisible(False)

    return grb_list


def set_completer_lineedit(qlineedit, list_items):
    """Set a completer into a QLineEdit
    :param qlineedit: Object where to set the completer (QLineEdit)
    :param list_items: List of items to set into the completer (List)["item1","item2","..."]
    """
    completer = QCompleter()
    completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    completer.setMaxVisibleItems(10)
    completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
    completer.setFilterMode(Qt.MatchFlag.MatchContains)
    completer.popup().setStyleSheet("color: black;")
    qlineedit.setCompleter(completer)
    model = QStringListModel()
    model.setStringList(list_items)
    completer.setModel(model)


def set_completer_rows(widget, rows, filter_mode: QtMatchFlag = "starts"):
    """Set a completer into a widget
    :param widget: Object where to set the completer (QLineEdit)
    :param rows: rows to set into the completer (List)["item1","item2","..."]
    """
    list_values = []
    if rows is not None:
        for row in rows:
            list_values.append(str(row[0]))

    # Set completer and model: add autocomplete in the widget
    completer = QCompleter()
    completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    completer.setFilterMode(match_flags.get(filter_mode))
    widget.setCompleter(completer)
    model = QStringListModel()
    model.setStringList(list_values)
    completer.setModel(model)


def add_combo_on_tableview(qtable, rows, field, widget_pos, combo_values):
    """Set one column of a QtableView as QComboBox with values from database.
    :param qtable: QTableView to fill
    :param rows: List of items to set QComboBox (["..", "..."])
    :param field: Field to set QComboBox (String)
    :param widget_pos: Position of the column where we want to put the QComboBox (integer)
    :param combo_values: List of items to populate QComboBox (["..", "..."])
    :return:
    """
    for x in range(0, len(rows)):
        try:
            from ..core.utils.async_combo import GwAsyncComboBox
            combo = GwAsyncComboBox()
        except ImportError:
            combo = QComboBox()
        row = rows[x]
        # Populate QComboBox
        fill_combo_values(combo, combo_values)
        # Set QCombobox to wanted item
        set_combo_value(combo, str(row[field]), 1)
        # Get index and put QComboBox into QTableView at index position
        idx = qtable.model().index(x, widget_pos)
        qtable.setIndexWidget(idx, combo)
        # noinspection PyUnresolvedReferences
        combo.currentIndexChanged.connect(partial(set_status, combo, qtable, x, widget_pos))


def set_status(qtable, combo, pos_x, combo_pos, col_update):
    """Update values from QComboBox to QTableView
    :param qtable: QTableView Where update values
    :param combo: QComboBox from which we will take the value
    :param pos_x: Position of the row where we want to update value (integer)
    :param combo_pos: Position of the column where we want to put the QComboBox (integer)
    :param col_update: Column to update into QTableView.Model() (integer)
    :return:
    """
    elem = combo.itemData(combo.currentIndex())
    i = qtable.model().index(pos_x, combo_pos)
    qtable.model().setData(i, elem[0])
    i = qtable.model().index(pos_x, col_update)
    qtable.model().setData(i, elem[0])


def document_open(qtable, field_name):
    """Open selected document"""
    msg = None

    # Get selected rows
    field_index = qtable.model().fieldIndex(field_name)
    selected_list = qtable.selectionModel().selectedRows(field_index)
    if not selected_list:
        msg = "Any record selected"
    elif len(selected_list) > 1:
        msg = "More then one document selected. Select just one document."

    if msg:
        tools_qgis.show_warning(msg)
        return
    path = selected_list[0].data()
    # Check if file exist
    if os.path.exists(path):
        # Open the document
        if sys.platform == "win32":
            os.startfile(path)
        else:
            opener = "open" if sys.platform == "darwin" else "xdg-open"
            subprocess.call([opener, path])
    else:
        webbrowser.open(path)


def delete_rows_tableview(qtable: QTableView):
    """Delete record from selected rows in a QTableView"""
    # Get selected rows. 0 is the column of the pk 0 'id'
    selected_list = qtable.selectionModel().selectedRows(0)
    if len(selected_list) == 0:
        message = "Any record selected"
        show_info_box(message)
        return

    selected_id = []
    for index in selected_list:
        doc_id = index.data()
        selected_id.append(str(doc_id))
    message = "Are you sure you want to delete these records?"
    title = "Delete records"
    answer = show_question(message, title, ",".join(selected_id))
    if answer:
        for model_index in qtable.selectionModel().selectedRows():
            index = QPersistentModelIndex(model_index)
            qtable.model().removeRow(index.row())
        status = qtable.model().submit()

        if not status:
            error = qtable.model().lastError().text()
            msg = "Error deleting data"
            tools_qgis.show_warning(msg, parameter=error)
        else:
            msg = "Record deleted"
            tools_qgis.show_info(msg)


def reset_model(dialog, table_object, feature_type):
    """Reset model of the widget"""
    table_relation = f"{table_object}_x_{feature_type}"
    widget_name = f"tbl_{table_relation}"
    widget = get_widget(dialog, widget_name)
    if widget:
        widget.setModel(None)


def get_feature_by_id(layer, id, field_id=None):
    if field_id is not None:
        expr = f"{field_id} = '{id}'"
        features = layer.getFeatures(expr)
        for feature in features:
            if feature[field_id] == id:
                return feature
    else:
        return layer.getFeature(id)

    return False


def show_details(detail_text, title=None, inf_text=None, text_params=None, title_params=None, copy_button=False):
    """Shows a message box with detail information"""
    iface.messageBar().clearWidgets()
    msg_box = QMessageBox()
    msg_box.setIcon(QMessageBox.Icon.Information)
    detail_text_translated = ""
    detail_text_plain = ""
    if detail_text:
        detail_text_translated = tr(detail_text, list_params=text_params)
        msg_box.setText(detail_text_translated)
        text_document = QTextDocument()
        text_document.setHtml(detail_text_translated)
        detail_text_plain = text_document.toPlainText()
    if title:
        title = tr(title, list_params=title_params)
        msg_box.setWindowTitle(title)
    if inf_text:
        inf_text = tr(inf_text)
        msg_box.setInformativeText(inf_text)
    msg_box.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint)
    msg_box.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Close)
    if copy_button:
        copy_btn = msg_box.addButton(tr("Copy to clipboard"), QMessageBox.ButtonRole.ActionRole)
        copy_btn.clicked.connect(
            lambda: (
                QApplication.clipboard().setText(detail_text_plain or detail_text_translated or ""),
                tools_qgis.show_success("Copied to clipboard"),
            )
        )
    msg_box.setDefaultButton(QMessageBox.StandardButton.Ok)
    msg_box.exec()


def show_warning_open_file(text, inf_text, file_path, context_name="giswater", text_params=None):
    """Show warning message with a button to open @file_path"""
    widget = iface.messageBar().createMessage(tr(text, context_name, list_params=text_params), tr(inf_text))
    button = QPushButton(widget)
    button.setText(tr("Open file"))
    button.clicked.connect(partial(tools_os.open_file, file_path))
    widget.layout().addWidget(button)
    iface.messageBar().pushWidget(widget, 1)


def _manage_messagebox_buttons(buttons):
    """Convert list of button names to QMessageBox flags and determine default button

    Args:
        buttons: List of button names like ["Yes", "No"] or None for default ["Ok", "Cancel"]

    Returns:
        tuple: (button_flags, default_button)

    """
    button_map = {
        "Yes": QMessageBox.StandardButton.Yes,
        "No": QMessageBox.StandardButton.No,
        "Ok": QMessageBox.StandardButton.Ok,
        "Cancel": QMessageBox.StandardButton.Cancel,
        "Save": QMessageBox.StandardButton.Save,
        "Discard": QMessageBox.StandardButton.Discard,
        "Close": QMessageBox.StandardButton.Close,
        "Apply": QMessageBox.StandardButton.Apply,
    }

    # Set buttons (default to Ok/Cancel if not specified)
    if buttons is None:
        buttons = ["Ok", "Cancel"]

    button_flags = QMessageBox.StandardButton.NoButton
    for btn_name in buttons:
        if btn_name in button_map:
            button_flags |= button_map[btn_name]

    # Set default button (first positive action button)
    if "Yes" in buttons:
        default_button = QMessageBox.StandardButton.Yes
    elif "Ok" in buttons:
        default_button = QMessageBox.StandardButton.Ok
    elif "Save" in buttons:
        default_button = QMessageBox.StandardButton.Save
    else:
        default_button = button_map.get(buttons[0], QMessageBox.StandardButton.Ok)

    return button_flags, default_button


def _message_parent(parent=None):
    """Return explicit parent or the active modal dialog, if any."""
    if parent is not None:
        return parent
    return lib_vars.session_vars.get("message_parent")


def show_question(
    text,
    title="Info",
    inf_text=None,
    context_name="giswater",
    parameter=None,
    force_action=False,
    msg_params=None,
    title_params=None,
    buttons=None,
    parent=None,
):
    """Ask question to the user

    Args:
        buttons: List of button names like ["Yes", "No"] or ["Save", "Discard"].
                 Defaults to ["Ok", "Cancel"] if None.

    """
    # Expert mode does not ask and accept all actions
    if lib_vars.user_level["level"] not in (None, "None") and not force_action:
        if lib_vars.user_level["level"] not in lib_vars.user_level["showquestion"]:
            return True

    msg_parent = _message_parent(parent)
    msg_box = QMessageBox(msg_parent) if msg_parent is not None else QMessageBox()
    msg = tr(text, context_name, list_params=msg_params)
    if parameter:
        msg += ": " + str(parameter)
    if len(msg) > 750:
        msg = msg[:750] + "\n[...]"
    msg_box.setText(msg)

    if title:
        title = tr(title, context_name, list_params=title_params)
        msg_box.setWindowTitle(title)

    if inf_text:
        inf_text = tr(inf_text, context_name)
        if len(inf_text) > 500:
            inf_text = inf_text[:500] + "\n[...]"
        msg_box.setInformativeText(inf_text)

    # Get button configuration
    button_flags, default_button = _manage_messagebox_buttons(buttons)
    msg_box.setStandardButtons(button_flags)
    msg_box.setDefaultButton(default_button)

    # Set icon for the type of message
    msg_box.setIcon(QMessageBox.Icon.Question)

    # Set window icon
    icon_folder = f"{lib_vars.plugin_dir}{os.sep}icons"
    icon_path = f"{icon_folder}{os.sep}dialogs{os.sep}136.png"
    giswater_icon = QIcon(icon_path)
    msg_box.setWindowIcon(giswater_icon)

    if msg_parent is None:
        msg_box.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint)

    ret = msg_box.exec()
    # Return True for positive actions (Yes, Ok, Save, Apply)
    if ret in (
        QMessageBox.StandardButton.Ok,
        QMessageBox.StandardButton.Yes,
        QMessageBox.StandardButton.Save,
        QMessageBox.StandardButton.Apply,
    ):
        return True
    else:
        return False


def show_info_box(
    text, title=None, inf_text=None, context_name="giswater", parameter=None, msg_params=None, title_params=None,
    parent=None,
):
    """Show information box to the user"""
    msg = ""
    if text:
        msg = tr(text, context_name, list_params=msg_params)
        if parameter:
            msg += ": " + str(parameter)

    msg_parent = _message_parent(parent)
    msg_box = QMessageBox(msg_parent) if msg_parent is not None else QMessageBox()
    if len(msg) > 750:
        msg = msg[:750] + "\n[...]"
    msg_box.setText(msg)
    if msg_parent is None:
        msg_box.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint)
    if title:
        title = tr(title, context_name, list_params=title_params)
        msg_box.setWindowTitle(title)
    if inf_text:
        inf_text = tr(inf_text, context_name)
        if len(inf_text) > 500:
            inf_text = inf_text[:500] + "\n[...]"
        msg_box.setInformativeText(inf_text)
    msg_box.setIcon(QMessageBox.Icon.Information)
    msg_box.setDefaultButton(QMessageBox.StandardButton.No)
    msg_box.exec()


def show_warning_box(
    text,
    title="Warning",
    inf_text=None,
    context_name="giswater",
    parameter=None,
    msg_params=None,
    title_params=None,
    parent=None,
):
    """Show warning box to the user"""
    msg = ""
    if text:
        msg = tr(text, context_name, list_params=msg_params)
        if parameter:
            msg += ": " + str(parameter)

    msg_parent = _message_parent(parent)
    msg_box = QMessageBox(msg_parent) if msg_parent is not None else QMessageBox()
    if len(msg) > 750:
        msg = msg[:750] + "\n[...]"
    msg_box.setText(msg)
    if msg_parent is None:
        msg_box.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint)
    if title:
        title = tr(title, context_name, list_params=title_params)
        msg_box.setWindowTitle(title)
    if inf_text:
        inf_text = tr(inf_text, context_name)
        if len(inf_text) > 500:
            inf_text = inf_text[:500] + "\n[...]"
        msg_box.setInformativeText(inf_text)
    msg_box.setIcon(QMessageBox.Icon.Warning)
    msg_box.setDefaultButton(QMessageBox.StandardButton.Ok)
    msg_box.exec()


def set_text_bold(widget, pattern):
    """Set bold text when word match with pattern
    :param widget: QTextEdit
    :param pattern: Text to find used as pattern for QRegularExpression (String)
    :return:
    """
    cursor = widget.textCursor()
    format_ = QTextCharFormat()
    format_.setFontWeight(QFont.Weight.Bold)
    regex = QRegularExpression(pattern)
    text = widget.toPlainText()
    pos = 0
    match = regex.match(text, pos)

    while match.hasMatch():
        start = match.capturedStart()
        length = match.capturedLength()

        # Set cursor at begin of match
        cursor.setPosition(start, QTextCursor.MoveMode.MoveAnchor)
        # Set cursor at end of match
        cursor.setPosition(start + length, QTextCursor.MoveMode.KeepAnchor)
        # Apply format
        cursor.mergeCharFormat(format_)

        # Move to the next match
        pos = start + length
        match = regex.match(text, pos)


def set_stylesheet(widget, style="border: 2px solid red"):
    widget.setStyleSheet(style)


def _translate_line(line, context_name, aux_context):
    """Translate a single line with fallback to aux_context."""
    translated = QCoreApplication.translate(context_name, line)
    if translated == line:
        translated = QCoreApplication.translate(aux_context, line)
    return translated


def _translate_multiline(str_message, context_name, aux_context):
    """Translate a multiline string by translating each line separately."""
    lines = str_message.split("\n")
    translated_lines = [_translate_line(line, context_name, aux_context) for line in lines]
    return "\n".join(translated_lines)


def _format_params(value, list_params):
    """Format value with parameters if provided."""
    if not list_params:
        return value
    try:
        if not isinstance(list_params, (list, tuple)):
            list_params = (list_params,)
        return value.format(*list_params)
    except (IndexError, KeyError, TypeError):
        return value


def tr(message, context_name="giswater", aux_context="ui_message", default=None, list_params=None):
    """Translate @message looking it in @context_name"""
    if context_name is None:
        context_name = lib_vars.plugin_name

    str_message = str(message)
    if "\n" in str_message:
        value = _translate_multiline(str_message, context_name, aux_context)
    else:
        value = _translate_line(str_message, context_name, aux_context)

    if value == str_message and default is not None:
        value = default

    return _format_params(value, list_params)


def translate_am_cm(schema_name):
    """Translate AM and CM toolbars"""
    # Get locale and schema lang
    locale = tools_qgis.get_locale_schema()
    lang = tools_db.get_rows(f"SELECT language FROM {schema_name}.sys_version")
    lang = lang[0][0]

    # Determine if translation is necessary
    if lang == locale or locale == "no_TR":
        return

    # Get file path
    plugin_dir = lib_vars.plugin_dir
    file_path = f"{plugin_dir}{os.sep}dbmodel{os.sep}{schema_name}{os.sep}i18n{os.sep}{lang}{os.sep}{lang}.sql"
    if not os.path.exists(file_path):
        return

    # Execute SQL statements
    with open(file_path, "r", encoding="utf-8") as file:
        sql = file.read()
        statements = sql.split(";")
        for stmt in statements:
            if stmt.strip():
                tools_db.execute_sql(stmt.strip(), log_sql=False, commit=True)

    sql = f"UPDATE cm.sys_version SET language = '{locale}'"
    tools_db.execute_sql(sql, log_sql=False, commit=True)


def _should_show_exception(description):
    """Helper function to determine if exception should be shown"""
    if not description:
        return True

    dont_show_list = [
        "unknown error",
        "server closed the connection unexpectedly",
        "message contents do not agree with length in message",
        "unexpected field count in",
    ]
    for dont_show in dont_show_list:
        if dont_show in description:
            return False
    if "server sent data" in description and "without prior row description" in description:
        return False
    return True


def manage_exception_db(
    exception=None,
    sql=None,
    stack_level=2,
    stack_level_increase=0,
    filepath=None,
    schema_name=None,
    pause_on_exception=False,
):
    """Manage exception in database queries and show information to the user"""
    show_exception_msg = _should_show_exception(str(exception) if exception else "")

    try:
        stack_level += stack_level_increase
        file_name, function_line, function_name = _get_stack_info(stack_level)

        msg = _build_exception_message(file_name, function_line, function_name, exception, filepath, sql, schema_name)
        lib_vars.session_vars["last_error_msg"] = msg

        # Show exception message in dialog and log it
        if show_exception_msg:
            title = "Database error"
            show_exception_message(title, msg)
            if pause_on_exception:
                pause()
        else:
            message = "Exception message not shown to user"
            tools_log.log_warning(message)
        tools_log.log_warning(msg, stack_level_increase=2)

    except Exception:
        title = "Unhandled Error"
        manage_exception(title)


def pause():
    """Pause execution until user clicks accept on dialog"""
    dlg_info.btn_accept.setVisible(True)
    dlg_info.btn_close.setVisible(False)
    dlg_info.btn_accept.clicked.connect(lambda: dlg_info.close())
    dlg_info.exec()


def show_exception_message(
    title=None,
    msg="",
    window_title="Information about exception",
    pattern=None,
    context_name="giswater",
    title_params=None,
    msg_params=None,
    parent=None,
):
    """Show exception message in dialog"""
    # Show dialog only if we are not in a task process
    if len(lib_vars.session_vars["threads"]) > 0:
        return

    lib_vars.session_vars["last_error_msg"] = None
    dlg_info.btn_accept.setVisible(False)
    dlg_info.btn_close.clicked.connect(lambda: dlg_info.close())
    dlg_info.setWindowTitle(tr(window_title))
    if title:
        title = tr(title, context_name, list_params=title_params)
        dlg_info.lbl_text.setText(title)
    if msg:
        msg = tr(msg, context_name, list_params=msg_params)
    set_widget_text(dlg_info, dlg_info.tab_log_txt_infolog, msg)
    message_parent = _message_parent(parent)
    if message_parent is not None:
        dlg_info.setParent(message_parent)
        dlg_info.setWindowFlags(Qt.WindowType.Dialog)
    else:
        dlg_info.setParent(None)
        dlg_info.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint)
    if pattern is None:
        pattern = f"""{tr("File name")}:|{tr("Function name")}:|{tr("Line number")}:|{tr("SQL")}:|{tr("SQL File")}:
                    |{tr("Detail")}:|{tr("Context")}:|{tr("Description")}:|{tr("Schema name")}:|{tr("Message error")}:
                    |{tr("Error type")}:"""
    set_text_bold(dlg_info.tab_log_txt_infolog, pattern)

    dlg_info.show()
    if message_parent is not None:
        dlg_info.raise_()
        dlg_info.activateWindow()


def manage_exception(title=None, description=None, sql=None, schema_name=None):
    """Manage exception and show information to the user"""
    # Get traceback
    trace = traceback.format_exc()
    exc_type, exc_obj, exc_tb = sys.exc_info()
    path = exc_tb.tb_frame.f_code.co_filename
    file_name = os.path.split(path)[1]

    # Set exception message details
    msg = ""
    msg += f"""{tr("Error type")}: {exc_type}\n"""
    msg += f"""{tr("File name")}: {file_name}\n"""
    msg += f"""{tr("Line number")}: {exc_tb.tb_lineno}\n"""
    msg += f"{trace}\n"
    if description:
        msg += f"""{tr("Description")}: {description}\n"""
    if sql:
        msg += f"""{tr("SQL")}:\n {sql}\n\n"""
    msg += f"""{tr("Schema name")}: {schema_name}"""

    # Translate title if exist
    if title:
        title = tr(title)

    # Show exception message in dialog and log it
    show_exception_message(title, msg)
    tools_log.log_warning(msg)

    # Log exception message
    tools_log.log_warning(msg)

    # Show exception message only if we are not in a task process
    if len(lib_vars.session_vars["threads"]) == 0:
        show_exception_message(title, msg)


def fill_combo_unicodes(combo):
    """Populate combo with full list of codes"""
    unicode_list = []
    matches = ["utf8", "windows", "latin"]

    for item in list(aliases.items()):
        if any(item[0].startswith(match) for match in matches):
            unicode_list.append((str(item[0]), str(item[0])))

    fill_combo_values(combo, unicode_list)


def set_table_model(dialog, table_object, table_name, expr_filter, columns_to_show: List[str] = None):
    """Sets a TableModel to @widget_name attached to
    @table_name and filter @expr_filter
    """
    if columns_to_show is None:
        columns_to_show = []
    # Validate expression
    is_valid, expr = _validate_expression(expr_filter)
    if not is_valid:
        return expr

    # Create and configure model
    model = _create_table_model(table_name)
    if model is None:
        return expr

    # Get widget
    widget = _get_widget_from_table_object(dialog, table_object)
    if widget is None or isdeleted(widget):
        return expr

    # Apply model and filter
    if expr_filter:
        widget.setModel(model)
        widget.model().setFilter(expr_filter)
        widget.model().select()
    else:
        widget.setModel(None)

    # Hide columns that are not in the list of columns to show
    if columns_to_show:
        for i in range(model.columnCount()):
            if model.headerData(i, Qt.Orientation.Horizontal) not in columns_to_show:
                widget.hideColumn(i)

    return expr


def create_datetime(object_name, allow_null=True, set_cal_popup=True, display_format="dd/MM/yyyy"):
    """Create a QgsDateTimeEdit widget"""
    widget = QgsDateTimeEdit()
    widget.setObjectName(object_name)
    widget.setAllowNull(allow_null)
    widget.setCalendarPopup(set_cal_popup)
    widget.setDisplayFormat(display_format)
    btn_calendar = widget.findChild(QToolButton)
    btn_calendar.clicked.connect(partial(set_calendar_empty, widget))
    return widget


# region private functions


def _add_translator(log_info=False):
    """Add translation file to the list of translation files to be used for translations"""
    locale = tools_qgis.get_ui_language_locale()

    locale_path = os.path.join(lib_vars.plugin_dir, "i18n", f"{lib_vars.plugin_name.lower()}_{locale}.qm")
    if not os.path.exists(locale_path):
        if log_info:
            msg = "Locale not found"
            tools_log.log_info(msg, parameter=locale_path)
        locale_path = os.path.join(lib_vars.plugin_dir, "i18n", f"{lib_vars.plugin_name}_en_US.qm")
        # If English locale file not found, exit function
        if not os.path.exists(locale_path):
            if log_info:
                msg = "English locale not found"
                tools_log.log_info(msg, parameter=locale_path)
            return

    if os.path.exists(locale_path):
        translator.load(locale_path)
        QCoreApplication.installTranslator(translator)
        if log_info:
            msg = "Add translator ({0})"
            msg_params = (locale,)
            tools_log.log_info(msg, parameter=locale_path, msg_params=msg_params)
    else:
        if log_info:
            msg = "Locale not found ({0})"
            msg_params = (locale,)
            tools_log.log_info(msg, parameter=locale_path, msg_params=msg_params)


def _translate_form(context_name, dialog, aux_context="ui_message"):
    """Translate widgets of the form to current language"""
    type_widget_list = [
        QCheckBox,
        QGroupBox,
        QLabel,
        QPushButton,
        QRadioButton,
        QLineEdit,
        QTextEdit,
        QTabWidget,
        QToolBox,
    ]
    for widget_type in type_widget_list:
        widget_list = dialog.findChildren(widget_type)
        for widget in widget_list:
            _translate_widget(context_name, widget, aux_context)

    # Translate title of the form
    text = tr("title", context_name, aux_context)
    if text != "title":
        dialog.setWindowTitle(text)


def _translate_widget(context_name, widget, aux_context="ui_message"):
    """Translate widget text"""
    if widget is None:
        return

    widget_name = ""
    try:
        if type(widget) is QTabWidget:
            _translate_tab_widget(widget, context_name, aux_context)
        elif type(widget) is QToolBox:
            _translate_tool_box(widget, context_name, aux_context)
        elif type(widget) is QGroupBox:
            _translate_group_box(widget, context_name, aux_context)
        elif type(widget) in (QLineEdit, QTextEdit):
            _translate_tooltip(context_name, widget, aux_context=aux_context)
        else:
            _translate_standard_widget(widget, context_name, aux_context)

    except Exception as e:
        msg = "{0} --> {1} --> {2}"
        msg_params = (widget_name, type(e).__name__, e)
        tools_log.log_info(msg, msg_params=msg_params)


def _translate_tooltip(context_name, widget, idx=None, aux_context="ui_message"):
    """Translate tooltips widgets of the form to current language
    If we find a translation, it will be put
    If the object does not have a tooltip we will put the object text itself as a tooltip
    """
    if type(widget) is QTabWidget:
        widget_name = widget.widget(idx).objectName()
        tooltip = tr(f"tooltip_{widget_name}", context_name, aux_context)
        if tooltip not in (f"tooltip_{widget_name}", None, "None"):
            widget.setTabToolTip(idx, tooltip)
        elif widget.toolTip() in ("", None):
            widget.setTabToolTip(idx, widget.tabText(idx))
    else:
        widget_name = widget.objectName()
        tooltip = tr(f"tooltip_{widget_name}", context_name, aux_context)
        if tooltip not in (f"tooltip_{widget_name}", None, "None"):
            widget.setToolTip(tooltip)
        elif widget.toolTip() in ("", None):
            if type(widget) is QGroupBox:
                widget.setToolTip(widget.title())
            elif type(widget) in (QTextEdit, QPlainTextEdit):
                widget.setToolTip(widget.toPlainText())
            elif type(widget) is QWidget:
                widget.setToolTip("")
            elif type(widget) in (QTextEdit, QPlainTextEdit):
                widget.setToolTip(widget.toPlainText())
            else:
                widget.setToolTip(widget.text())


def _set_model_by_list(string_list, proxy_model):
    """Set the model according to the list"""
    model = QStringListModel()
    model.setStringList(string_list)
    proxy_model.setSourceModel(model)
    proxy_model.setFilterKeyColumn(0)


def _validate_expression(expr_filter):
    """Helper function to validate expression filter"""
    expr = None
    if expr_filter:
        (is_valid, expr) = check_expression_filter(expr_filter)
        if not is_valid:
            return None, expr
    return True, expr


def _create_table_model(table_name):
    """Helper function to create and configure table model"""
    if lib_vars.schema_name and lib_vars.schema_name not in table_name:
        table_name = f"{lib_vars.schema_name}.{table_name}"

    model = QSqlTableModel(db=lib_vars.qgis_db_credentials)
    model.setTable(table_name)
    model.setEditStrategy(QSqlTableModel.EditStrategy.OnManualSubmit)
    model.select()

    if model.lastError().isValid():
        if "Unable to find table" in model.lastError().text():
            tools_db.reset_qsqldatabase_connection()
        else:
            tools_qgis.show_warning(model.lastError().text())
        return None
    return model


def _get_widget_from_table_object(dialog, table_object: Union[str, QTableView]) -> Optional[QTableView]:
    """Helper function to get widget from table object"""
    if type(table_object) is str:
        widget = get_widget(dialog, table_object)
        if widget is None:
            msg = "Widget not found"
            tools_log.log_info(msg, parameter=table_object)
            return None
        if type(widget) is not QTableView:
            msg = "Widget is not a QTableView"
            msg_params = ("QTableView",)
            tools_log.log_info(msg, parameter=table_object, msg_params=msg_params)
            return None
    elif type(table_object) is QTableView:
        widget: QTableView = table_object
    else:
        msg = "{0} is not a table name or {1}"
        msg_params = ("Table_object", "QTableView")
        tools_log.log_info(msg, list_params=msg_params)
        return None
    return widget


def _translate_tab_widget(widget, context_name, aux_context):
    """Helper function to translate QTabWidget"""
    num_tabs = widget.count()
    for i in range(0, num_tabs):
        widget_name = widget.widget(i).objectName()
        text = tr(widget_name, context_name, aux_context)
        if text not in (widget_name, None, "None"):
            widget.setTabText(i, text)
        else:
            widget_text = widget.tabText(i)
            text = tr(widget_text, context_name, aux_context)
            if text != widget_text:
                widget.setTabText(i, text)
        _translate_tooltip(context_name, widget, i, aux_context=aux_context)


def _translate_tool_box(widget, context_name, aux_context):
    """Helper function to translate QToolBox"""
    num_tabs = widget.count()
    for i in range(0, num_tabs):
        widget_name = widget.widget(i).objectName()
        text = tr(widget_name, context_name, aux_context)
        if text not in (widget_name, None, "None"):
            widget.setItemText(i, text)
        else:
            widget_text = widget.itemText(i)
            text = tr(widget_text, context_name, aux_context)
            if text != widget_text:
                widget.setItemText(i, text)
        _translate_tooltip(context_name, widget.widget(i), aux_context=aux_context)


def _translate_group_box(widget, context_name, aux_context):
    """Helper function to translate QGroupBox"""
    widget_name = widget.objectName()
    text = tr(widget_name, context_name, aux_context)
    if text not in (widget_name, None, "None"):
        widget.setTitle(text)
    else:
        widget_title = widget.title()
        text = tr(widget_title, context_name, aux_context)
        if text != widget_title:
            widget.setTitle(text)
    _translate_tooltip(context_name, widget, aux_context=aux_context)


def _translate_standard_widget(widget, context_name, aux_context):
    """Helper function to translate standard widgets"""
    widget_name = widget.objectName()
    text = tr(widget_name, context_name, aux_context)
    if text not in (widget_name, None, "None"):
        widget.setText(text)
    else:
        widget_text = widget.text()
        text = tr(widget_text, context_name, aux_context)
        if text != widget_text:
            widget.setText(text)
    _translate_tooltip(context_name, widget, aux_context=aux_context)


def _get_text_from_line_edit(widget):
    """Helper function to get text from QLineEdit and similar widgets"""
    return widget.text()


def _get_text_from_spinbox(widget):
    """Helper function to get text from QDoubleSpinBox and QSpinBox"""
    # When the QDoubleSpinbox contains decimals, for example 2,0001 when collecting the value,
    # the spinbox itself sends 2.0000999999, as in reality we only want, maximum 4 decimal places, we round up,
    # thus fixing this small failure of the widget
    return round(widget.value(), 4)


def _get_text_from_text_edit(widget):
    """Helper function to get text from QTextEdit and QPlainTextEdit"""
    return widget.toPlainText()


def _get_text_from_combo(widget):
    """Helper function to get text from QComboBox"""
    return widget.currentText()


def _get_text_from_checkbox(dialog, widget):
    """Helper function to get text from QCheckBox"""
    value = is_checked(dialog, widget)
    if type(value) is bool:
        return str(value)
    return None


def _handle_null_text(text, add_quote, return_string_null):
    """Helper function to handle null/empty text cases"""
    if text in (None, "") and return_string_null:
        text = "null"
    elif text in (None, ""):
        text = ""
    if add_quote and text != "null":
        text = "'" + text + "'"
    return text


def _set_text_for_text_widgets(widget, text, msg_params=None):
    """Helper function to set text for text-based widgets"""
    if str(text) == "None":
        text = ""
    else:
        text = tr(f"{text}", list_params=msg_params)
    if type(widget) is QPlainTextEdit:
        widget.insertPlainText(f"{text}")
    else:
        widget.setText(f"{text}")


def _set_text_for_spinbox(widget, text):
    """Helper function to set text for spinbox widgets"""
    if text == "None" or text == "null":
        text = 0
    widget.setValue(float(text))


def _get_stack_info(stack_level):
    """Helper function to get stack information"""
    if stack_level >= len(inspect.stack()):
        stack_level = len(inspect.stack()) - 1
    module_path = inspect.stack()[stack_level][1]
    file_name = tools_os.get_relative_path(module_path, 2)
    function_line = inspect.stack()[stack_level][2]
    function_name = inspect.stack()[stack_level][3]
    return file_name, function_line, function_name


def _build_exception_message(file_name, function_line, function_name, exception, filepath, sql, schema_name):
    """Helper function to build exception message"""
    # Set exception message details
    msg = ""
    msg += f"""{tr("File name")}: {file_name}\n"""
    msg += f"""{tr("Function name")}: {function_name}\n"""
    msg += f"""{tr("Line number")}: {function_line}\n"""
    if exception:
        msg += f"""{tr("Description")}:\n{str(exception)}\n"""
    if filepath:
        msg += f"""{tr("SQL File")}:\n{filepath}\n\n"""
    if sql:
        msg += f"""{tr("SQL")}:\n {sql}\n\n"""
    msg += f"""{tr("Schema name")}: {schema_name}"""

    return msg


# endregion
