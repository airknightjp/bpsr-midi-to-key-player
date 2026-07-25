from pathlib import Path, PurePath

from PyInstaller.utils.hooks.qt import (
    add_qt6_dependencies,
    pyside6_library_info,
)


hiddenimports, binaries, datas = add_qt6_dependencies(__file__)

qml_root = Path(pyside6_library_info.location["QmlImportsPath"])
qml_destination = PurePath(pyside6_library_info.qt_rel_dir) / "qml"

for relative in (
    "builtins.qmltypes",
    "jsroot.qmltypes",
    "QtQml/plugins.qmltypes",
    "QtQml/qmldir",
    "QtQml/qmlplugin.dll",
    "QtQml/Models/modelsplugin.dll",
    "QtQml/Models/plugins.qmltypes",
    "QtQml/Models/qmldir",
    "QtQuick/plugins.qmltypes",
    "QtQuick/qmldir",
    "QtQuick/qtquick2plugin.dll",
):
    source = qml_root / relative
    destination = qml_destination / PurePath(relative).parent
    target = binaries if source.suffix.lower() == ".dll" else datas
    target.append((str(source), str(destination)))
