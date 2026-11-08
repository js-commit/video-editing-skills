import AppKit
import SwiftUI

// MARK: - The shortcut table
//
// Every remappable key of the review loop is in `Shortcuts.table` below: one
// row per action, its default keys and what it does. The in-app legend (⌘/)
// is built from it; README.md lists the same defaults.
//
// Two ways to change a key:
//
// 1. No rebuild: write ~/Library/Application Support/EditReview/shortcuts.json
//    and relaunch the app. Only the actions you list change:
//
//        { "playPause": "ctrl+space", "zoomIn": ["ctrl+e", "cmd+="], "goToEnd": [] }
//
//    A value is one key string or a list of them; [] unbinds the action.
//    Keys starting with "_" are ignored (use them for comments).
//
// 2. Edit the defaults in `table` and rebuild (apps/edit-review/build.sh).
//
// Key strings: modifiers joined with "+" in front of one key.
//   modifiers  cmd, ctrl, opt (alt), shift
//   keys       space tab left right up down home end pageup pagedown
//              delete (⌫) forwarddelete (⌦), or one character: "e", "=", "/"
// A plain character without cmd / ctrl / opt is refused: the note field is
// always focused, so it would swallow typing and dictation. ⏎ and ESC are fixed
// (they belong to the note field) and so are the menu shortcuts; rebind menu
// items in System Settings › Keyboard › Keyboard Shortcuts › App Shortcuts.

/// Everything the review keys can do.
enum ReviewAction: String, CaseIterable, Sendable {
    case playPause, speedUp, speedDown
    case seekBack, seekForward, seekBackBig, seekForwardBig
    case frameBack, frameForward, halfSecondBack, halfSecondForward
    case zoomIn, zoomOut
    case previousCut, nextCut, previousChange, nextChange
    case goToStart, goToEnd
    case deleteNote, archiveNotes, undo, selectAllNotes
    case find, findNext, findPrevious
}

/// One key with its modifiers, e.g. "ctrl+shift+left".
struct KeyCombo: Equatable, Sendable {
    let key: String
    let cmd: Bool, ctrl: Bool, opt: Bool, shift: Bool

    /// Named keys and the key codes they stand for (layout-independent).
    static let named: [String: [UInt16]] = [
        "space": [49], "tab": [48], "return": [36, 76], "esc": [53],
        "left": [123], "right": [124], "up": [126], "down": [125],
        "home": [115], "end": [119], "pageup": [116], "pagedown": [121],
        "delete": [51], "forwarddelete": [117],
    ]
    private static let aliases = ["backspace": "delete", "escape": "esc", "enter": "return", "spacebar": "space"]

    /// nil when the text is not a key string (see the table's header).
    static func parse(_ text: String) -> KeyCombo? {
        var raw = text.trimmingCharacters(in: .whitespaces).lowercased()
        guard !raw.isEmpty else { return nil }
        var key = ""
        if raw.hasSuffix("++") || raw == "+" { key = "+"; raw = String(raw.dropLast(raw == "+" ? 1 : 2)) }
        var parts = raw.split(separator: "+", omittingEmptySubsequences: true).map(String.init)
        if key.isEmpty { key = parts.popLast() ?? "" }
        key = aliases[key] ?? key
        guard named[key] != nil || key.count == 1 else { return nil }
        var cmd = false, ctrl = false, opt = false, shift = false
        for m in parts {
            switch m {
            case "cmd", "command", "⌘": cmd = true
            case "ctrl", "control", "⌃": ctrl = true
            case "opt", "option", "alt", "⌥": opt = true
            case "shift", "⇧": shift = true
            default: return nil
            }
        }
        return KeyCombo(key: key, cmd: cmd, ctrl: ctrl, opt: opt, shift: shift)
    }

    /// A key the note field would type (or ⏎ / ESC, which it owns).
    var clashesWithTyping: Bool {
        if cmd || ctrl || opt { return false }
        return key.count == 1 || key == "return" || key == "esc"
    }

    func matches(_ e: NSEvent) -> Bool {
        let m = e.modifierFlags.intersection(.deviceIndependentFlagsMask)
        guard m.contains(.command) == cmd, m.contains(.control) == ctrl,
              m.contains(.option) == opt, m.contains(.shift) == shift else { return false }
        if let codes = Self.named[key] { return codes.contains(e.keyCode) }
        return e.charactersIgnoringModifiers?.lowercased() == key
    }

    /// "⌃⇧←", "⌘⌫", "SPACE".
    var label: String {
        let symbols: [String: String] = [
            "space": "SPACE", "tab": "TAB", "return": "⏎", "esc": "ESC",
            "left": "←", "right": "→", "up": "↑", "down": "↓",
            "home": "HOME", "end": "END", "pageup": "PAGE UP", "pagedown": "PAGE DOWN",
            "delete": "⌫", "forwarddelete": "⌦",
        ]
        let mods = (ctrl ? "⌃" : "") + (opt ? "⌥" : "") + (shift ? "⇧" : "") + (cmd ? "⌘" : "")
        return mods + (symbols[key] ?? key.uppercased())
    }
}

enum Shortcuts {
    struct Row: Sendable {
        let action: ReviewAction
        let keys: [String]
        let what: String
    }

    /// THE TABLE: default keys for every remappable action, in legend order.
    static let table: [Row] = [
        .init(action: .playPause, keys: ["space"], what: "play / pause (with text in the field it types a space)"),
        .init(action: .speedUp, keys: ["tab"], what: "faster: 1× → 1.5× → 1.7× → 2× → 2.5× → 3× → 1×"),
        .init(action: .speedDown, keys: ["shift+tab"], what: "slower: the same list backwards"),
        .init(action: .seekBack, keys: ["left"], what: "back 2 s; paused with a note selected, move that note instead"),
        .init(action: .seekForward, keys: ["right"], what: "forward 2 s (same note rule)"),
        .init(action: .seekBackBig, keys: ["shift+left"], what: "back 10 s (same note rule)"),
        .init(action: .seekForwardBig, keys: ["shift+right"], what: "forward 10 s (same note rule)"),
        .init(action: .frameBack, keys: ["ctrl+left"], what: "back one frame; hold to run (same note rule)"),
        .init(action: .frameForward, keys: ["ctrl+right"], what: "forward one frame (same note rule)"),
        .init(action: .halfSecondBack, keys: ["ctrl+shift+left"], what: "back ½ s (same note rule)"),
        .init(action: .halfSecondForward, keys: ["ctrl+shift+right"], what: "forward ½ s (same note rule)"),
        .init(action: .zoomIn, keys: ["ctrl+e"], what: "zoom the waveform and seek bar in around the playhead"),
        .init(action: .zoomOut, keys: ["ctrl+w"], what: "zoom them back out"),
        .init(action: .previousCut, keys: ["up"], what: "previous cut (needs cuts.json); paused with a note selected, move the note there"),
        .init(action: .nextCut, keys: ["down"], what: "next cut (same rules)"),
        .init(action: .previousChange, keys: ["opt+up"], what: "previous change since the last cut, played from a second before (needs changes.json)"),
        .init(action: .nextChange, keys: ["opt+down"], what: "next change"),
        .init(action: .goToStart, keys: ["home"], what: "jump to the start of the video"),
        .init(action: .goToEnd, keys: ["end"], what: "jump to the end"),
        .init(action: .deleteNote, keys: ["delete", "forwarddelete"], what: "empty field + notes selected: delete them"),
        .init(action: .archiveNotes, keys: ["cmd+delete"], what: "archive the selected notes: kept, but left out of the export"),
        .init(action: .undo, keys: ["cmd+z"], what: "undo the last delete, add, archive or restore (empty field)"),
        .init(action: .selectAllNotes, keys: ["cmd+a"], what: "select every note (empty field)"),
        .init(action: .find, keys: ["cmd+f"], what: "find in the transcript"),
        .init(action: .findNext, keys: ["cmd+g"], what: "next find hit (⏎ in the find bar)"),
        .init(action: .findPrevious, keys: ["cmd+shift+g"], what: "previous find hit (⇧⏎ in the find bar)"),
    ]

    /// Seconds the seek keys move. Edit here and rebuild to change them.
    static let seekStep = 2.0
    static let bigSeekStep = 10.0
    static let smallSeekStep = 0.5

    /// Keys that are not in the table (shown in the legend as they are).
    static let fixed: [(keys: String, what: String)] = [
        ("⏎", "stamp the field's text as a note at the playhead, clear it, resume. Empty field + previous-cut notes selected: bring them back"),
        ("ESC", "clear the field (closes the find bar when the field is empty)"),
        ("⌥⏎", "in an inline note edit: a line break"),
        ("⇧-click / ⌘-click", "select a range of notes / add one to the selection"),
        ("⌥-drag", "seek on the timeline without snapping to cuts"),
        ("scroll / ⇧scroll", "over the timeline: zoom around the pointer / move the window"),
        ("⌘O", "open a video (or drop one onto the window)"),
        ("⌘⇧O", "open the path on the clipboard"),
        ("⌘⇧C", "copy the live notes to the clipboard as JSON"),
        ("⌘/", "this legend"),
        ("⌘= / ⌘- / ⌘0", "bigger / smaller / default transcript and notes text"),
    ]

    /// ~/Library/Application Support/EditReview/shortcuts.json
    /// (EDIT_REVIEW_SHORTCUTS=<path> points elsewhere, for testing).
    static let overrideURL: URL = {
        if let p = ProcessInfo.processInfo.environment["EDIT_REVIEW_SHORTCUTS"], !p.isEmpty {
            return URL(fileURLWithPath: (p as NSString).expandingTildeInPath)
        }
        return FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/EditReview/shortcuts.json")
    }()

    /// The bindings in force (defaults + shortcuts.json), and any problems
    /// reading the override file. Read once, at launch.
    static let loaded: (bindings: [(ReviewAction, KeyCombo)], messages: [String]) = load()

    private static func load() -> (bindings: [(ReviewAction, KeyCombo)], messages: [String]) {
        var keys: [ReviewAction: [String]] = [:]
        for r in table { keys[r.action] = r.keys }
        var messages: [String] = []
        if let data = try? Data(contentsOf: overrideURL) {
            if let doc = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] {
                for (name, value) in doc where !name.hasPrefix("_") {
                    guard let action = ReviewAction(rawValue: name) else {
                        messages.append("shortcuts.json: unknown action \"\(name)\"")
                        continue
                    }
                    if let one = value as? String { keys[action] = [one] }
                    else if let list = value as? [String] { keys[action] = list }
                    else { messages.append("shortcuts.json: \"\(name)\" must be a key string or a list of them") }
                }
            } else {
                messages.append("shortcuts.json is not a JSON object; using the default keys")
            }
        }
        var out: [(ReviewAction, KeyCombo)] = []
        for r in table {
            for text in keys[r.action] ?? [] {
                guard let combo = KeyCombo.parse(text) else {
                    messages.append("\(r.action.rawValue): \"\(text)\" is not a key string"); continue
                }
                if combo.clashesWithTyping {
                    messages.append("\(r.action.rawValue): \"\(text)\" would swallow typing; add cmd, ctrl or opt"); continue
                }
                if let other = out.first(where: { $0.1 == combo }) {
                    messages.append("\(r.action.rawValue): \"\(text)\" is already \(other.0.rawValue); ignored"); continue
                }
                out.append((r.action, combo))
            }
        }
        return (out, messages)
    }

    /// The action a key press stands for, if any.
    static func action(for e: NSEvent) -> ReviewAction? {
        loaded.bindings.first { $0.1.matches(e) }?.0
    }

    /// "⌃E", "⌫ / ⌦", or "(none)" for an unbound action.
    static func label(_ action: ReviewAction) -> String {
        let l = loaded.bindings.filter { $0.0 == action }.map(\.1.label)
        return l.isEmpty ? "(none)" : l.joined(separator: " / ")
    }
}

struct ShortcutsView: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Keyboard Shortcuts").font(.headline)
            Text("The note field is always focused; letters go into it. Change the review keys in ~/Library/Application Support/EditReview/shortcuts.json (README › Customizing the keys).")
                .font(.callout).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            ForEach(Shortcuts.loaded.messages, id: \.self) { m in
                Text(m).font(.caption).foregroundStyle(.orange)
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 10) {
                    section("Review", Shortcuts.table.map { (Shortcuts.label($0.action), $0.what) })
                    section("Fixed keys and menus", Shortcuts.fixed.map { ($0.keys, $0.what) })
                }
            }
            .frame(maxHeight: 560)
        }
        .padding(16)
        .frame(width: 500)
    }

    private func section(_ title: String, _ items: [(String, String)]) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title).font(.subheadline.weight(.semibold)).foregroundStyle(.secondary)
            Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 4) {
                ForEach(Array(items.enumerated()), id: \.offset) { _, s in
                    GridRow {
                        Text(s.0)
                            .font(.system(.body, design: .monospaced).weight(.semibold))
                            .padding(.horizontal, 6).padding(.vertical, 1)
                            .background(Color.secondary.opacity(0.15))
                            .clipShape(RoundedRectangle(cornerRadius: 4))
                            .gridColumnAlignment(.trailing)
                        Text(s.1).font(.callout)
                    }
                }
            }
        }
    }
}
