import SwiftUI

/// Settings › Keys: every action's key, rebindable by clicking it and
/// pressing the new one; plus how far "a little" and "a lot" seek. The
/// defaults are the built-in keys with shortcuts.json on top (Keymap.swift).
struct SettingsView: View {
    @ObservedObject var keymap: Keymap

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Click a key, then press the new one (⎋ cancels). A key already in use moves to the new action. "
                 + "To set keys in a file instead (handy to keep or share): \(Keymap.overrideURL.path), see the README.")
                .font(.callout).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
            ForEach(Keymap.overrideMessages, id: \.self) { m in
                Text(m).font(.caption).foregroundStyle(.orange)
            }
            ScrollView {
                Grid(alignment: .leading, horizontalSpacing: 14, verticalSpacing: 6) {
                    ForEach(Action.Group.allCases, id: \.self) { g in
                        GridRow {
                            Text(g.rawValue).font(.subheadline.weight(.semibold)).foregroundStyle(.secondary)
                                .padding(.top, 8)
                                .gridCellColumns(3)
                        }
                        ForEach(Action.allCases.filter { $0.group == g }) { a in row(a) }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            if let note = keymap.lastNote {
                Text(note).font(.callout).foregroundStyle(.orange)
            }
            Divider()
            HStack(spacing: 24) {
                Picker("A little:", selection: $keymap.seekStep) {
                    ForEach(Keymap.seekSteps, id: \.self) { Text(Self.seconds($0)).tag($0) }
                }
                .fixedSize()
                Picker("A lot:", selection: $keymap.jumpStep) {
                    ForEach(Keymap.jumpSteps, id: \.self) { Text(Self.seconds($0)).tag($0) }
                }
                .fixedSize()
                Spacer()
                Button("Restore All Defaults") { keymap.resetAll() }
            }
        }
        .padding(20)
        .frame(width: 640, height: 680)
        .onDisappear { keymap.recording = nil }
    }

    private func row(_ a: Action) -> some View {
        let isRecording = keymap.recording == a
        return GridRow {
            Text(a.title)
            Button { keymap.recording = isRecording ? nil : a } label: {
                Text(isRecording ? "Press a key…" : keymap.label(a))
                    .font(.system(.body, design: .monospaced).weight(.semibold))
                    .frame(minWidth: 120)
            }
            .buttonStyle(.bordered)
            .tint(isRecording ? Color.accentColor : nil)
            HStack(spacing: 10) {
                Button("Clear") { keymap.unbind(a) }.disabled(keymap.bindings[a] == nil)
                Button("Default") { keymap.reset(a) }.disabled(keymap.bindings[a] == Keymap.defaults[a])
            }
            .buttonStyle(.borderless)
            .controlSize(.small)
        }
    }

    static func seconds(_ s: Double) -> String {
        (s == s.rounded() ? String(Int(s)) : String(s)) + " s"
    }
}

/// ⌘/: the keys in force, read-only.
struct ShortcutsView: View {
    @ObservedObject var keymap: Keymap
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openSettings) private var openSettings

    private static let fixed: [(String, String)] = [
        ("⌘O", "Open a folder (or a video or photo, to open its folder)"),
        ("⌘R / ⌘⇧R", "Reload the folder / reveal the clip in Finder"),
        ("⌘⏎", "Apply: review, then trash, crop, rotate and zoom everything staged"),
        ("⌘S", "Apply now, without the review (as the sheet's Overwrite setting was last left)"),
        ("⌘Z / ⌘⇧Z", "Undo / redo any staging"),
        ("Drag", "On the picture: zoom a video into that area, or crop a photo to it (⇧ for any shape)"),
        ("⌘= / ⌘-", "Bigger / smaller thumbnails"),
        ("⌘I", "Show / hide the notes from the folder's bulkcut.json"),
        ("⌘,", "Change the keys"),
    ]

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Keyboard Shortcuts").font(.title3.weight(.semibold))
            Text("Make them yours: Settings (⌘,), or \(Keymap.overrideURL.path).")
                .font(.callout).foregroundStyle(.secondary).textSelection(.enabled)
            ForEach(Keymap.overrideMessages, id: \.self) { m in
                Text(m).font(.caption).foregroundStyle(.orange)
            }
            ScrollView {
                Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 4) {
                    ForEach(Action.Group.allCases, id: \.self) { g in
                        GridRow {
                            Text(g.rawValue).font(.subheadline.weight(.semibold)).foregroundStyle(.secondary)
                                .padding(.top, 6).gridCellColumns(2)
                        }
                        ForEach(Action.allCases.filter { $0.group == g }) { a in
                            GridRow {
                                key(keymap.label(a))
                                Text(a.title + note(a)).font(.callout)
                            }
                        }
                    }
                    GridRow {
                        Text("App").font(.subheadline.weight(.semibold)).foregroundStyle(.secondary)
                            .padding(.top, 6).gridCellColumns(2)
                    }
                    ForEach(Self.fixed, id: \.0) { k, what in
                        GridRow { key(k); Text(what).font(.callout) }
                    }
                }
            }
            HStack {
                Button("Change Keys…") { dismiss(); openSettings() }
                Spacer()
                Button("Close") { dismiss() }.keyboardShortcut(.defaultAction)
            }
        }
        .padding(18)
        .frame(width: 560, height: 640)
    }

    private func note(_ a: Action) -> String {
        switch a {
        case .seekBack, .seekForward: " (\(SettingsView.seconds(keymap.seekStep)))"
        case .jumpBack, .jumpForward: " (\(SettingsView.seconds(keymap.jumpStep)))"
        case .speedUp, .speedDown: " (1× ↔ 1.5× ↔ 1.7× ↔ 2× ↔ 2.5× ↔ 3×, wrapping)"
        case .zoomIn, .zoomOut: " (around the playhead; scroll over it too)"
        default: ""
        }
    }

    private func key(_ k: String) -> some View {
        Text(k)
            .font(.system(.body, design: .monospaced).weight(.semibold))
            .padding(.horizontal, 6).padding(.vertical, 1)
            .background(Color.secondary.opacity(0.15))
            .clipShape(RoundedRectangle(cornerRadius: 4))
            .gridColumnAlignment(.trailing)
    }
}
