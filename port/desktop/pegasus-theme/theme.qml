// Pixel 2 Android adaptation of the cover grid in PegasusG by ROC.
import QtQuick 2.12

FocusScope {
    id: root
    focus: true
    readonly property color ink: "#f2f3f5"
    readonly property color muted: "#b1b5ba"
    readonly property color gold: "#f6c549"
    readonly property real scaleFactor: Math.max(0.75, Math.min(width / 640, height / 440))
    function px(v) { return Math.round(v * scaleFactor) }
    property int section: 0
    property var sections: collectSections()
    readonly property var games: sections.length && section < sections.length ? sections[section].games : []
    readonly property var currentGame: grid.currentIndex >= 0 && grid.currentIndex < games.length ? games[grid.currentIndex] : null

    function collectSections() {
        var groups = [], all = [], seen = Object.create(null)
        for (var i = 0; i < api.collections.count; ++i) {
            var c = api.collections.get(i), list = [], isApps = c.shortName === "android" || /^android( apps)?$/i.test(c.name)
            for (var j = 0; j < c.games.count; ++j) {
                var game = c.games.get(j)
                list.push(game)
                if (isApps) continue
                var key = game.files.count ? game.files.get(0).path : c.name + "/" + game.title
                if (!seen[key]) { seen[key] = true; all.push(game) }
            }
            if (list.length) groups.push({label: isApps ? "应用" : c.name, games: list})
        }
        if (all.length) groups.unshift({label: "全部", games: all})
        return groups
    }
    function changeSection(n) {
        if (!sections.length) return
        section = (n + sections.length) % sections.length
        grid.currentIndex = games.length ? 0 : -1
        grid.positionViewAtBeginning()
        tabs.positionViewAtIndex(section, ListView.Contain)
    }
    function choose(n) {
        if (!games.length) return
        grid.currentIndex = Math.max(0, Math.min(games.length - 1, n))
        grid.positionViewAtIndex(grid.currentIndex, GridView.Contain)
    }
    function cover(game) {
        return game ? (game.assets.boxFront || game.assets.banner || game.assets.screenshot || "") : ""
    }
    function preview(game) {
        return game ? (game.assets.screenshot || game.assets.background || cover(game)) : ""
    }
    function play() { if (currentGame) currentGame.launch() }
    function developers(game) { return game && game.developer ? game.developer : "" }
    onGamesChanged: if (grid) grid.currentIndex = games.length ? 0 : -1

    Keys.onPressed: {
        if (api.keys.isNextPage(event)) changeSection(section + 1)
        else if (api.keys.isPrevPage(event)) changeSection(section - 1)
        else if (api.keys.isAccept(event)) { if (!event.isAutoRepeat) play() }
        else if (event.key === Qt.Key_Right) choose(grid.currentIndex + 1)
        else if (event.key === Qt.Key_Left) choose(grid.currentIndex - 1)
        else if (event.key === Qt.Key_Down) choose(grid.currentIndex + grid.columns)
        else if (event.key === Qt.Key_Up) choose(grid.currentIndex - grid.columns)
        else return
        event.accepted = true
    }
    Rectangle { anchors.fill: parent; color: "#030405" }

    Rectangle {
        id: head
        anchors { left: parent.left; right: parent.right; top: parent.top }
        height: root.px(45); color: "#111214"
        Row {
            id: credit
            anchors { right: parent.right; rightMargin: root.px(10); verticalCenter: parent.verticalCenter }
            spacing: root.px(6)
            Text { anchors.verticalCenter: parent.verticalCenter; text: "天马G ROC移植"; font.pixelSize: root.px(13); color: root.ink }
        }
        ListView {
            id: tabs
            anchors { left: parent.left; leftMargin: root.px(6); right: credit.left; rightMargin: root.px(8); top: parent.top; bottom: parent.bottom }
            orientation: ListView.Horizontal; clip: true; model: root.sections
            delegate: Rectangle {
                width: tabText.implicitWidth + root.px(22); height: tabs.height
                color: index === root.section ? "#2f3236" : "transparent"
                Text { id: tabText; anchors.centerIn: parent; text: modelData.label; font.pixelSize: root.px(16); color: index === root.section ? root.ink : root.muted }
                Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: root.px(3); color: root.gold; visible: index === root.section }
                MouseArea { anchors.fill: parent; onClicked: root.changeSection(index) }
            }
        }
    }
    Rectangle {
        id: info
        anchors { left: parent.left; top: head.bottom; bottom: foot.top }
        width: Math.round(parent.width / 3); color: "#08090a"
        Rectangle { anchors.right: parent.right; height: parent.height; width: 1; color: "#323437" }
        Column {
            anchors { fill: parent; margins: root.px(12) }
            spacing: root.px(9)
            Text {
                width: parent.width; height: root.px(50); color: root.ink; font.bold: true; font.pixelSize: root.px(20)
                text: root.currentGame ? root.currentGame.title : ""; verticalAlignment: Text.AlignVCenter
                wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideRight
            }
            Image {
                width: parent.width; height: Math.round(width * 9/16); source: root.preview(root.currentGame)
                fillMode: Image.PreserveAspectFit; asynchronous: true; sourceSize.width: 480
            }
            Text { width: parent.width; color: root.gold; font.pixelSize: root.px(14); text: root.developers(root.currentGame); visible: text.length > 0; elide: Text.ElideRight }
            Text {
                width: parent.width; color: root.muted; font.pixelSize: root.px(15)
                text: root.currentGame ? (root.currentGame.summary || root.currentGame.description || "") : ""
                wrapMode: Text.Wrap; maximumLineCount: 5; elide: Text.ElideRight
            }
        }
    }
    GridView {
        id: grid
        property int columns: width >= root.px(440) ? 3 : 2
        anchors { left: info.right; leftMargin: root.px(8); right: parent.right; rightMargin: root.px(8); top: head.bottom; topMargin: root.px(8); bottom: foot.top }
        model: root.games; clip: true; keyNavigationEnabled: false
        cellWidth: Math.floor(width / columns); cellHeight: Math.round(cellWidth * .72)
        delegate: Item {
            width: grid.cellWidth; height: grid.cellHeight
            readonly property bool chosen: index === grid.currentIndex
            Rectangle {
                anchors { fill: parent; margins: root.px(4) }
                color: "#15171a"; border.color: parent.chosen ? root.gold : "#323437"; border.width: parent.chosen ? root.px(3) : 1
                Image {
                    id: art
                    anchors { left: parent.left; right: parent.right; top: parent.top; bottom: caption.top; margins: root.px(4) }
                    source: root.cover(modelData); fillMode: Image.PreserveAspectFit; asynchronous: true; sourceSize.width: 260
                }
                Text {
                    id: caption
                    anchors { bottom: parent.bottom; left: parent.left; right: parent.right; margins: root.px(6) }
                    text: modelData.title; elide: Text.ElideRight; color: root.ink; font.pixelSize: root.px(14)
                    font.bold: chosen; horizontalAlignment: Text.AlignHCenter
                }
                MouseArea {
                    anchors.fill: parent
                    onClicked: { if (index === grid.currentIndex) root.play(); else root.choose(index) }
                }
            }
        }
    }
    Text {
        anchors.centerIn: grid; visible: !root.games.length
        text: "此分类暂无游戏"; color: root.muted; font.pixelSize: root.px(16)
    }
    Rectangle {
        id: foot
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
        height: root.px(32); color: "#111214"
        Text { anchors { left: parent.left; leftMargin: root.px(12); verticalCenter: parent.verticalCenter }
            color: root.muted; font.pixelSize: root.px(13); text: "十字键 选择     A 打开     L1 / R1 分类" }
        Text { anchors { right: parent.right; rightMargin: root.px(12); verticalCenter: parent.verticalCenter }
            color: root.ink; font.pixelSize: root.px(13); text: grid.count ? (grid.currentIndex + 1) + " / " + grid.count : "0" }
    }
}
