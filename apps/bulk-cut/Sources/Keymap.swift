import AppKit
import SwiftUI

// MARK: - Keyboard shortcuts
//
// Every key of the main window is an `Action` below with its default key in
// `Keymap.builtIn`. Three ways to change one, later ones winning:
//
// 1. Edit `builtIn` and rebuild (apps/bulk-cut/build.sh).
// 2. No rebuild: write ~/Library/Application Support/BulkCut/shortcuts.json
//    and relaunch. Only the actions you list change; they become the
//    defaults that Settings' "Default" buttons go back to:
//
//        { "setIn": "i", "setOut": "o", "zoomIn": ["ctrl+e", "cmd+="], "loop": [] }
//
//    A value is one key string or a list of them (only the first is used: an
//    action has one key); [] unbinds it. Keys starting with "_" are ignored.
// 3. Settings (⌘,): click an action's key and press the new one.
//
// Key strings: modifiers joined with "+" in front of one key.
//   modifiers  cmd, ctrl, opt (alt), shift
//   keys       space tab return esc left right up down home end pageup
//              pagedown delete (⌫) forwarddelete (⌦) f1…f12, or one
//              character: a letter, digit or one of - = [ ] ; ' , . / \ `
// Keys are matched by their position on a US keyboard (as Settings records
// them), so they stay put when the input language changes.

/// Everything the keyboard does in the main window. Each one has a
/// rebindable key (Settings › Keys, or shortcuts.json); the Clip menu shows
/// the current one.
enum Action: String, CaseIterable, Identifiable, Codable {
    case prevClip, nextClip, selectAll, toggleDelete, copyPath, focusNext, focusPrev
    case playPause, seekBack, seekForward, stepBack, stepForward, jumpBack, jumpForward
    case goStart, goEnd, speedDown, speedUp, sectionsOnly, loop
    case setIn, setOut, prevEdge, nextEdge, removeRange, clearRanges
    case turn, turnLeft, clearZoom
    case zoomIn, zoomOut

    var id: String { rawValue }

    var title: String {
        switch self {
        case .prevClip: "Previous Clip"
        case .nextClip: "Next Clip"
        case .selectAll: "Select All (a Click Selects One Again)"
        case .toggleDelete: "Stage / Unstage Delete"
        case .copyPath: "Copy Path (Absolute)"
        case .focusNext: "Review Focus: Next (Everything / a Sequence / Picks Only)"
        case .focusPrev: "Review Focus: Previous"
        case .playPause: "Play / Pause (and Autoplay On / Off)"
        case .seekBack: "Back a Little"
        case .seekForward: "Forward a Little"
        case .stepBack: "Back One Frame"
        case .stepForward: "Forward One Frame"
        case .jumpBack: "Back a Lot"
        case .jumpForward: "Forward a Lot"
        case .goStart: "Go to Start"
        case .goEnd: "Go to End"
        case .speedDown: "Slower"
        case .speedUp: "Faster"
        case .sectionsOnly: "Play Sections Only (Skip the Grey) On / Off"
        case .loop: "Loop On / Off"
        case .setIn: "Crop Left (Keep From Here)"
        case .setOut: "Crop Right (Keep Up to Here)"
        case .prevEdge: "Previous Crop Edge"
        case .nextEdge: "Next Crop Edge"
        case .removeRange: "Remove Kept Range Under Playhead"
        case .clearRanges: "Clear All Crops on Clip"
        case .turn: "Rotate 90° Right"
        case .turnLeft: "Rotate 90° Left"
        case .clearZoom: "Clear Zoom / Crop (Drag on the Picture Sets It)"
        case .zoomIn: "Zoom Timeline In"
        case .zoomOut: "Zoom Timeline Out"
        }
    }

    enum Group: String, CaseIterable {
        case clips = "Clips", playback = "Playback", crop = "Crop", picture = "Picture", timeline = "Timeline"
    }

    var group: Group {
        switch self {
        case .prevClip, .nextClip, .selectAll, .toggleDelete, .copyPath, .focusNext, .focusPrev: .clips
        case .playPause, .seekBack, .seekForward, .stepBack, .stepForward, .jumpBack, .jumpForward,
             .goStart, .goEnd, .speedDown, .speedUp, .sectionsOnly, .loop: .playback
        case .setIn, .setOut, .prevEdge, .nextEdge, .removeRange, .clearRanges: .crop
        case .turn, .turnLeft, .clearZoom: .picture
        case .zoomIn, .zoomOut: .timeline
        }
    }

    /// Changes what is staged (the debug log records these).
    var changesEdits: Bool {
        switch self {
        case .toggleDelete, .setIn, .setOut, .removeRange, .clearRanges, .turn, .turnLeft, .clearZoom: true
        default: false
        }
    }

    /// Held down, does key repeat fire it again? Not for toggles and edits.
    var repeats: Bool {
        switch self {
        case .playPause, .selectAll, .toggleDelete, .copyPath, .setIn, .setOut, .removeRange, .clearRanges, .turn, .turnLeft, .clearZoom, .speedDown, .speedUp,
             .sectionsOnly, .loop, .focusNext, .focusPrev: false
        default: true
        }
    }
}

/// One key plus modifiers, matched by key code (layout-independent);
/// `key` is how the key itself is shown.
struct KeyCombo: Codable, Hashable {
    var keyCode: UInt16
    var modifiers: UInt
    var key: String

    static let mask: NSEvent.ModifierFlags = [.control, .option, .shift, .command]

    init(_ keyCode: UInt16, _ mods: NSEvent.ModifierFlags = [], _ key: String) {
        self.keyCode = keyCode
        self.modifiers = mods.intersection(Self.mask).rawValue
        self.key = key
    }

    /// nil for a bare modifier press.
    init?(event e: NSEvent) {
        guard e.type == .keyDown else { return nil }
        let name = Self.names[e.keyCode]
            ?? e.characters(byApplyingModifiers: [])?.uppercased()
            ?? e.charactersIgnoringModifiers?.uppercased()
        guard let name, !name.isEmpty, !name.unicodeScalars.allSatisfy({ CharacterSet.controlCharacters.contains($0) })
        else { return nil }
        self.init(e.keyCode, e.modifierFlags, name)
    }

    var flags: NSEvent.ModifierFlags { NSEvent.ModifierFlags(rawValue: modifiers) }

    /// ⌘A, ⌘X, ⌘C, ⌘V: with text selected, these are the text's, whatever
    /// action they are bound to.
    static func isTextEditing(_ e: NSEvent) -> Bool {
        e.modifierFlags.intersection(mask) == .command && [0, 7, 8, 9].contains(e.keyCode)
    }

    /// `as`: match the event as if it were that key code instead.
    func matches(_ e: NSEvent, as code: UInt16? = nil) -> Bool {
        (code ?? e.keyCode) == keyCode && e.modifierFlags.intersection(Self.mask).rawValue == modifiers
    }

    var label: String {
        var s = ""
        if flags.contains(.control) { s += "⌃" }
        if flags.contains(.option) { s += "⌥" }
        if flags.contains(.shift) { s += "⇧" }
        if flags.contains(.command) { s += "⌘" }
        return s + key
    }

    /// Named keys in shortcuts.json and their key codes.
    static let namedCodes: [String: UInt16] = [
        "space": 49, "tab": 48, "return": 36, "enter": 36, "esc": 53, "escape": 53,
        "left": 123, "right": 124, "down": 125, "up": 126, "home": 115, "end": 119,
        "pageup": 116, "pagedown": 121, "delete": 51, "backspace": 51, "forwarddelete": 117,
        "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97, "f7": 98, "f8": 100,
        "f9": 101, "f10": 109, "f11": 103, "f12": 111,
    ]

    /// Character keys by their position on a US (ANSI) keyboard.
    static let characterCodes: [Character: UInt16] = [
        "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9, "b": 11,
        "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "1": 18, "2": 19, "3": 20, "4": 21,
        "6": 22, "5": 23, "=": 24, "9": 25, "7": 26, "-": 27, "8": 28, "0": 29, "]": 30, "o": 31,
        "u": 32, "[": 33, "i": 34, "p": 35, "l": 37, "j": 38, "'": 39, "k": 40, ";": 41, "\\": 42,
        ",": 43, "/": 44, "n": 45, "m": 46, ".": 47, "`": 50,
    ]

    /// A key string from shortcuts.json ("ctrl+shift+left", "q", "cmd+="); nil if it isn't one.
    init?(parsing text: String) {
        let raw = text.trimmingCharacters(in: .whitespaces).lowercased()
        var parts = raw.split(separator: "+", omittingEmptySubsequences: false).map(String.init)
        guard let key = parts.popLast(), !key.isEmpty else { return nil }     // "+" itself: write shift+=
        var mods: NSEvent.ModifierFlags = []
        for m in parts {
            switch m {
            case "cmd", "command", "⌘": mods.insert(.command)
            case "ctrl", "control", "⌃": mods.insert(.control)
            case "opt", "option", "alt", "⌥": mods.insert(.option)
            case "shift", "⇧": mods.insert(.shift)
            default: return nil
            }
        }
        let code: UInt16
        if let c = Self.namedCodes[key] { code = c }
        else if key.count == 1, let c = Self.characterCodes[Character(key)] { code = c }
        else { return nil }
        self.init(code, mods, Self.names[code] ?? key.uppercased())
    }

    static let names: [UInt16: String] = [
        123: "←", 124: "→", 125: "↓", 126: "↑", 49: "Space", 48: "⇥", 51: "⌫", 117: "⌦",
        36: "⏎", 76: "⌅", 53: "⎋", 115: "Home", 119: "End", 116: "PgUp", 121: "PgDn",
        122: "F1", 120: "F2", 99: "F3", 118: "F4", 96: "F5", 97: "F6", 98: "F7", 100: "F8",
        101: "F9", 109: "F10", 103: "F11", 111: "F12",
    ]
}

/// The bindings in force, kept in UserDefaults; Settings › Keys edits them.
@MainActor
final class Keymap: ObservableObject {
    static let shared = Keymap()

    /// THE TABLE: the built-in key of every action. README.md lists the same.
    nonisolated static let builtIn: [Action: KeyCombo] = [
        .prevClip: .init(126, [], "↑"),
        .nextClip: .init(125, [], "↓"),
        .selectAll: .init(0, .command, "A"),
        .toggleDelete: .init(51, [], "⌫"),
        .copyPath: .init(8, .command, "C"),
        // F for focus: a review folder's one sequence (or the picks) at a time.
        .focusNext: .init(3, [], "F"),
        .focusPrev: .init(3, .shift, "F"),
        .playPause: .init(49, [], "Space"),
        .seekBack: .init(123, [], "←"),
        .seekForward: .init(124, [], "→"),
        .stepBack: .init(123, .control, "←"),
        .stepForward: .init(124, .control, "→"),
        .jumpBack: .init(123, .command, "←"),
        .jumpForward: .init(124, .command, "→"),
        .goStart: .init(115, [], "Home"),
        .goEnd: .init(119, [], "End"),
        .speedDown: .init(48, .shift, "⇥"),
        .speedUp: .init(48, [], "⇥"),
        .sectionsOnly: .init(1, [], "S"),
        .loop: .init(37, [], "L"),
        // As in DaVinci Resolve with its Premiere Pro keyboard preset: Q / W
        // ripple start / end to playhead; ⌃E / ⌃W zoom in / out.
        .setIn: .init(12, [], "Q"),
        .setOut: .init(13, [], "W"),
        .prevEdge: .init(123, .option, "←"),
        .nextEdge: .init(124, .option, "→"),
        .removeRange: .init(51, .control, "⌫"),
        .clearRanges: .init(51, [.control, .shift], "⌫"),
        .turn: .init(15, [], "R"),
        .turnLeft: .init(15, .shift, "R"),
        .clearZoom: .init(6, .shift, "Z"),
        .zoomIn: .init(14, .control, "E"),
        .zoomOut: .init(13, .control, "W"),
    ]

    /// ~/Library/Application Support/BulkCut/shortcuts.json
    /// (BULKCUT_SHORTCUTS=<path> points elsewhere, for testing).
    static let overrideURL: URL = {
        if let p = ProcessInfo.processInfo.environment["BULKCUT_SHORTCUTS"], !p.isEmpty {
            return URL(fileURLWithPath: (p as NSString).expandingTildeInPath)
        }
        return FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/BulkCut/shortcuts.json")
    }()

    /// The defaults in force: `builtIn` with shortcuts.json on top, and what
    /// was wrong in that file (shown in orange in Settings and the ⌘/ list).
    /// Read once, at launch.
    static let loaded: (defaults: [Action: KeyCombo], messages: [String]) = loadOverrides(from: overrideURL)

    static var defaults: [Action: KeyCombo] { loaded.defaults }
    static var overrideMessages: [String] { loaded.messages }

    /// `builtIn` with the overrides in `url` applied. A key given to one action
    /// is taken from any other that had it by default.
    nonisolated static func loadOverrides(from url: URL) -> (defaults: [Action: KeyCombo], messages: [String]) {
        var b = builtIn
        var messages: [String] = []
        guard let data = try? Data(contentsOf: url) else { return (b, []) }
        guard let doc = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else {
            return (b, ["shortcuts.json is not a JSON object; using the built-in keys"])
        }
        for name in doc.keys.sorted() where !name.hasPrefix("_") {
            guard let action = Action(rawValue: name) else {
                messages.append("shortcuts.json: unknown action \"\(name)\"")
                continue
            }
            let value = doc[name]
            let list: [String]
            if let one = value as? String { list = [one] }
            else if let many = value as? [String] { list = many }
            else { messages.append("shortcuts.json: \"\(name)\" must be a key string or a list of them"); continue }
            guard let text = list.first else { b[action] = nil; continue }
            if list.count > 1 { messages.append("\(name): one key per action; using \"\(text)\"") }
            guard let combo = KeyCombo(parsing: text) else {
                messages.append("\(name): \"\(text)\" is not a key string"); continue
            }
            for (other, c) in b where c == combo && other != action {
                b[other] = nil
                messages.append("\(name): \(combo.label) was \(other.rawValue)'s, which now has no key")
            }
            b[action] = combo
        }
        return (b, messages)
    }

    @Published private(set) var bindings: [Action: KeyCombo]
    /// The action whose new key the next key press sets (Settings › Keys).
    @Published var recording: Action?
    /// What the last recording took away from another action, for Settings to say.
    @Published private(set) var lastNote: String?

    static let seekSteps: [Double] = [0.5, 1, 2, 3]
    static let jumpSteps: [Double] = [3, 5, 10, 15, 30]
    @Published var seekStep: Double { didSet { UserDefaults.standard.set(seekStep, forKey: "seekStep") } }
    @Published var jumpStep: Double { didSet { UserDefaults.standard.set(jumpStep, forKey: "jumpStep") } }

    /// What Settings changed: only what differs from the defaults, so a
    /// changed default reaches every action the user never rebound there.
    private struct Stored: Codable { var v: Int?; var bound: [String: KeyCombo]; var unbound: [String] }

    private init() {
        var b = Self.defaults
        if let data = UserDefaults.standard.data(forKey: "keymap"),
           let s = try? JSONDecoder().decode(Stored.self, from: data) {
            var fromSettings: [KeyCombo: Action] = [:]
            for (k, v) in s.bound { if let a = Action(rawValue: k) { b[a] = v; fromSettings[v] = a } }
            for k in s.unbound { if let a = Action(rawValue: k) { b[a] = nil } }
            // A key Settings gave one action and shortcuts.json another: Settings wins.
            for (a, c) in b where fromSettings[c].map({ $0 != a }) == true { b[a] = nil }
        }
        bindings = b
        let d = UserDefaults.standard
        seekStep = d.object(forKey: "seekStep") as? Double ?? 1
        jumpStep = d.object(forKey: "jumpStep") as? Double ?? 5
    }

    private func save() {
        let changed = bindings.filter { Self.defaults[$0.key] != $0.value }
        let s = Stored(v: 2, bound: Dictionary(uniqueKeysWithValues: changed.map { ($0.key.rawValue, $0.value) }),
                       unbound: Action.allCases.filter { bindings[$0] == nil && Self.defaults[$0] != nil }.map(\.rawValue))
        if let data = try? JSONEncoder().encode(s) { UserDefaults.standard.set(data, forKey: "keymap") }
    }

    /// ⌦ (forward delete, fn-⌫ on a laptop) does whatever ⌫ does unless it
    /// has a binding of its own: which one is "Delete" depends on the keyboard.
    func action(for e: NSEvent) -> Action? {
        if let a = bindings.first(where: { $0.value.matches(e) })?.key { return a }
        guard e.keyCode == 117 else { return nil }
        return bindings.first { $0.value.matches(e, as: 51) }?.key
    }

    func label(_ a: Action) -> String { bindings[a]?.label ?? "—" }

    /// Give `a` this key, taking it from whatever had it.
    func bind(_ a: Action, to c: KeyCombo) {
        lastNote = nil
        for (other, combo) in bindings where combo == c && other != a {
            bindings[other] = nil
            lastNote = "\(c.label) was \"\(other.title)\", which now has no key."
        }
        bindings[a] = c
        save()
    }

    func unbind(_ a: Action) { bindings[a] = nil; lastNote = nil; save() }

    func reset(_ a: Action) {
        if let c = Self.defaults[a] { bind(a, to: c) } else { unbind(a) }
    }

    func resetAll() {
        bindings = Self.defaults
        lastNote = nil
        save()
    }

    /// While recording: the key press becomes the binding (⎋ cancels). Returns
    /// nil to swallow the event.
    func capture(_ e: NSEvent) -> NSEvent? {
        guard let a = recording else { return e }
        if e.keyCode == 53, e.modifierFlags.intersection(KeyCombo.mask).isEmpty { recording = nil; return nil }
        guard let c = KeyCombo(event: e) else { return nil }
        bind(a, to: c)
        recording = nil
        return nil
    }
}
