import QtQuick

Item {
    id: root
    clip: true
    property double clockMs: Date.now()
    readonly property double currentPosition: fallingNotesBridge.running
        ? fallingNotesBridge.position
          + Math.max(0, clockMs - fallingNotesBridge.positionAnchorMs)
            / 1000.0 * fallingNotesBridge.speedRatio
        : fallingNotesBridge.position
    readonly property real songHorizon: Math.max(
        0.1,
        fallingNotesBridge.speedRatio
    )
    readonly property real whiteWidth: Math.max(1, (width - 1) / 52)

    function isWhite(note) {
        var pitch = note % 12
        return pitch === 0 || pitch === 2 || pitch === 4
                || pitch === 5 || pitch === 7 || pitch === 9 || pitch === 11
    }

    function whiteIndex(note) {
        var result = 0
        for (var value = 21; value < note; ++value) {
            if (isWhite(value))
                ++result
        }
        return result
    }

    function noteWidth(note) {
        return isWhite(note) ? whiteWidth : whiteWidth * 0.62
    }

    function noteCenter(note) {
        if (isWhite(note))
            return (whiteIndex(note) + 0.5) * whiteWidth
        return whiteIndex(note) * whiteWidth
    }

    function noteLeft(note) {
        return noteCenter(note) - noteWidth(note) / 2
    }

    function impactDuration(judgment) {
        if (judgment === "PERFECT")
            return 240
        if (judgment === "GREAT")
            return 180
        return 120
    }

    function impactIntensity(judgment) {
        if (judgment === "PERFECT")
            return 1.50
        if (judgment === "GREAT")
            return 1.05
        return 0.72
    }

    function impactRayCount(judgment, released) {
        var count = judgment === "PERFECT" ? 17 : (judgment === "GREAT" ? 10 : 5)
        return released ? Math.max(1, Math.round(count * 0.5)) : count
    }

    function impactColor(judgment) {
        if (judgment === "PERFECT")
            return "#ffd84d"
        if (judgment === "GREAT")
            return "#52e5ff"
        return Qt.lighter(fallingNotesBridge.scheduledColor, 1.2)
    }

    Rectangle {
        anchors.fill: parent
        color: fallingNotesBridge.surfaceColor
    }

    Timer {
        interval: 16
        repeat: true
        running: fallingNotesBridge.animationRunning && root.visible
        onTriggered: root.clockMs = Date.now()
    }

    Repeater {
        model: fallingNotesBridge.impacts
        delegate: Item {
            id: impactDelegate
            required property var modelData
            readonly property int note: Number(modelData.note)
            readonly property string judgment: String(modelData.judgment)
            readonly property bool released: Boolean(modelData.released)
            readonly property real elapsed: root.clockMs - Number(modelData.startedAtMs)
            readonly property real progress: Math.max(
                0,
                Math.min(1, elapsed / root.impactDuration(judgment))
            )
            readonly property real intensity: root.impactIntensity(judgment)
            readonly property real keyWidthScale: root.isWhite(note) ? 1.0 : 0.62
            readonly property real effectScale: released ? 0.60 : 1.0
            readonly property int rayCount: root.impactRayCount(judgment, released)
            x: root.noteLeft(note)
            y: root.height - 1
            width: root.noteWidth(note)
            height: 1
            visible: elapsed >= 0 && progress < 1
            opacity: {
                var base = judgment === "PERFECT"
                    ? (released ? 0.20 : 0.50)
                    : (released ? 0.70 : 1.0)
                return base * (1.0 - progress)
            }

            Rectangle {
                anchors.centerIn: parent
                width: Math.max(
                    6,
                    parent.width * parent.intensity * parent.effectScale
                    * (1.0 + parent.progress * 1.4)
                )
                height: width
                radius: width / 2
                color: parent.judgment === "PERFECT"
                       ? Qt.hsla((parent.progress * 0.22) % 1.0, 0.92, 0.62, 0.72)
                       : root.impactColor(parent.judgment)
            }

            Repeater {
                model: impactDelegate.rayCount
                delegate: Rectangle {
                    required property int index
                    readonly property real angle: 195
                        + (impactDelegate.rayCount <= 1
                           ? 75
                           : 150 * index / (impactDelegate.rayCount - 1))
                    readonly property real distance: (
                        5 + 15 * impactDelegate.progress
                    ) * impactDelegate.effectScale * impactDelegate.keyWidthScale
                    x: impactDelegate.width / 2
                        + Math.cos(angle * Math.PI / 180) * distance
                    y: Math.sin(angle * Math.PI / 180) * distance
                    width: Math.max(1, 1.4 * impactDelegate.effectScale)
                    height: Math.max(3, 7 * impactDelegate.effectScale)
                    radius: width / 2
                    rotation: angle - 90
                    color: impactDelegate.judgment === "PERFECT"
                           ? Qt.hsla(
                                 (index / Math.max(1, impactDelegate.rayCount)
                                  + impactDelegate.progress * 0.22) % 1.0,
                                 0.92,
                                 0.62,
                                 1.0
                             )
                           : root.impactColor(impactDelegate.judgment)
                }
            }
        }
    }

    Repeater {
        model: fallingNotesBridge.heldNotes
        delegate: Rectangle {
            required property int modelData
            x: root.noteLeft(modelData)
            y: 0
            width: root.noteWidth(modelData)
            height: root.height
            opacity: 0.28
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: "transparent" }
                GradientStop { position: 0.5; color: fallingNotesBridge.liveColor }
                GradientStop { position: 1.0; color: "transparent" }
            }
        }
    }

    Repeater {
        model: fallingNotesBridge.laneFades
        delegate: Rectangle {
            required property var modelData
            readonly property real progress: Math.max(
                0,
                Math.min(1, (root.clockMs - Number(modelData.startedAtMs)) / 150)
            )
            x: root.noteLeft(Number(modelData.note))
            y: 0
            width: root.noteWidth(Number(modelData.note))
            height: root.height
            opacity: 0.28 * Math.pow(1.0 - progress, 2)
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: "transparent" }
                GradientStop { position: 0.5; color: fallingNotesBridge.liveColor }
                GradientStop { position: 1.0; color: "transparent" }
            }
        }
    }

    Repeater {
        model: 53
        delegate: Rectangle {
            required property int index
            x: index * root.whiteWidth
            y: 0
            width: index % 7 === 0 ? 1.25 : 0.75
            height: root.height
            color: index % 7 === 0
                   ? fallingNotesBridge.borderColor
                   : fallingNotesBridge.gridColor
            opacity: index % 7 === 0 ? 0.59 : 0.69
        }
    }

    Repeater {
        model: fallingNotesBridge.visibleNotes
        delegate: Item {
            id: noteDelegate
            required property var modelData
            readonly property int note: Number(modelData.note)
            readonly property real noteStart: Number(modelData.start)
            readonly property real noteEnd: Number(modelData.end)
            readonly property bool approaching: root.currentPosition < noteStart
            readonly property real rawTop: root.height
                - ((noteEnd - root.currentPosition) / root.songHorizon) * root.height
            readonly property real rawBottom: root.height
                - ((noteStart - root.currentPosition) / root.songHorizon) * root.height
            readonly property real trailTop: Math.max(
                0.5,
                Math.min(root.height - 1, Math.min(rawTop, rawBottom))
            )
            readonly property real trailBottom: Math.max(
                trailTop,
                Math.min(root.height - 1, Math.max(rawTop, rawBottom))
            )
            readonly property real minimumHeight: approaching
                ? Math.max(4, Math.min(6, root.noteWidth(note) * 0.35))
                : 0
            readonly property real bodyTop: Math.max(
                0.5,
                trailBottom - Math.max(minimumHeight, trailBottom - trailTop)
            )
            x: root.noteLeft(note)
            y: bodyTop
            width: root.noteWidth(note)
            height: Math.max(0, trailBottom - bodyTop)
            visible: height > 0

            Rectangle {
                anchors.horizontalCenter: parent.horizontalCenter
                width: Math.max(7, parent.width * 0.58)
                height: parent.height
                radius: width / 2
                gradient: Gradient {
                    GradientStop {
                        position: 0.0
                        color: Qt.rgba(0, 0, 0, 0)
                    }
                    GradientStop {
                        position: noteDelegate.approaching ? 0.55 : 0.60
                        color: Qt.rgba(
                            fallingNotesBridge.scheduledColor.r,
                            fallingNotesBridge.scheduledColor.g,
                            fallingNotesBridge.scheduledColor.b,
                            0.12
                        )
                    }
                    GradientStop {
                        position: 1.0
                        color: Qt.rgba(
                            fallingNotesBridge.scheduledColor.r,
                            fallingNotesBridge.scheduledColor.g,
                            fallingNotesBridge.scheduledColor.b,
                            noteDelegate.approaching ? 0.47 : 0.0
                        )
                    }
                }
            }

            Rectangle {
                anchors.horizontalCenter: parent.horizontalCenter
                width: Math.max(1.8, parent.width * 0.12)
                height: parent.height
                radius: width / 2
                gradient: Gradient {
                    GradientStop {
                        position: 0.0
                        color: Qt.rgba(1, 1, 1, 0.06)
                    }
                    GradientStop {
                        position: 0.62
                        color: Qt.rgba(1, 1, 1, 0.74)
                    }
                    GradientStop {
                        position: 1.0
                        color: Qt.rgba(
                            1,
                            1,
                            1,
                            noteDelegate.approaching ? 1.0 : 0.0
                        )
                    }
                }
            }

            Rectangle {
                visible: parent.approaching
                x: 0
                y: Math.max(0, parent.height - height)
                width: parent.width
                height: Math.max(2, parent.width * 0.12)
                radius: Math.min(1.2, height / 3)
                color: "#ffffff"
                border.width: 1
                border.color: Qt.darker(
                    fallingNotesBridge.scheduledColor,
                    1.08
                )
            }
        }
    }

    Rectangle {
        visible: fallingNotesBridge.hasUsedRange
        x: 0
        y: 0
        width: Math.max(0, root.noteLeft(fallingNotesBridge.usedLow))
        height: root.height
        color: fallingNotesBridge.surfaceColor
        opacity: 0.80
    }

    Rectangle {
        visible: fallingNotesBridge.hasUsedRange
        x: root.noteLeft(fallingNotesBridge.usedHigh)
           + root.noteWidth(fallingNotesBridge.usedHigh)
        y: 0
        width: Math.max(0, root.width - x)
        height: root.height
        color: fallingNotesBridge.surfaceColor
        opacity: 0.80
    }

    Rectangle {
        x: 0
        y: root.height - Math.max(1, 1.5)
        width: root.width
        height: Math.max(1, 1.5)
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop {
                position: 0.0
                color: Qt.rgba(
                    fallingNotesBridge.liveColor.r,
                    fallingNotesBridge.liveColor.g,
                    fallingNotesBridge.liveColor.b,
                    0.14
                )
            }
            GradientStop {
                position: 0.5
                color: Qt.rgba(
                    fallingNotesBridge.liveColor.r,
                    fallingNotesBridge.liveColor.g,
                    fallingNotesBridge.liveColor.b,
                    0.73
                )
            }
            GradientStop {
                position: 1.0
                color: Qt.rgba(
                    fallingNotesBridge.liveColor.r,
                    fallingNotesBridge.liveColor.g,
                    fallingNotesBridge.liveColor.b,
                    0.14
                )
            }
        }
    }

    Rectangle {
        anchors.fill: parent
        color: "transparent"
        border.width: 1
        border.color: fallingNotesBridge.borderColor
    }
}
