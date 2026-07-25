import QtQuick

Item {
    id: root
    clip: true
    readonly property var activeNotes: keyboardBridge.activeNotes
    readonly property var releasedNotes: keyboardBridge.releasedNotes
    readonly property bool hasUsedRange: keyboardBridge.hasUsedRange
    readonly property int usedLow: keyboardBridge.usedLow
    readonly property int usedHigh: keyboardBridge.usedHigh

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

    function isUsed(note) {
        return !root.hasUsedRange
                || (note >= root.usedLow && note <= root.usedHigh)
    }

    function isActive(note) {
        return keyboardBridge.renderingEnabled
                && root.activeNotes.indexOf(note) >= 0
                && root.releasedNotes.indexOf(note) < 0
    }

    readonly property real whiteWidth: Math.max(1, (width - 1) / 52)

    Rectangle {
        anchors.fill: parent
        color: keyboardBridge.surfaceColor
    }

    Repeater {
        model: 88
        delegate: Rectangle {
            required property int index
            readonly property int note: 21 + index
            readonly property bool active: keyboardBridge.renderingEnabled
                && root.activeNotes.indexOf(note) >= 0
                && root.releasedNotes.indexOf(note) < 0
            visible: root.isWhite(note)
            x: root.whiteIndex(note) * root.whiteWidth + 0.5
            y: 0.5
            width: root.whiteWidth
            height: Math.max(1, root.height - 1)
            color: active
                   ? keyboardBridge.accentColor
                   : ((!root.hasUsedRange
                       || (note >= root.usedLow && note <= root.usedHigh))
                      ? keyboardBridge.surfaceColor
                      : Qt.darker(keyboardBridge.surfaceColor, 1.18))
            border.width: 1
            border.color: active
                          ? keyboardBridge.accentBorderColor
                          : keyboardBridge.borderColor
        }
    }

    Repeater {
        model: 88
        delegate: Text {
            required property int index
            readonly property int note: 21 + index
            readonly property bool labelNote: note === 21 || note % 12 === 0
            visible: root.isWhite(note) && labelNote
            x: root.whiteIndex(note) * root.whiteWidth
            y: 1
            width: root.whiteWidth
            height: Math.max(1, root.height - 3)
            text: note === 21 ? "A0" : "C" + (Math.floor(note / 12) - 1)
            color: keyboardBridge.textColor
            opacity: (!root.hasUsedRange
                      || (note >= root.usedLow && note <= root.usedHigh))
                     ? 1.0 : 0.47
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignBottom
            font.pixelSize: Math.max(
                7,
                Math.min(12, Math.round(Math.min(root.height * 0.16, root.whiteWidth * 0.9)))
            )
            renderType: Text.NativeRendering
        }
    }

    Repeater {
        model: 88
        delegate: Rectangle {
            required property int index
            readonly property int note: 21 + index
            readonly property bool active: keyboardBridge.renderingEnabled
                && root.activeNotes.indexOf(note) >= 0
                && root.releasedNotes.indexOf(note) < 0
            visible: !root.isWhite(note)
            x: (root.whiteIndex(note) * root.whiteWidth) - width / 2 + 0.5
            y: 0.5
            width: root.whiteWidth * 0.62
            height: Math.max(1, (root.height - 1) * 0.60)
            color: active
                   ? keyboardBridge.accentColor
                   : ((!root.hasUsedRange
                       || (note >= root.usedLow && note <= root.usedHigh))
                      ? keyboardBridge.blackColor
                      : Qt.lighter(keyboardBridge.blackColor, 1.45))
            border.width: 1
            border.color: active
                          ? keyboardBridge.accentBorderColor
                          : keyboardBridge.borderColor
        }
    }
}
