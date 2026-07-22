"""This file is part of Giswater
The program is free software: you can redistribute it and/or modify it under the terms of the GNU
General Public License as published by the Free Software Foundation, either version 3 of the License,
or (at your option) any later version.
"""

# -*- coding: utf-8 -*-
import configparser
import re
from functools import partial
from typing import Optional
from warnings import warn

import console
import os.path
import shlex
import sys
from random import randrange

from qgis.PyQt.QtCore import Qt, QTimer, QSettings
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QDockWidget,
    QApplication,
    QPushButton,
    QDialog,
    QVBoxLayout,
    QTextEdit,
    QDialogButtonBox,
)
from qgis.core import (
    QgsExpressionContextUtils,
    QgsProject,
    QgsPointLocator,
    QgsSnappingUtils,
    QgsSnappingConfig,
    QgsTolerance,
    QgsPointXY,
    QgsFeatureRequest,
    QgsRectangle,
    QgsSymbol,
    QgsLineSymbol,
    QgsRendererCategory,
    QgsCategorizedSymbolRenderer,
    QgsGeometry,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsVectorLayer,
    QgsExpression,
    QgsFillSymbol,
    QgsMapToPixel,
    QgsWkbTypes,
    QgsPrintLayout,
    Qgis,
    NULL,
    QgsMapLayer,
)
from qgis.utils import iface, plugin_paths, available_plugins, active_plugins

from . import tools_log, tools_qt, tools_os, tools_db
from . import lib_vars

# List of user parameters (optionals)
user_parameters = {"log_sql": None, "show_message_durations": None, "aux_context": "ui_message"}

# Define message level constants
MESSAGE_LEVEL_INFO = Qgis.MessageLevel.Info  # Blue
MESSAGE_LEVEL_WARNING = Qgis.MessageLevel.Warning  # Yellow
MESSAGE_LEVEL_CRITICAL = Qgis.MessageLevel.Critical  # Red
MESSAGE_LEVEL_SUCCESS = Qgis.MessageLevel.Success  # Green

# Define message duration constants
DEFAULT_MESSAGE_DURATION = 10
MINIMUM_WARNING_DURATION = 10


def get_feature_by_expr(layer, expr_filter):
    # Check filter and existence of fields
    expr = QgsExpression(expr_filter)
    if expr.hasParserError():
        message = f"{expr.parserErrorString()}: {expr_filter}"
        show_warning(message)
        return

    it = layer.getFeatures(QgsFeatureRequest(expr))
    # Iterate over features
    for feature in it:
        return feature

    return False


def show_message(
    text,
    message_level=MESSAGE_LEVEL_WARNING,
    duration=DEFAULT_MESSAGE_DURATION,
    context_name="giswater",
    parameter=None,
    title="",
    logger_file=True,
    dialog=iface,
    sqlcontext=None,
    msg_params=None,
    title_params=None,
):
    """Show message to the user with selected message level
    :param text: The text to be shown (String)
    :param message_level: Message level constant
    :param duration: The duration of the message (int)
    :param context_name: Where to look for translating the message
    :param parameter: A text to show after the message (String)
    :param title: The title of the message (String)
    :param logger_file: Whether it should log the message in a file or not (bool)
    """
    global user_parameters

    # Get optional parameter 'show_message_durations'
    dev_duration = user_parameters.get("show_message_durations")
    # If is set, use this value
    if dev_duration not in (None, "None"):
        if (
            message_level in (MESSAGE_LEVEL_WARNING, MESSAGE_LEVEL_CRITICAL)
            and int(dev_duration) < MINIMUM_WARNING_DURATION
        ):  # noqa: E501
            duration = DEFAULT_MESSAGE_DURATION
        else:
            duration = int(dev_duration)
    msg = None
    if text:
        msg = tools_qt.tr(text, context_name, user_parameters["aux_context"], list_params=msg_params)
        if parameter:
            msg += f": {parameter}"

    tlt = tools_qt.tr(title, context_name, user_parameters["aux_context"], list_params=title_params) if title else ""

    # Show message
    try:
        if message_level in (MESSAGE_LEVEL_WARNING, MESSAGE_LEVEL_CRITICAL) and sqlcontext is not None:
            # show message with button with the sqlcontext
            show_message_function(
                msg,
                lambda: show_sqlcontext_dialog(sqlcontext, msg, title, 500, 300),
                "Show more",
                message_level,
                duration,
                context_name,
                logger_file,
                dialog,
            )
        else:
            dialog.messageBar().pushMessage(tlt, msg, message_level, duration)
    except Exception as e:  # This is because "messageBar().pushMessage" is only available for QMainWindow, not QDialog.
        print("Exception show_message: ", e)
        iface.messageBar().pushMessage(tlt, msg, message_level, duration)

    # Check if logger to file
    if lib_vars.logger and logger_file:
        lib_vars.logger.info(text)


def show_message_link(
    text,
    url,
    btn_text="Open",
    message_level=MESSAGE_LEVEL_INFO,
    duration=DEFAULT_MESSAGE_DURATION,
    context_name="giswater",
    logger_file=True,
    dialog=iface,
):
    """Show message to the user with selected message level and a button to open the url
    :param text: The text to be shown (String)
    :param url: The url that will be opened by the button. It will also show after the message (String)
    :param btn_text: The text of the button (String)
    :param message_level: {INFO = 0(blue), WARNING = 1(yellow), CRITICAL = 2(red), SUCCESS = 3(green)}
    :param duration: The duration of the message (int)
    :param context_name: Where to look for translating the message
    :param logger_file: Whether it should log the message in a file or not (bool)
    """
    global user_parameters

    # Get optional parameter 'show_message_durations'
    dev_duration = user_parameters.get("show_message_durations")
    # If is set, use this value
    if dev_duration not in (None, "None"):
        if message_level in (1, 2) and int(dev_duration) < 10:
            duration = 10
        else:
            duration = int(dev_duration)
    msg = None
    if text:
        msg = tools_qt.tr(text, context_name, user_parameters["aux_context"])

    # Create the message with the button
    widget = iface.messageBar().createMessage(f"{msg}", f"{url}")
    button = QPushButton(widget)
    button.setText(f"{btn_text}")
    button.pressed.connect(partial(tools_os.open_file, url))
    widget.layout().addWidget(button)

    # Show the message
    dialog.messageBar().pushWidget(widget, message_level, duration)

    # Check if logger to file
    if lib_vars.logger and logger_file:
        lib_vars.logger.info(text)


def show_message_function(
    text,
    function,
    btn_text="Open",
    message_level=MESSAGE_LEVEL_INFO,
    duration=DEFAULT_MESSAGE_DURATION,
    context_name="giswater",
    logger_file=True,
    dialog=iface,
    text_params=None,
):
    """Show message to the user with selected message level and a button to open the url
    :param text: The text to be shown (String)
    :param function: The function (can be a ``partial()`` object) to execute.
    :param btn_text: The text of the button (String)
    :param message_level: Message level constant
    :param duration: The duration of the message (int)
    :param context_name: Where to look for translating the message
    :param logger_file: Whether it should log the message in a file or not (bool)
    """
    global user_parameters

    # Get optional parameter 'show_message_durations'
    dev_duration = user_parameters.get("show_message_durations")
    # If is set, use this value
    if dev_duration not in (None, "None") and duration > 0:
        if (
            message_level in (MESSAGE_LEVEL_WARNING, MESSAGE_LEVEL_CRITICAL)
            and int(dev_duration) < MINIMUM_WARNING_DURATION
        ):  # noqa: E501
            duration = DEFAULT_MESSAGE_DURATION
        else:
            duration = int(dev_duration)
    msg = None
    if text:
        msg = tools_qt.tr(text, context_name, user_parameters["aux_context"], list_params=text_params)

    # Create the message with the button
    widget = iface.messageBar().createMessage(f"{msg}")
    button = QPushButton(widget)
    button.setText(f"{btn_text}")
    button.pressed.connect(function)
    widget.layout().addWidget(button)

    # Show the message
    dialog.messageBar().pushWidget(widget, message_level, duration)

    # Check if logger to file
    if lib_vars.logger and logger_file:
        lib_vars.logger.info(text)


def show_info(
    text,
    duration=DEFAULT_MESSAGE_DURATION,
    context_name="giswater",
    parameter=None,
    logger_file=True,
    title="",
    dialog=iface,
    msg_params=None,
    title_params=None,
):
    """Show information message to the user
    :param text: The text to be shown (String)
    :param duration: The duration of the message (int)
    :param context_name: Where to look for translating the message
    :param parameter: A text to show after the message (String)
    :param logger_file: Whether it should log the message in a file or not (bool)
    :param title: The title of the message (String)
    """
    show_message(
        text,
        MESSAGE_LEVEL_INFO,
        duration,
        context_name,
        parameter,
        title,
        logger_file,
        dialog=dialog,
        msg_params=msg_params,
        title_params=title_params,
    )


def show_warning(
    text,
    duration=DEFAULT_MESSAGE_DURATION,
    context_name="giswater",
    parameter=None,
    logger_file=True,
    title="",
    dialog=iface,
    msg_params=None,
    title_params=None,
):
    """Show warning message to the user
    :param text: The text to be shown (String)
    :param duration: The duration of the message (int)
    :param context_name: Where to look for translating the message
    :param parameter: A text to show after the message (String)
    :param logger_file: Whether it should log the message in a file or not (bool)
    :param title: The title of the message (String)
    """
    show_message(
        text,
        MESSAGE_LEVEL_WARNING,
        duration,
        context_name,
        parameter,
        title,
        logger_file,
        dialog=dialog,
        msg_params=msg_params,
        title_params=title_params,
    )


def show_critical(
    text,
    duration=DEFAULT_MESSAGE_DURATION,
    context_name="giswater",
    parameter=None,
    logger_file=True,
    title="",
    dialog=iface,
    msg_params=None,
    title_params=None,
):
    """Show critical message to the user
    :param text: The text to be shown (String)
    :param duration: The duration of the message (int)
    :param context_name: Where to look for translating the message
    :param parameter: A text to show after the message (String)
    :param logger_file: Whether it should log the message in a file or not (bool)
    :param title: The title of the message (String)
    """
    show_message(
        text,
        MESSAGE_LEVEL_CRITICAL,
        duration,
        context_name,
        parameter,
        title,
        logger_file,
        dialog=dialog,
        msg_params=msg_params,
        title_params=title_params,
    )


def show_success(
    text,
    duration=DEFAULT_MESSAGE_DURATION,
    context_name="giswater",
    parameter=None,
    logger_file=True,
    title="",
    dialog=iface,
    msg_params=None,
    title_params=None,
):
    """Show success message to the user
    :param text: The text to be shown (String)
    :param duration: The duration of the message (int)
    :param context_name: Where to look for translating the message
    :param parameter: A text to show after the message (String)
    :param logger_file: Whether it should log the message in a file or not (bool)
    :param title: The title of the message (String)
    """
    show_message(
        text,
        MESSAGE_LEVEL_SUCCESS,
        duration,
        context_name,
        parameter,
        title,
        logger_file,
        dialog=dialog,
        msg_params=msg_params,
        title_params=title_params,
    )


def show_sqlcontext_dialog(
    sqlcontext: str, msg: str, title: str, min_width: int = 400, min_height: int = 200, context_name="giswater"
):
    """Displays a dialog with the SQL context in a more detailed, error-specific format,
    allowing the user to copy the error message.

    :param sqlcontext: The SQL context to display (String)
    :param msg: The message to display above the sqlcontext (String)
    :param title: The title of the dialog window (String)
    :param min_width: The minimum width of the dialog (int)
    :param min_height: The minimum height of the dialog (int)
    """
    dialog = QDialog()

    # Title translation
    translated_title = tools_qt.tr(title or "SQL Context", context_name, user_parameters["aux_context"])
    dialog.setWindowTitle(translated_title)

    dialog.setMinimumWidth(min_width)
    dialog.setMinimumHeight(min_height)

    layout = QVBoxLayout()

    # Full message construction
    message = "SQL Context"
    sqlcontext_label = tools_qt.tr(message, context_name, user_parameters["aux_context"])
    if msg and sqlcontext:
        full_message = f"{msg}\n\n{sqlcontext_label}:\n{sqlcontext}"
    elif msg:
        full_message = msg
    elif sqlcontext:
        full_message = f"{sqlcontext_label}:\n{sqlcontext}"
    else:
        message = "No SQL context available."
        full_message = tools_qt.tr(message, context_name, user_parameters["aux_context"])

    # Add the message text area to allow copying
    text_area = QTextEdit()
    text_area.setPlainText(full_message)
    text_area.setReadOnly(True)
    layout.addWidget(text_area)

    # Add standard close button at the bottom
    button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    button_box.rejected.connect(dialog.reject)
    layout.addWidget(button_box)

    dialog.setLayout(layout)

    # Manage stay on top
    flags = Qt.WindowType.WindowStaysOnTopHint
    dialog.setWindowFlags(flags)

    dialog.exec()


def get_visible_layers(as_str_list=False, as_list=False):
    """Return string as {...} or [...] or list with name of table in DB of all visible layer in TOC
    False, False --> return str like {"name1", "name2", "..."}

    True, False --> return str like ["name1", "name2", "..."]

    xxxx, True --> return list like ['name1', 'name2', '...']
    """
    layers_name = []
    visible_layer = "{"
    if as_str_list:
        visible_layer = "["
    layers = get_project_layers()
    for layer in layers:
        if not check_query_layer(layer):
            continue
        if is_layer_visible(layer):
            table_name = get_layer_source_table_name(layer)
            if not check_query_layer(layer):
                continue
            layers_name.append(table_name)
            visible_layer += f'"{table_name}", '
    visible_layer = visible_layer[:-2]

    if as_list:
        return layers_name

    if as_str_list:
        visible_layer += "]"
    else:
        visible_layer += "}"

    return visible_layer


def get_plugin_metadata(parameter, default_value, plugin_dir=None):
    """Get @parameter from metadata.txt file"""
    if not plugin_dir:
        plugin_dir = os.path.dirname(__file__)
        plugin_dir = plugin_dir.rstrip(f"{os.sep}lib")
    # Check if metadata file exists
    metadata_file = os.path.join(plugin_dir, "metadata.txt")
    if not os.path.exists(metadata_file):
        message = f"Metadata file not found: {metadata_file}"
        iface.messageBar().pushMessage("", message, 1, 20)
        return default_value

    value = None
    try:
        metadata = configparser.ConfigParser(comment_prefixes=["#", ";"], allow_no_value=True, strict=False)
        metadata.read(metadata_file)
        value = metadata.get("general", parameter)
    except configparser.NoOptionError:
        message = f"Parameter not found: {parameter}"
        iface.messageBar().pushMessage("", message, 1, 20)
        value = default_value
    return value


def get_plugin_version():
    """Get plugin version from metadata.txt file"""
    # Check if metadata file exists
    plugin_version = None
    message = None
    metadata_file = os.path.join(lib_vars.plugin_dir, "metadata.txt")
    if not os.path.exists(metadata_file):
        message = f"Metadata file not found: {metadata_file}"
        return plugin_version, message

    metadata = configparser.ConfigParser(comment_prefixes=";", allow_no_value=True, strict=False)
    metadata.read(metadata_file)
    plugin_version = metadata.get("general", "version")
    if plugin_version is None:
        message = "Plugin version not found"

    return plugin_version, message


def get_major_version(plugin_dir=None, default_version="3.5"):
    """Return major.minor folder name (e.g. 4.10) from metadata.txt version."""
    version = get_plugin_metadata("version", default_version, plugin_dir)
    parts = version.split(".")
    if len(parts) >= 2:
        return f"{parts[0]}.{parts[1]}"
    return parts[0] if parts else default_version


def get_build_version(plugin_dir, default_version="35001"):
    """Get plugin build version from metadata.txt file"""
    build_version = get_plugin_metadata("version", default_version, plugin_dir).replace(".", "")
    return build_version


def find_plugin_path(folder_name: str) -> Optional[str]:
    """Find the full path of a plugin folder by checking possible paths.

    :param folder_name: The folder name of the plugin.
    :return: The full path to the plugin folder if found, None otherwise.
    """
    for path in plugin_paths:
        potential_path = os.path.join(path, folder_name)
        if os.path.exists(potential_path):
            return potential_path
    return None


def is_plugin_available(plugin_name: str) -> bool:
    """Check if a QGIS plugin is available by matching its metadata name.

    :param plugin_name: The 'name' parameter from the plugin's metadata.
    :return: True if the plugin is available, False otherwise.
    """
    for folder_name in available_plugins:
        plugin_dir = find_plugin_path(folder_name)
        if plugin_dir:
            metadata_name = get_plugin_metadata("name", default_value=None, plugin_dir=plugin_dir)
            if metadata_name == plugin_name:
                return True
    return False


def is_plugin_active(plugin_name: str) -> bool:
    """Check if a QGIS plugin is active by matching its metadata name.

    :param plugin_name: The 'name' parameter from the plugin's metadata.
    :return: True if the plugin is active, False otherwise.
    """
    for folder_name in active_plugins:
        plugin_dir = find_plugin_path(folder_name)
        if plugin_dir:
            metadata_name = get_plugin_metadata("name", default_value=None, plugin_dir=plugin_dir)
            if metadata_name == plugin_name:
                return True
    return False


def get_plugin_folder(plugin_name: str) -> Optional[str]:
    """Get the full path of a plugin folder by matching its metadata name.

    :param plugin_name: The 'name' parameter from the plugin's metadata.
    :return: The folder name of the plugin if found, None otherwise.
    """
    for folder_name in available_plugins:
        plugin_dir = find_plugin_path(folder_name)
        if plugin_dir:
            metadata_name = get_plugin_metadata("name", default_value=None, plugin_dir=plugin_dir)
            if metadata_name == plugin_name:
                return folder_name
    return None


def enable_python_console():
    """Enable Python console and Log Messages panel"""
    # Manage Python console
    python_console = iface.mainWindow().findChild(QDockWidget, "PythonConsole")
    if python_console:
        python_console.setVisible(True)
    else:
        console.show_console()

    # Manage Log Messages panel
    message_log = iface.mainWindow().findChild(QDockWidget, "MessageLog")
    if message_log:
        message_log.setVisible(True)


def get_project_variable(var_name):
    """Get project variable"""
    value = None
    try:
        value = QgsExpressionContextUtils.projectScope(QgsProject.instance()).variable(var_name)
        if value == NULL:
            value = None
    except Exception:
        pass
    return value


def set_project_variable(var_name, value):
    """Set project variable"""
    try:
        custom_vars = QgsProject.instance().customVariables()
        custom_vars[var_name] = value
        QgsProject.instance().setCustomVariables(custom_vars)
    except Exception:
        pass
    return


def get_project_layers():
    """Return layers in the same order as listed in TOC"""
    layers = [layer.layer() for layer in QgsProject.instance().layerTreeRoot().findLayers()]

    return layers


def find_toc_group(root, group, case_sensitive=False):
    """Find a group of layers in the ToC"""
    for grp in root.findGroups():
        group1 = grp.name()
        group2 = group
        if not case_sensitive:
            group1 = group1.lower()
            group2 = group2.lower()

        if group1 == group2:
            return grp

    return None


def get_layer_source(layer):
    """Get database connection paramaters of @layer"""
    # Initialize variables
    layer_source = {
        "db": None,
        "schema": None,
        "table": None,
        "service": None,
        "host": None,
        "port": None,
        "user": None,
        "password": None,
        "sslmode": None,
    }

    if layer is None:
        return layer_source

    if layer.providerType() != "postgres":
        return layer_source

    # Get dbname, host, port, user and password
    uri = layer.dataProvider().dataSourceUri()

    # split with quoted substrings preservation
    splt = shlex.split(uri)

    list_uri = []
    for v in splt:
        if "=" in v:
            elem_uri = tuple(v.split("="))
            if len(elem_uri) == 2:
                list_uri.append(elem_uri)

    splt_dct = _manage_layer_source_dict(list_uri)

    for key in layer_source.keys():
        layer_source[key] = splt_dct.get(key)

    return layer_source


def get_layer_source_table_name(layer):
    """Get table or view name of selected layer"""
    if layer is None:
        return None

    provider = layer.providerType()
    if provider in ["postgres", "gdal"]:
        uri = layer.dataProvider().dataSourceUri().lower()
        pos_ini = uri.find("table=")
        total = len(uri)
        pos_end_schema = uri.rfind(".")
        pos_fi = uri.find('" ')
        if uri.find("pg:") != -1:
            uri_table = uri[pos_ini + 6 : total]
        elif pos_ini != -1 and pos_fi != -1:
            uri_table = uri[pos_end_schema + 2 : pos_fi]
        else:
            uri_table = uri[pos_end_schema + 2 : total - 1]
    elif provider == "ogr" and layer.source().split("|")[0].endswith(".gpkg"):
        uri_table = ""
        parts = layer.source().split("|")  # Split by the pipe character '|'
        for part in parts:
            if part.startswith("layername="):
                uri_table = part.split("=")[1]
                break
    else:
        uri_table = None

    return uri_table


def get_layer_schema(layer):
    """Get table or view schema_name of selected layer"""
    if layer is None:
        return None
    if layer.providerType() != "postgres":
        return None

    table_schema = None
    uri = layer.dataProvider().dataSourceUri().lower()

    pos_ini = uri.find("table=")
    pos_end_schema = uri.rfind(".")
    pos_fi = uri.find('" ')
    if pos_ini != -1 and pos_fi != -1:
        table_schema = uri[pos_ini + 7 : pos_end_schema - 1]

    return table_schema


def get_primary_key(layer=None):
    """Get primary key of selected layer"""
    if layer is None:
        layer = iface.activeLayer()
    if layer is None:
        return None

    # Check if it's a PostgreSQL layer
    if layer.providerType() != "postgres":
        return None

    try:
        uri = layer.dataProvider().dataSourceUri()

        # Parse URI and find key parameter
        for part in shlex.split(uri):
            if part.startswith("key="):
                return part.split("=", 1)[1]

        return None

    except Exception:
        return None


def get_layer_by_tablename(tablename, show_warning_=False, log_info=False, schema_name=None):
    """Iterate over all layers and get the one with selected @tablename"""
    # Check if we have any layer loaded
    layers = get_project_layers()
    if len(layers) == 0:
        return None

    # Iterate over all layers
    if schema_name is None:
        if "main_schema" in lib_vars.project_vars:
            schema_name = lib_vars.project_vars["main_schema"]
        else:
            msg = "Key not found"
            tools_log.log_warning(msg, parameter="main_schema")

    layer = find_matching_layer(layers, tablename, schema_name)

    if show_warning_:
        if layer is None:
            show_warning("Layer not found", parameter=tablename)
        elif not layer.isValid():
            show_warning("Layer is broken", parameter=tablename)

    if log_info:
        if layer is None:
            msg = "Layer not found"
            tools_log.log_info(msg, parameter=tablename)
        elif not layer.isValid():
            msg = "Layer is broken"

    return layer


def get_layer(
    custom_properties=None, tablename=None, layername=None, schema_name=None, show_warning_=False, log_info=False
):
    """
    Iterate over all layers and get the one with selected @custom_properties, @tablename or @layername
    :param custom_properties: Dictionary of custom properties to match (dict)
    :param tablename: Table name to match (string)
    :param layername: Layer name to match (string)
    :param schema_name: Schema name to match (string)
    :param show_warning_: Show warning if layer is not found (bool)
    :param log_info: Log info if layer is not found (bool)
    """
    # Check if we have any layer loaded
    layers = get_project_layers()
    if len(layers) == 0:
        return None

    layer = None

    layer = _manage_custom_properties(layers, custom_properties)

    if layer is None and tablename is not None:
        layer = get_layer_by_tablename(
            tablename, show_warning_=show_warning_, log_info=log_info, schema_name=schema_name
        )

    if layer is None and layername is not None:
        layer = get_layer_by_layername(layername, log_info=log_info)

    if show_warning_:
        if layer is None:
            show_warning("Layer not found", parameter=tablename)
        elif not layer.isValid():
            show_warning("Layer is broken", parameter=tablename)

    if log_info:
        if layer is None:
            msg = "Layer not found"
            tools_log.log_info(msg, parameter=tablename)
        elif not layer.isValid():
            msg = "Layer is broken"

    return layer


def find_matching_layer(layers, tablename, schema_name):
    for cur_layer in layers:
        uri_table = get_layer_source_table_name(cur_layer)
        table_schema = get_layer_schema(cur_layer)
        if uri_table is not None and uri_table == tablename and schema_name in ("", None, table_schema):
            return cur_layer
    return None


def add_layer_to_toc(
    layer, group=None, sub_group=None, create_groups=False, sub_sub_group=None, custom_properties=None
):
    """If the function receives a group name, check if it exists or not and put the layer in this group
    :param layer: (QgsVectorLayer)
    :param group: Name of the group that will be created in the toc (string)
    :param sub_group: Name of the sub-group that will be created in the toc (string)
    :param create_groups: Create groups if they do not exist (boolean)
    :param sub_sub_group: Name of the sub-sub-group that will be created in the toc (string)
    :param custom_properties: Custom properties of the layer (dict)
    """
    if group is None:
        QgsProject.instance().addMapLayer(layer)
        return

    if custom_properties is not None:
        for key, value in custom_properties.items():
            layer.setCustomProperty(key, value)

    QgsProject.instance().addMapLayer(layer, False)
    root = QgsProject.instance().layerTreeRoot()
    if root is None:
        msg = "QgsLayerTree not found for project."
        tools_log.log_error(msg)
        return

    if create_groups:
        first_group, second_group, third_group = _create_group_structure(root, group, sub_group, sub_sub_group)
    else:
        first_group = find_toc_group(root, group)
        second_group = find_toc_group(first_group, sub_group) if first_group and sub_group else None
        third_group = find_toc_group(second_group, sub_sub_group) if second_group and sub_sub_group else None

    _add_layer_to_group(layer, first_group, second_group, third_group)


def hide_node_from_treeview(node, root, ltv):
    # Hide the node from the tree view
    index = get_node_index(node, ltv)
    ltv.setRowHidden(index.row(), index.parent(), True)
    node.setCustomProperty("nodeHidden", "true")
    ltv.setCurrentIndex(get_node_index(root, ltv))


def get_node_index(node, ltv):
    if Qgis.QGIS_VERSION_INT >= 31800:
        return ltv.node2index(node)
    else:
        # Older QGIS versions
        return ltv.layerTreeModel().node2index(node)


def restore_hidden_nodes():
    root = QgsProject.instance().layerTreeRoot()
    ltv = iface.layerTreeView()

    for node in root.children():
        if node.customProperty("nodeHidden", "") == "true":
            hide_node_from_treeview(node, root, ltv)


def add_layer_from_query(
    query: str,
    layer_name: str = "QueryLayer",
    key_column: Optional[str] = None,
    geom_column: Optional[str] = "the_geom",
    group: Optional[str] = None,
):
    """Creates a QVectorLayer and adds it to the project"""
    # Define your PostgreSQL connection parameters
    uri, _ = tools_db.get_uri()

    # Modify the query to include a unique identifier if key_column is not provided
    if key_column is None:
        querytext = f"(SELECT row_number() over () AS _uid_, * FROM ({query}) AS query_table)"
        key_column = "_uid_"
    else:
        querytext = f"({query})"

    # Set the SQL query and the geometry column (initially without geom_column)
    uri.setDataSource("", f"({query})", "", "", key_column)

    # Create a provisional layer
    provisional_layer = QgsVectorLayer(uri.uri(False), f"{layer_name}", "postgres")

    # Check if the provisional layer is valid
    if not provisional_layer.isValid():
        msg = "Layer failed to load!"
        tools_log.log_error(msg, parameter=querytext)
        return

    # Check if the geometry column exists in the provisional layer
    fields = provisional_layer.fields()
    if geom_column in fields.names():
        # Update uri to include the geometry column
        uri.setDataSource("", querytext, geom_column, "", key_column)

    # Create the layer
    layer = QgsVectorLayer(uri.uri(False), f"{layer_name}", "postgres")

    # Check if the layer is valid
    if not layer.isValid():
        msg = "Layer failed to load!"
        tools_log.log_error(msg, parameter=querytext)
        return

    # Add the layer to the project
    add_layer_to_toc(layer, group)


def manage_snapping_layer(layername, snapping_type=0, tolerance=15.0):
    """Manage snapping of @layername"""
    layer = get_layer_by_tablename(layername)
    if not layer:
        return
    if snapping_type == 0:
        snapping_type = QgsPointLocator.Type.Vertex
    elif snapping_type == 1:
        snapping_type = QgsPointLocator.Type.Edge
    elif snapping_type == 2:
        snapping_type = QgsPointLocator.Type.All

    QgsSnappingUtils.LayerConfig(layer, snapping_type, tolerance, QgsTolerance.UnitType.Pixels)


def set_project_snapping_settings(enabled=None, mode=None, tolerance=None, units=None, snapping_types=None):
    """Configures project-wide snapping settings.

    This function operates in two modes:
    1.  **Creation Mode (no arguments):** When called with no arguments, it applies a
        comprehensive set of default snapping settings for a new project.
    2.  **Update Mode (arguments provided):** When any argument is provided, it
        modifies only the specified settings, preserving existing ones. This is
        used when loading an existing project.
    """
    project = QgsProject.instance()
    cfg = project.snappingConfig()

    is_create_project_mode = all(arg is None for arg in (enabled, mode, tolerance, units, snapping_types))
    is_new_api = Qgis.QGIS_VERSION_INT >= 32200

    if is_create_project_mode:
        # Apply a full default configuration for new projects.
        cfg.setEnabled(True)
        cfg.setMode(QgsSnappingConfig.SnappingMode.AllLayers)
        cfg.setTolerance(15.0)
        cfg.setUnits(QgsTolerance.UnitType.Pixels)
        if is_new_api:
            # For QGIS 3.22 and later
            types = Qgis.SnappingType.Vertex | Qgis.SnappingType.Segment
            cfg.setTypeFlag(Qgis.SnappingTypes(types))
        else:
            # For older QGIS versions
            cfg.setTypeFlag(QgsSnappingConfig.SnappingTypes.VertexFlag | QgsSnappingConfig.SnappingTypes.SegmentFlag)
    else:
        # Apply only the settings that were explicitly passed to the function.
        if enabled is not None:
            cfg.setEnabled(enabled)
        if mode is not None:
            cfg.setMode(mode)
        if tolerance is not None:
            cfg.setTolerance(tolerance)
        if units is not None:
            cfg.setUnits(units)
        if snapping_types is not None:
            if is_new_api:
                cfg.setTypeFlag(Qgis.SnappingTypes(snapping_types))
            else:
                cfg.setTypeFlag(snapping_types)

    # Commit the configuration to the project and map canvas.
    project.setSnappingConfig(cfg)
    mc = iface.mapCanvas()
    if mc:
        mc.snappingUtils().setConfig(cfg)

    return True


def select_features_by_ids(feature_type, expr, layers=None):
    """Select features of layers of group @feature_type applying @expr"""
    if layers is None:
        return

    if feature_type not in layers:
        return

    # Build a list of feature id's and select them
    for layer in layers[feature_type]:
        if expr is None:
            layer.removeSelection()
        else:
            it = layer.getFeatures(QgsFeatureRequest(expr))
            id_list = [i.id() for i in it]
            if len(id_list) > 0:
                layer.selectByIds(id_list)
            else:
                layer.removeSelection()


def get_points_from_geometry(layer, feature):
    """Get the start point and end point of the feature"""
    list_points = None

    geom = feature.geometry()

    try:
        if layer.geometryType() == 0:
            points = geom.asPoint()
            list_points = f'"x1":{points.x()}, "y1":{points.y()}'
        elif layer.geometryType() in (1, 2):
            points = geom.asPolyline()
            init_point = points[0]
            last_point = points[-1]
            list_points = f'"x1":{init_point.x()}, "y1":{init_point.y()}'
            list_points += f', "x2":{last_point.x()}, "y2":{last_point.y()}'
        else:
            msg = "NO FEATURE TYPE DEFINED"
            tools_log.log_info(msg)
    except Exception:
        pass

    return list_points


def disconnect_snapping(action_pan=True, emit_point=None, vertex_marker=None):
    """Select 'Pan' as current map tool and disconnect snapping"""
    try:
        iface.mapCanvas().xyCoordinates.disconnect()
    except TypeError as e:
        msg = "{0} --> {1}"
        msg_params = (
            type(e).__name__,
            e,
        )
        tools_log.log_info(msg, msg_params=msg_params)

    if emit_point is not None:
        try:
            emit_point.canvasClicked.disconnect()
        except TypeError as e:
            msg = "{0} --> {1}"
            msg_params = (
                type(e).__name__,
                e,
            )
            tools_log.log_info(msg, msg_params=msg_params)

    if vertex_marker is not None:
        try:
            vertex_marker.hide()
        except AttributeError as e:
            msg = "{0} --> {1}"
            msg_params = (
                type(e).__name__,
                e,
            )
            tools_log.log_info(msg, msg_params=msg_params)

    if action_pan:
        iface.actionPan().trigger()


def refresh_map_canvas(_restore_cursor=False):
    """Refresh all layers present in map canvas"""
    iface.mapCanvas().refreshAllLayers()
    for layer_refresh in iface.mapCanvas().layers():
        layer_refresh.triggerRepaint()

    if _restore_cursor:
        restore_cursor()


def force_refresh_map_canvas():
    """Refresh all layers & map canvas"""
    refresh_map_canvas()  # First refresh all the layers
    iface.mapCanvas().refresh()  # Then refresh the map view itself


def set_cursor_wait():
    """Change cursor to 'WaitCursor'"""
    while get_override_cursor() is not None:
        restore_cursor()
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)


def get_override_cursor():
    return QApplication.overrideCursor()


def restore_cursor():
    """Restore to previous cursors"""
    while get_override_cursor() is not None:
        QApplication.restoreOverrideCursor()


def disconnect_signal_selection_changed():
    """Disconnect signal selectionChanged"""
    try:
        iface.mapCanvas().selectionChanged.disconnect()
    except Exception:
        pass
    finally:
        iface.actionPan().trigger()


def select_features_by_expr(layer, expr):
    """Select features of @layer applying @expr"""
    if not layer:
        return

    if expr is None:
        layer.removeSelection()
    else:
        it = layer.getFeatures(QgsFeatureRequest(expr))
        # Build a list of feature id's from the previous result and select them
        id_list = [i.id() for i in it]
        if len(id_list) > 0:
            layer.selectByIds(id_list)
        else:
            layer.removeSelection()


def get_max_rectangle_from_coords(list_coord):
    """Returns the minimum rectangle(x1, y1, x2, y2) of a series of coordinates
    :param list_coord: list of coords in format ['x1 y1', 'x2 y2',....,'x99 y99']
    """
    coords = list_coord.group(1)
    polygon = coords.split(",")
    x_vals = []
    y_vals = []
    for p in polygon:
        x, y = re.findall(r"-?\d+(?:\.\d+)?", p)
        x_vals.append(float(x))
        y_vals.append(float(y))
    min_x = min(x_vals)
    max_x = max(x_vals)
    min_y = min(y_vals)
    max_y = max(y_vals)

    return max_x, max_y, min_x, min_y


def zoom_to_rectangle(x1, y1, x2, y2, margin=5, change_crs=True):
    """Generate an extension on the canvas according to the received coordinates"""
    rect = QgsRectangle(float(x1) + margin, float(y1) + margin, float(x2) - margin, float(y2) - margin)
    if str(lib_vars.data_epsg) == "2052" and str(lib_vars.project_epsg) == "102566" and change_crs:
        rect = QgsRectangle(
            float(float(x1) + margin) * -1,
            (float(y1) + margin) * -1,
            (float(x2) - margin) * -1,
            (float(y2) - margin) * -1,
        )
    elif str(lib_vars.data_epsg) != str(lib_vars.project_epsg) and change_crs:
        data_epsg = QgsCoordinateReferenceSystem(str(lib_vars.data_epsg))
        project_epsg = QgsCoordinateReferenceSystem(str(lib_vars.project_epsg))
        tform = QgsCoordinateTransform(data_epsg, project_epsg, QgsProject.instance())

        rect = tform.transform(rect)

    iface.mapCanvas().setExtent(rect)
    iface.mapCanvas().refresh()


def get_composers_list():
    """Returns the list of project composer"""
    layour_manager = QgsProject.instance().layoutManager().layouts()
    active_composers = [layout for layout in layour_manager]
    return active_composers


def get_composer_index(name):
    """Returns the index of the selected composer name"""
    index = 0
    composers = get_composers_list()
    for comp_view in composers:
        composer_name = comp_view.name()
        if composer_name == name:
            break
        index += 1

    return index


def get_geometry_vertex(list_coord=None):
    """Return list of QgsPoints taken from geometry
    :param list_coord: list of coors in format ['x1 y1', 'x2 y2',....,'x99 y99']
    """
    coords = list_coord.group(1)
    polygon = coords.split(",")
    points = []

    for i in range(0, len(polygon)):
        x, y = polygon[i].split(" ")
        point = QgsPointXY(float(x), float(y))
        points.append(point)

    return points


def reset_rubber_band(rubber_band):
    """Reset QgsRubberBand"""
    rubber_band.reset()


def restore_user_layer(layer_name, user_current_layer=None):
    """Set active layer, preferably @user_current_layer else @layer_name.
    If user_current_layer was removed from project (C++ object deleted), falls back to layer_name."""
    try:
        if user_current_layer:
            iface.setActiveLayer(user_current_layer)
            return
    except RuntimeError:
        pass  # wrapped C/C++ object of type QgsVectorLayer has been deleted
    layer = get_layer_by_tablename(layer_name)
    if layer:
        iface.setActiveLayer(layer)


def set_layer_categoryze(layer, cat_field, size, color_values, unique_values=None, opacity=255):
    """:param layer: QgsVectorLayer to be categorized (QgsVectorLayer)
    :param cat_field: Field to categorize (String)
    :param size: Size of feature (int)
    """
    # get unique values
    fields = layer.fields()
    fni = fields.indexOf(cat_field)
    if not unique_values:
        unique_values = layer.dataProvider().uniqueValues(fni)
    categories = []

    for unique_value in unique_values:
        # initialize the default symbol for this geometry type
        symbol = QgsSymbol.defaultSymbol(layer.geometryType())
        if type(symbol) in (QgsLineSymbol,):
            symbol.setWidth(size)
        elif type(symbol) in (QgsFillSymbol,):
            pass
        else:
            symbol.setSize(size)

        # configure a symbol layer
        legend_id = None
        try:
            if "color" in color_values.get(str(unique_value)):
                color = color_values.get(str(unique_value)).get("color")
            else:
                color = color_values.get(str(unique_value))
            symbol.setColor(color)
            legend_id = color_values.get(str(unique_value)).get("legend_id")
        except Exception:
            color = QColor(randrange(0, 256), randrange(0, 256), randrange(0, 256), opacity)
            symbol.setColor(color)

        # create renderer object
        if legend_id:
            category = QgsRendererCategory(unique_value, symbol, str(legend_id))
        else:
            category = QgsRendererCategory(unique_value, symbol, str(unique_value))
        # entry for the list of category items
        categories.append(category)

    # create renderer object
    renderer = QgsCategorizedSymbolRenderer(cat_field, categories)

    # assign the created renderer to the layer
    if renderer is not None:
        layer.setRenderer(renderer)

    layer.triggerRepaint()
    iface.layerTreeView().refreshLayerSymbology(layer.id())


def remove_layer_from_toc(layer_name, group_name, sub_group=None):
    """Remove layer from toc if exist
    :param layer_name: Name's layer (String)
    :param group_name: Name's group (String)
    """
    warn("remove_layer_from_toc is deprecated. Use remove_layer instead.", stacklevel=2)
    remove_layer(layername=layer_name, group_name=group_name, sub_group=sub_group)


def remove_layer(custom_properties=None, tablename=None, layername=None, group_name=None, sub_group=None):
    """
    Remove layer from toc if exist
    :param custom_properties: Custom properties of the layer (dict)
    :param tablename: Tablename of the layer (String)
    :param layername: Layername of the layer (String)
    :param group_name: Name's group (String)
    :param sub_group: Name's sub group (String)
    """
    layer = get_layer(custom_properties=custom_properties, tablename=tablename, layername=layername)
    if layer is not None:
        # Remove layer
        QgsProject.instance().removeMapLayer(layer)

        # Remove group if is void
        if group_name is not None:
            root = QgsProject.instance().layerTreeRoot()
            first_group = root.findGroup(group_name)
            if first_group:
                if sub_group:
                    second_group = first_group.findGroup(sub_group)
                    if second_group:
                        layers = second_group.findLayers()
                        if not layers:
                            root.removeChildNode(second_group)
                layers = first_group.findLayers()
                if not layers:
                    root.removeChildNode(first_group)
        remove_layer(
            custom_properties=custom_properties,
            tablename=tablename,
            layername=layername,
            group_name=group_name,
            sub_group=sub_group,
        )

    # Force a map refresh
    force_refresh_map_canvas()


def clean_layer_group_from_toc(group_name):
    """Remove all "broken" layers from a group
    :param group_name: Group's name (String)
    """
    root = QgsProject.instance().layerTreeRoot()
    group = root.findGroup(group_name)
    if group:
        layers = group.findLayers()
        for layer in layers:
            if layer.layer() is None:
                group.removeChildNode(layer)
        # Remove group if is void
        layers = group.findLayers()
        if not layers:
            root.removeChildNode(group)


def get_plugin_settings_value(section, key, default_value=""):
    """Get @value of QSettings located in @key"""
    key = section + "/" + key
    value = QSettings().value(key, default_value)
    return value


def get_layer_by_layername(layername, log_info=False):
    """Get layer with selected @layername (the one specified in the TOC)"""
    layer = QgsProject.instance().mapLayersByName(layername)
    if layer:
        layer = layer[0]
    elif not layer and log_info:
        layer = None
        msg = "Layer not found"
        tools_log.log_info(msg, parameter=layername)

    return layer


def is_layer_visible(layer):
    """Return is @layer is visible or not"""
    visible = False
    if layer:
        visible = QgsProject.instance().layerTreeRoot().findLayer(layer.id()).itemVisibilityChecked()

    return visible


def set_layer_visible(layer, recursive=True, visible=True):
    """Set layer visible
    :param layer: layer to set visible (QgsVectorLayer)
    :param recursive: Whether it affects just the layer or all of its parents (bool)
    :param visible: Whether the layer will be visible or not (bool)
    """
    try:
        if layer:
            if recursive:
                QgsProject.instance().layerTreeRoot().findLayer(layer.id()).setItemVisibilityCheckedParentRecursive(
                    visible
                )  # noqa: E501
            else:
                QgsProject.instance().layerTreeRoot().findLayer(layer.id()).setItemVisibilityChecked(visible)
    except RuntimeError:
        pass


def set_layer_index(layer_name):
    """Force reload dataProvider of layer"""
    layer = get_layer_by_tablename(layer_name)
    if layer:
        layer.dataProvider().reloadData()
        layer.triggerRepaint()


def load_qml(layer, qml_path):
    """Apply QML style located in @qml_path in @layer
    :param layer: layer to set qml (QgsVectorLayer)
    :param qml_path: desired path (String)
    :return: True or False (bool)
    """
    if layer is None:
        return False

    if not os.path.exists(qml_path):
        msg = "File not found"
        tools_log.log_warning(msg, parameter=qml_path)
        return False

    if not qml_path.endswith(".qml"):
        msg = "File extension not valid"
        tools_log.log_warning(msg, parameter=qml_path)
        return False

    layer.loadNamedStyle(qml_path)
    layer.triggerRepaint()

    return True


def set_margin(layer, margin):
    """Generates a margin around the layer so that it is fully visible on the canvas"""
    if layer.extent().isNull():
        return

    extent = QgsRectangle()
    extent.setNull()
    extent.combineExtentWith(layer.extent())
    xmin = extent.xMinimum() - margin
    ymin = extent.yMinimum() - margin
    xmax = extent.xMaximum() + margin
    ymax = extent.yMaximum() + margin
    extent.set(xmin, ymin, xmax, ymax)
    iface.mapCanvas().setExtent(extent)
    iface.mapCanvas().refresh()


def create_qml(layer, style):
    """Generates a qml file through a json of styles (@style) and puts it in the received @layer"""
    config_folder = f"{lib_vars.user_folder_dir}{os.sep}core{os.sep}temp"
    if not os.path.exists(config_folder):
        os.makedirs(config_folder)
    path_temp_file = f"{config_folder}{os.sep}temporal_layer.qml"
    file = open(path_temp_file, "w")
    file.write(style)
    file.close()
    del file
    load_qml(layer, path_temp_file)


def draw_point(point, rubber_band=None, color=None, width=3, duration_time=None, reset_rb=True):
    """Draw a point on the canvas
    :param point: (QgsPointXY)
    :param rubber_band: (QgsRubberBand)
    :param color: Color of the point (QColor)
    :param width: width of the point (int)
    :param duration_time: Time in milliseconds that the point will be visible. Ex: 3000 for 3 seconds (int)
    """
    if color is None:
        color = QColor(255, 0, 0, 100)
    if reset_rb:
        rubber_band.reset(QgsWkbTypes.GeometryType.PointGeometry)
    rubber_band.setIconSize(10)
    rubber_band.setColor(color)
    rubber_band.setWidth(width)
    point = QgsGeometry.fromPointXY(point)
    if rubber_band.size() == 0:
        rubber_band.setToGeometry(point, None)
    else:
        rubber_band.addGeometry(point, None)

    # wait to simulate a flashing effect
    if duration_time is not None:
        QTimer.singleShot(duration_time, rubber_band.reset)


def draw_polyline(points, rubber_band, color=None, width=5, duration_time=None, reset_rb=True):
    """Draw 'line' over canvas following list of points
    :param points: list of QgsPointXY (points[QgsPointXY_1, QgsPointXY_2, ..., QgsPointXY_x])
    :param rubber_band: (QgsRubberBand)
    :param color: Color of the point (QColor)
    :param width: width of the point (int)
    :param duration_time: Time in milliseconds that the point will be visible. Ex: 3000 for 3 seconds (int)
    """
    if color is None:
        color = QColor(255, 0, 0, 100)
    if reset_rb:
        rubber_band.reset(QgsWkbTypes.GeometryType.LineGeometry)
    rubber_band.setIconSize(20)
    if type(points) is str:
        polyline = QgsGeometry.fromWkt(points)
    else:
        polyline = QgsGeometry.fromPolylineXY(points)
    if rubber_band.size() == 0:
        rubber_band.setToGeometry(polyline, None)
    else:
        rubber_band.addGeometry(polyline, None)
    rubber_band.setColor(color)
    rubber_band.setWidth(width)
    rubber_band.show()

    # wait to simulate a flashing effect
    if duration_time is not None:
        QTimer.singleShot(duration_time, rubber_band.reset)


def draw_polygon(points, rubber_band, border=None, width=3, duration_time=None, reset_rb=True):
    """Draw 'polygon' over canvas following list of points
    :param duration_time: integer milliseconds ex: 3000 for 3 seconds
    """
    if border is None:
        border = QColor(255, 0, 0, 100)
    if reset_rb:
        rubber_band.reset(QgsWkbTypes.GeometryType.PolygonGeometry)
    rubber_band.setIconSize(20)
    polygon = QgsGeometry.fromPolygonXY([points])
    if rubber_band.size() == 0:
        rubber_band.setToGeometry(polygon, None)
    else:
        rubber_band.addGeometry(polygon, None)
    rubber_band.setColor(border)
    rubber_band.setFillColor(QColor(0, 0, 0, 0))
    rubber_band.setWidth(width)
    rubber_band.show()

    # wait to simulate a flashing effect
    if duration_time is not None:
        # Qtimer singleShot works with ms, we manage transformation to seconds
        QTimer.singleShot(int(duration_time) * 1000, rubber_band.reset)


def get_geometry_from_json(feature):
    """Get coordinates from GeoJson and return QGsGeometry

    functions called in:
        getattr(f"get_{feature['geometry']['type'].lower()}")(feature)
        def _get_vertex_from_point(feature)
        _get_vertex_from_linestring(feature)
        _get_vertex_from_multilinestring(feature)
        _get_vertex_from_polygon(feature)
        _get_vertex_from_multipolygon(feature)

        :param feature: feature to get geometry type and coordinates (GeoJson)
        :return: Geometry of the feature (QgsGeometry)

    """
    try:
        coordinates = getattr(sys.modules[__name__], f"_get_vertex_from_{feature['geometry']['type'].lower()}")(feature)
        type_ = feature["geometry"]["type"]
        geometry = f"{type_}{coordinates}"
        return QgsGeometry.fromWkt(geometry)
    except (AttributeError, TypeError, IndexError) as e:
        msg = "{0} --> {1}"
        msg_params = (
            type(e).__name__,
            e,
        )
        tools_log.log_info(msg, msg_params=msg_params)
        return None


def get_locale():
    locale = "en_US"
    try:
        # Get locale of QGIS application
        override = QSettings().value("locale/overrideFlag")
        if tools_os.set_boolean(override):
            locale = QSettings().value("locale/globalLocale")
        else:
            locale = QSettings().value("locale/userLocale")
    except AttributeError as e:
        locale = "en_US"
        msg = "{0} --> {1}"
        msg_params = (
            type(e).__name__,
            e,
        )
        tools_log.log_info(msg, msg_params=msg_params)
    if locale in (None, ""):
        locale = "en_US"
    return locale


def get_locale_schema():
    """Get locale of the schema"""
    locale = "en_US"
    try:
        current_schema = lib_vars.schema_name
        if current_schema:
            # Remove schema quotes for check_table function
            current_schema_no_quotes = current_schema.replace('"', "")
            if tools_db.check_table(tablename="sys_version", schemaname=current_schema_no_quotes):
                table = f"{current_schema}.sys_version"
                sql = f"SELECT language FROM {table};"
                row = tools_db.get_row(sql, log_info=False)
                if row and row[0]:
                    locale = row[0]
            else:
                # If table does not exist, try to get global locale
                locale = get_locale()
        else:
            # If schema is not defined, try to get global locale
            locale = get_locale()
    except Exception as e:
        msg = "Error getting locale from schema: {0}"
        msg_params = (e,)
        tools_log.log_info(msg, msg_params=msg_params)

    return locale


def _locale_folder_from_lang_id(lang_id: str | None) -> str | None:
    """Map multilang.cat_language / cat_user_lang id (ca_es) to QGIS locale (ca_ES)."""
    text = str(lang_id or "").strip().replace("-", "_")
    if not text or len(text) != 5:
        return None
    parts = text.split("_", 1)
    if len(parts) == 2 and parts[0] and parts[1]:
        return f"{parts[0].lower()}_{parts[1].upper()}"
    return text


def get_ui_language_locale():
    """Return UI language for Python .qm files from multilang user preference when set."""
    locale = None
    try:
        from . import tools_db

        schema_name = lib_vars.schema_name
        if schema_name:
            schema_name = schema_name.replace('"', "").strip()
        if schema_name and tools_db.check_schema("multilang"):
            schema_esc = schema_name.replace("'", "''")
            row = tools_db.get_row(
                "SELECT lang FROM multilang.cat_user_lang "
                f"WHERE schema_name = '{schema_esc}' AND username = current_user",
                log_info=False,
            )
            if row and row[0]:
                locale = _locale_folder_from_lang_id(row[0])
    except Exception as e:
        msg = "Error getting UI language locale: {0}"
        tools_log.log_info(msg, msg_params=(e,))

    if not locale:
        locale = get_locale_schema()
    if locale in (None, ""):
        locale = "en_US"
    return locale


def highlight_features_by_id(qtable, layer_name, field_id, rubber_band, width, selected, deselected):
    rubber_band.reset()
    for idx, index in enumerate(qtable.selectionModel().selectedRows()):
        highlight_feature_by_id(qtable, layer_name, field_id, rubber_band, width, index, add=(idx > 0))


def highlight_feature_by_id(qtable, layer_name, field_id, rubber_band, width, index, table_field=None, add=False):
    """Based on the received index and field_id, the id of the received field_id is searched within the table
    and is painted in red on the canvas
    """
    layer = get_layer_by_tablename(layer_name)
    if not layer:
        rubber_band.reset()
        return

    row = index.row()
    if not table_field:
        table_field = field_id
    column_index = tools_qt.get_col_index_by_col_name(qtable, table_field)
    _id = index.sibling(row, column_index).data()
    feature = tools_qt.get_feature_by_id(layer, _id, field_id)
    try:
        geometry = feature.geometry()
        if add:
            rubber_band.addGeometry(geometry, None)
        else:
            rubber_band.reset()
            rubber_band.setToGeometry(geometry, None)
        rubber_band.setColor(QColor(255, 0, 0, 100))
        rubber_band.setWidth(width)
        rubber_band.show()
    except AttributeError:
        pass


def zoom_to_layer(layer):
    """Zooms to a given layer
    :param layer:
    :return:
    """
    if not layer:
        msg = "Couldn't find layer to zoom to"
        show_warning(msg)
        return

    extent = layer.extent()

    # Transform extent from layer CRS to canvas CRS if needed
    if layer.crs() != iface.mapCanvas().mapSettings().destinationCrs():
        try:
            transform = QgsCoordinateTransform(
                layer.crs(), iface.mapCanvas().mapSettings().destinationCrs(), QgsProject.instance()
            )
            extent = transform.transformBoundingBox(extent)
        except Exception as e:
            msg = f"Failed to transform coordinates for layer '{layer.name()}': {str(e)}"
            show_warning(msg)
            return

    # Set canvas extent
    iface.mapCanvas().setExtent(extent)
    # Refresh canvas
    iface.mapCanvas().refresh()


def check_query_layer(layer):
    """Check for query layer and/or bad layer, if layer is a simple table, or an added layer from query, return False
    :param layer: Layer to be checked (QgsVectorLayer)
    :return: True/False (Boolean)
    """
    try:
        # TODO:: Find differences between PostgreSQL and query layers, and replace this if condition.
        table_uri = layer.dataProvider().dataSourceUri()
        if (
            layer is None
            or type(layer) is not QgsVectorLayer
            or "SELECT row_number() over ()" in str(table_uri)
            or layer.isSqlQuery()
        ):
            return False
        return True
    except Exception:
        return False


def get_epsg():
    epsg = iface.mapCanvas().mapSettings().destinationCrs().authid()
    epsg = epsg.split(":")
    if len(epsg) > 1:
        epsg = epsg[1]
    else:
        epsg = None
    return epsg


def get_composer(removed=None):
    """Get all composers from current QGis project"""
    composers = '"{'
    active_composers = get_composers_list()

    for composer in active_composers:
        if type(composer) is QgsPrintLayout:  # TODO: use isinstance(composer, QgsPrintLayout)
            if composer != removed and composer.name():
                cur = composer.name()
                composers += cur + ", "
    if len(composers) > 2:
        composers = composers[:-2] + '}"'
    else:
        composers += '}"'
    return composers


# region private functions


def _get_vertex_from_point(feature):
    """Manage feature geometry when is Point

    This function is called in def get_geometry_from_json(feature)
            geometry = getattr(f"get_{feature['geometry']['type'].lower()}")(feature)

        :param feature: feature to get geometry type and coordinates (GeoJson)
        :return: Coordinates of the feature (String)

    """
    return f"({feature['geometry']['coordinates'][0]} {feature['geometry']['coordinates'][1]})"


def _get_vertex_from_linestring(feature):
    """Manage feature geometry when is LineString

    This function is called in def get_geometry_from_json(feature)
          geometry = getattr(f"get_{feature['geometry']['type'].lower()}")(feature)

        :param feature: feature to get geometry type and coordinates (GeoJson)
        :return: Coordinates of the feature (String)
    """
    return _get_vertex_from_points(feature)


def _get_vertex_from_multilinestring(feature):
    """Manage feature geometry when is MultiLineString

    This function is called in def get_geometry_from_json(feature)
          geometry = getattr(f"get_{feature['geometry']['type'].lower()}")(feature)

        :param feature: feature to get geometry type and coordinates (GeoJson)
        :return: Coordinates of the feature (String)
    """
    return _get_multi_coordinates(feature)


def _get_vertex_from_polygon(feature):
    """Manage feature geometry when is Polygon

    This function is called in def get_geometry_from_json(feature)
          geometry = getattr(f"get_{feature['geometry']['type'].lower()}")(feature)

        :param feature: feature to get geometry type and coordinates (GeoJson)
        :return: Coordinates of the feature (String)
    """
    return _get_multi_coordinates(feature)


def _get_vertex_from_multipolygon(feature):
    """Manage feature geometry when is MultiPolygon

    This function is called in def get_geometry_from_json(feature)
          geometry = getattr(f"get_{feature['geometry']['type'].lower()}")(feature)

        :param feature: feature to get geometry type and coordinates (GeoJson)
        :return: Coordinates of the feature (String)
    """
    coordinates = "("
    for coords in feature["geometry"]["coordinates"]:
        coordinates += "("
        for cc in coords:
            coordinates += "("
            for c in cc:
                coordinates += f"{c[0]} {c[1]}, "
            coordinates = coordinates[:-2] + "), "
        coordinates = coordinates[:-2] + "), "
    coordinates = coordinates[:-2] + ")"
    return coordinates


def _get_vertex_from_points(feature):
    """Get coordinates of the received feature, to be a point
    :param feature: Json with the information of the received feature (GeoJson)
    :return: Coordinates of the feature received (String)
    """
    coordinates = "("
    for coords in feature["geometry"]["coordinates"]:
        coordinates += f"{coords[0]} {coords[1]}, "
    coordinates = coordinates[:-2] + ")"
    return coordinates


def _get_multi_coordinates(feature):
    """Get coordinates of the received feature, can be a line
    :param feature: Json with the information of the received feature (GeoJson)
    :return: Coordinates of the feature received (String)
    """
    coordinates = "("
    for coords in feature["geometry"]["coordinates"]:
        coordinates += "("
        for c in coords:
            coordinates += f"{c[0]} {c[1]}, "
        coordinates = coordinates[:-2] + "), "
    coordinates = coordinates[:-2] + ")"
    return coordinates


def create_point(canvas, iface, event):
    x = event.pos().x()
    y = event.pos().y()
    try:
        point = QgsMapToPixel.toMapCoordinates(canvas.getCoordinateTransform(), x, y)
    except (TypeError, KeyError):
        iface.actionPan().trigger()
        return False

    return point


def _create_group_structure(root, group, sub_group, sub_sub_group):
    """Create the group structure if it doesn't exist"""
    first_group = find_toc_group(root, group)
    if not first_group:
        first_group = root.insertGroup(0, group)
    if first_group is None:
        msg = "Group '{0}' not found in layer tree."
        msg_params = (group,)
        tools_log.log_error(msg, msg_params=msg_params)
        return None, None, None

    second_group = None
    third_group = None
    if sub_group:
        second_group = find_toc_group(first_group, sub_group)
        if not second_group:
            second_group = first_group.insertGroup(0, sub_group)
            if second_group is None:
                msg = "Couldn't add group."
                tools_log.log_error(msg)
                return first_group, None, None
        if sub_sub_group:
            third_group = find_toc_group(second_group, sub_sub_group)
            if not third_group:
                third_group = second_group.insertGroup(0, sub_sub_group)

    return first_group, second_group, third_group


def _add_layer_to_group(layer, first_group, second_group, third_group):
    """Add layer to the appropriate group level"""
    if third_group is not None:
        third_group.insertLayer(0, layer)
    elif second_group is not None:
        second_group.insertLayer(0, layer)
    elif first_group is not None:
        first_group.insertLayer(0, layer)
    else:
        root = QgsProject.instance().layerTreeRoot()
        my_group = root.findGroup("GW Layers")
        if my_group is None:
            my_group = root.insertGroup(0, "GW Layers")
        my_group.insertLayer(0, layer)
    iface.setActiveLayer(layer)


def _manage_layer_source_dict(list_uri: list[tuple[str, str]]) -> dict[str, str]:
    splt_dct = dict(list_uri)

    if "service" in splt_dct:
        splt_dct["service"] = splt_dct["service"]
    if "dbname" in splt_dct:
        splt_dct["db"] = splt_dct["dbname"]
    if "table" in splt_dct:
        splt_dict_table = splt_dct["table"].split(".")
        if len(splt_dict_table) == 2:
            splt_dct["schema"], splt_dct["table"] = splt_dict_table

    return splt_dct


def _manage_custom_properties(
    layers: list[QgsMapLayer], custom_properties: Optional[dict[str, str]]
) -> QgsMapLayer | None:
    """Manage custom properties of the layer
    :param layers: List of layers (list)
    :param custom_properties: Custom properties of the layer (dict)
    :return: Layer (QgsMapLayer)
    """
    layer = None
    if custom_properties is not None:
        for current_layer in layers:
            if current_layer is None:
                continue
            if all(current_layer.customProperty(key) == value for key, value in custom_properties.items()):
                layer = current_layer
                break
    return layer


# endregion
