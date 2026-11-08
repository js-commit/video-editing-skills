import AVFoundation
import AppKit
import SwiftUI

struct PlayerView: NSViewRepresentable {
    let player: AVPlayer

    final class View: NSView {
        override var acceptsFirstResponder: Bool { false }
        override func makeBackingLayer() -> CALayer { AVPlayerLayer() }
    }

    func makeNSView(context: Context) -> View {
        let v = View()
        v.wantsLayer = true
        v.layer?.backgroundColor = NSColor.black.cgColor
        (v.layer as? AVPlayerLayer)?.player = player
        (v.layer as? AVPlayerLayer)?.videoGravity = .resizeAspect
        return v
    }

    func updateNSView(_ v: View, context: Context) {
        guard let layer = v.layer as? AVPlayerLayer, layer.player !== player else { return }
        layer.player = player
    }
}

struct ContentView: View {
    @ObservedObject var controller: ReviewController
    /// Deliberately not observed here: the playhead ticks many times a second
    /// (once per mouse event during a drag) and only `Transport` and `SeekBar`
    /// need to redraw for it, not the whole window.
    let player: PlayerModel
    @FocusState private var fieldFocus: Bool
    @State private var startTCText = ""
    @State private var startTCBad = false

    init(controller: ReviewController) {
        self.controller = controller
        self.player = controller.player
    }

    var body: some View {
        HSplitView {
            playerPane
                .frame(minWidth: 640, minHeight: 480)
            sidePanel
                .frame(minWidth: 300, idealWidth: 400, maxWidth: 900)
        }
        .frame(minWidth: 1000, minHeight: 600)
        .onDrop(of: [.fileURL], isTargeted: nil) { controller.handleDrop($0) }
        .onChange(of: controller.fieldFocused) { _, v in fieldFocus = v }
        .onChange(of: fieldFocus) { _, v in controller.fieldFocused = v }
        .onChange(of: controller.focusRequest) { _, _ in
            // Next run-loop turn: lets a just-enabled field accept focus.
            DispatchQueue.main.async { fieldFocus = true }
        }
        .onAppear {
            controller.installMonitor()
            controller.openFromArguments()
            controller.runKeyScriptFromEnvironment()
        }
        .toolbar { toolbarItems }
    }

    // MARK: left

    private var playerPane: some View {
        VStack(spacing: 8) {
            PlayerView(player: player.player)
                .background(Color.black)
                .layoutPriority(1)

            Transport(controller: controller, player: player)
                .padding(.horizontal, 12)

            if controller.changes != nil {
                ChangeBanner(controller: controller, player: player)
                    .padding(.horizontal, 12)
            }

            if let s = controller.store {
                SeekBar(controller: controller, player: player, store: s)
                    .overlay(alignment: .top) { BuildCachesPrompt(controller: controller) }
                    .padding(.horizontal, 12)
            } else {
                Capsule().fill(Color.secondary.opacity(0.15)).frame(height: 6)
                    .padding(.horizontal, 12).padding(.vertical, 9)
            }

            TextField("type or dictate a note, ⏎ stamps it at the playhead · ESC clears",
                      text: $controller.draftText)
                .textFieldStyle(.plain)
                .font(.system(size: 17))
                .padding(.horizontal, 10).padding(.vertical, 9)
                .background(Color(nsColor: .textBackgroundColor), in: RoundedRectangle(cornerRadius: 8))
                .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.secondary.opacity(0.35), lineWidth: 1))
                .focused($fieldFocus)
                .disabled(controller.store == nil)
                .padding(.horizontal, 12)
                .overlay(FocusPulse(on: fieldFocus).padding(.horizontal, 12))

            Text(controller.status)
                .font(.callout)
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 12)
                .padding(.bottom, 8)
        }
    }

    // MARK: right

    @ViewBuilder
    private var sidePanel: some View {
        if let store = controller.store {
            VSplitView {
                if let changes = controller.changes {
                    ChangesPane(controller: controller, list: changes)
                        .frame(minHeight: 140, idealHeight: 380)
                }
                TranscriptPane(controller: controller)
                    .frame(minHeight: 120, idealHeight: 420)
                NotesList(controller: controller, store: store)
                    .frame(minHeight: 120)
            }
        } else {
            VStack(spacing: 10) {
                Spacer()
                Text("No video").font(.title3).foregroundStyle(.secondary)
                Text("⌘O open · ⌘⇧O open the path on the clipboard\nFile › Open Recent · or drop a video here")
                    .font(.callout).foregroundStyle(.tertiary).multilineTextAlignment(.center)
                Spacer()
            }
        }
    }

    // MARK: toolbar

    @ToolbarContentBuilder
    private var toolbarItems: some ToolbarContent {
        ToolbarItem(placement: .navigation) {
            Button { controller.openPanel() } label: { Label("Open", systemImage: "folder") }
        }
        ToolbarItem(placement: .principal) {
            if let s = controller.store {
                Text(s.videoURL.lastPathComponent)
                    .font(.headline)
                    .lineLimit(1)
                    .truncationMode(.middle)
                    .frame(maxWidth: 480)
            }
        }
        ToolbarItem(placement: .primaryAction) {
            Button { controller.showShortcuts.toggle() } label: {
                Label("Keyboard Shortcuts", systemImage: "keyboard").labelStyle(.titleAndIcon)
            }
            .help("Keyboard shortcuts (⌘/)")
            .popover(isPresented: $controller.showShortcuts, arrowEdge: .bottom) { ShortcutsView() }
        }
        ToolbarItem(placement: .primaryAction) {
            if let s = controller.store {
                HStack(spacing: 6) {
                    Text("Start TC").foregroundStyle(.secondary)
                    TextField("00:00:00:00", text: $startTCText)
                        .font(.system(.body, design: .monospaced))
                        .textFieldStyle(.roundedBorder)
                        .frame(width: 120)
                        .foregroundStyle(startTCBad ? Color.red : Color.primary)
                        .onAppear { startTCText = s.startTimecode }
                        .onChange(of: s.startTimecode) { _, v in startTCText = v }
                        .onSubmit {
                            startTCBad = !controller.setStartTimecode(startTCText)
                            if !startTCBad { controller.focusField() }
                        }
                }
                .help("Timecode Resolve shows at the first frame of this file (read from the file's timecode track; edit if wrong)")
            }
        }
    }
}

/// Timecode, speed and play/pause: the one strip that redraws per playhead tick.
struct Transport: View {
    @ObservedObject var controller: ReviewController
    @ObservedObject var player: PlayerModel

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 16) {
            Text(controller.timecode(player.currentSeconds))
                .font(.system(size: 44, weight: .medium, design: .monospaced))
            Text(player.speedLabel)
                .font(.system(size: 22, weight: .semibold, design: .rounded))
                .padding(.horizontal, 10).padding(.vertical, 2)
                .background(player.speed > 1 ? Color.orange.opacity(0.85) : Color.secondary.opacity(0.25))
                .clipShape(Capsule())
            if let cuts = controller.cuts, let c = cuts.cut(at: player.currentSeconds) {
                Text("cut \(c.index)/\(cuts.cuts.count) · \(c.name)")
                    .font(.system(size: 13, weight: .medium, design: .monospaced))
                    .foregroundStyle(.secondary)
                    .lineLimit(1).truncationMode(.middle)
                    .help("The clip under the playhead, from \(cuts.project) / \(cuts.timeline) · \(Shortcuts.label(.previousCut)) / \(Shortcuts.label(.nextCut)): previous / next cut")
            }
            Spacer()
            Button(action: controller.togglePlay) {
                Image(systemName: player.isPlaying ? "pause.fill" : "play.fill")
            }
            .help("Space")
            .disabled(controller.store == nil)
        }
    }
}

/// The change under the playhead, one line: its number, title and what to watch
/// — or, between changes, the next one. A fixed height, so the video does not
/// jump as the playhead goes in and out of changes. A click plays it from just before.
struct ChangeBanner: View {
    @ObservedObject var controller: ReviewController
    @ObservedObject var player: PlayerModel

    var body: some View {
        let t = player.currentSeconds
        let list = controller.changes
        let here = list?.change(at: t)
        let next = list?.changes.first { $0.start > t }
        HStack(spacing: 10) {
            if let list {
                if let c = here {
                    ChangeNumber(number: list.number(of: c.id) ?? 0, seen: controller.seenChanges.contains(c.id), size: 22)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(c.title).font(.system(size: 14, weight: .semibold)).lineLimit(1)
                        if let w = c.watch {
                            Text("Watch: " + w).font(.system(size: 12)).foregroundStyle(.secondary).lineLimit(1)
                        }
                    }
                    .help([c.what, c.watch.map { "Watch: " + $0 }].compactMap { $0 }.joined(separator: "\n\n"))
                } else if let n = next {
                    Text("Between changes · next (\(Shortcuts.label(.nextChange))):").font(.system(size: 13)).foregroundStyle(.secondary)
                    ChangeNumber(number: list.number(of: n.id) ?? 0, seen: controller.seenChanges.contains(n.id), size: 18)
                    Text("\(n.title) at \(ReviewStore.mmss(n.start))").font(.system(size: 13, weight: .medium)).lineLimit(1)
                } else {
                    Text("Past the last change · \(Shortcuts.label(.previousChange)) goes back").font(.system(size: 13)).foregroundStyle(.secondary)
                }
                Spacer(minLength: 8)
                Text("\(controller.seenChanges.count) of \(list.changes.count) seen")
                    .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
            }
        }
        .padding(.horizontal, 10)
        .frame(height: 42)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.change.opacity(here != nil ? 0.16 : 0.05), in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.change.opacity(here != nil ? 0.65 : 0.2), lineWidth: 1))
        .contentShape(Rectangle())
        .onTapGesture { if let c = here ?? next { controller.jumpToChange(c.id) } }
    }
}

/// A change's number in a purple disc (a ✓ once it has been played through).
struct ChangeNumber: View {
    let number: Int
    let seen: Bool
    var size: CGFloat = 20

    var body: some View {
        ZStack {
            Circle().fill(Color.change.opacity(seen ? 0.4 : 1))
            Text(seen ? "✓" : "\(number)")
                .font(.system(size: size * 0.52, weight: .bold, design: .rounded))
                .foregroundStyle(.white)
        }
        .frame(width: size, height: size)
        .help(seen ? "Change \(number) · played through" : "Change \(number)")
    }
}

/// What changed since the previous cut: one row per change, in time order. A
/// click plays it from a second before; the row under the playhead is lit and
/// open (what was done, what to watch, the note it answers).
struct ChangesPane: View {
    @ObservedObject var controller: ReviewController
    let list: ChangeList

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 8) {
                Text("What changed").font(.headline)
                Badge(text: (list.previous.map { "\($0) → " } ?? "") + list.round, tint: .change)
                Text("\(controller.seenChanges.count) of \(list.changes.count) seen")
                    .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                Spacer()
                Text("\(Shortcuts.label(.previousChange)) / \(Shortcuts.label(.nextChange))").font(.system(.caption, design: .monospaced).weight(.semibold)).foregroundStyle(.secondary)
                    .help("Previous / next change, played from a second before it")
            }
            .padding(10)
            if let s = list.summary {
                Text(s).font(.system(size: controller.panelFontSize - 2)).foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 10).padding(.bottom, 8)
            }
            Divider()
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        ForEach(Array(list.changes.enumerated()), id: \.element.id) { i, c in
                            ChangeRow(controller: controller, change: c, number: i + 1).id(c.id)
                            Divider()
                        }
                    }
                }
                .onChange(of: controller.currentChangeID) { _, id in
                    if let id { withAnimation(.easeInOut(duration: 0.2)) { proxy.scrollTo(id, anchor: .center) } }
                }
                .onChange(of: controller.focusedChangeID) { _, id in
                    if let id { withAnimation(.easeInOut(duration: 0.2)) { proxy.scrollTo(id, anchor: .center) } }
                }
            }
        }
    }
}

struct ChangeRow: View {
    @ObservedObject var controller: ReviewController
    let change: Change
    let number: Int

    var body: some View {
        let fs = controller.panelFontSize
        let current = controller.currentChangeID == change.id
        let open = current || controller.focusedChangeID == change.id
        HStack(alignment: .top, spacing: 9) {
            ChangeNumber(number: number, seen: controller.seenChanges.contains(change.id))
                .padding(.top, 1)
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 6) {
                    Text(controller.timecode(change.start))
                        .font(.system(size: fs - 4, design: .monospaced)).foregroundStyle(.secondary)
                    if !change.isPoint {
                        Text(ReviewStore.mmss(change.end - change.start))
                            .font(.system(size: fs - 5, design: .monospaced)).foregroundStyle(.tertiary)
                    }
                    if let k = change.kind {
                        Text(k).font(.system(size: fs - 5, weight: .medium)).foregroundStyle(Color.change)
                            .padding(.horizontal, 5).padding(.vertical, 0.5)
                            .background(Color.change.opacity(0.12), in: Capsule())
                    }
                }
                Text(change.title).font(.system(size: fs, weight: .semibold))
                    .lineLimit(open ? nil : 1).truncationMode(.tail)
                if open {
                    if let w = change.what {
                        Text(w).font(.system(size: fs - 1)).fixedSize(horizontal: false, vertical: true)
                    }
                    if let w = change.watch {
                        (Text("Watch: ").bold() + Text(w)).font(.system(size: fs - 1)).foregroundStyle(Color.change)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    if let n = change.note {
                        Text("Your note: “\(n)”").font(.system(size: fs - 2)).italic().foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
        }
        .padding(.horizontal, 10).padding(.vertical, 7)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(current ? Color.change.opacity(0.15) : open ? Color.change.opacity(0.06) : Color.clear)
        .contentShape(Rectangle())
        .onTapGesture { controller.jumpToChange(change.id) }
        .help("Click: play it from a second before (\(Shortcuts.label(.previousChange)) / \(Shortcuts.label(.nextChange)) step through them)")
    }
}

/// A network file opens without its waveform and thumbnails (each is a read
/// over the network); this sits over the empty waveform and builds them on a click.
struct BuildCachesPrompt: View {
    let controller: ReviewController
    /// Mirrors player.cachesDeferred: observing the player itself would redraw
    /// this on every playhead tick (see ContentView.player).
    @State private var deferred = false

    var body: some View {
        VStack {
            if deferred {
                HStack(spacing: 8) {
                    Image(systemName: "network").foregroundStyle(.secondary)
                    Text("Network file: waveform and thumbnails aren't built automatically.")
                        .font(.caption).foregroundStyle(.secondary)
                    Button("Build") { controller.buildCaches() }
                        .controlSize(.small)
                        .help("Read the audio and a frame every 2 s over the network; kept in ~/Library/Caches for next time")
                }
                .padding(.horizontal, 10).padding(.vertical, 5)
                .background(.regularMaterial, in: Capsule())
                .padding(.top, 18)
            }
        }
        .onReceive(controller.player.$cachesDeferred) { deferred = $0 }
    }
}

struct TranscriptPane: View {
    @ObservedObject var controller: ReviewController
    @ObservedObject var transcriber: Transcriber

    init(controller: ReviewController) {
        self.controller = controller
        self.transcriber = controller.transcriber
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text("Transcript").font(.headline)
                if let t = controller.transcript {
                    Text("\(t.words.count) words").font(.caption).foregroundStyle(.secondary)
                    if let engine = t.engine {
                        Text(engine).font(.caption).foregroundStyle(.tertiary)
                            .help("The engine that made this transcript (tools/transcribe.py)")
                    }
                    if t.stale {
                        Badge(text: "stale · \(t.changeDetail ?? "file changed")", tint: .orange)
                            .help("The file changed length since this transcript was made; Re-transcribe redoes it")
                    } else if t.changed {
                        Badge(text: "re-exported · same length", tint: .green)
                            .help("The file was re-exported since this transcript was made, but its length is the same, so the words still line up")
                    }
                }
                Spacer()
                if transcriber.running {
                    ProgressView().controlSize(.small)
                    Text(transcriber.progress).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                    Button("Cancel") { transcriber.cancel() }.controlSize(.small)
                } else if let t = controller.transcript {
                    if t.stale && controller.canTranscribe {
                        Button("Re-transcribe") { controller.transcribe() }.controlSize(.small)
                            .help("Every time in this transcript is from an earlier cut. Transcribes again with tools/transcribe.py; the old transcript is kept with the previous cut's notes")
                    } else {
                        Text("click a word to seek").font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
            .padding(10)
            Divider()
            if controller.findOpen {
                FindBar(controller: controller)
                Divider()
            }
            if controller.transcript != nil {
                TranscriptView(transcript: controller.transcript, currentIndex: controller.currentWord,
                               fontSize: controller.panelFontSize,
                               foundRanges: controller.foundRanges, currentFound: controller.currentFound,
                               onSeek: { controller.seekFromTranscript(to: $0) })
            } else {
                VStack(spacing: 10) {
                    Spacer()
                    if transcriber.running {
                        Text("Transcribing… you can keep reviewing.").foregroundStyle(.secondary)
                    } else if controller.store != nil {
                        Text("No transcript next to this file.").foregroundStyle(.secondary)
                        if let note = controller.transcribeNote {
                            Text(note).font(.caption).foregroundStyle(.orange).multilineTextAlignment(.center)
                        }
                        if controller.canTranscribe {
                            Button("Transcribe") { controller.transcribe() }
                                .buttonStyle(.borderedProminent)
                                .help("Write <stem>.transcript.json next to the video")
                        }
                        Text(controller.transcriberFound
                             ? "Runs the repo's tools/transcribe.py with your chosen engine. Review › Transcribe When a Video Opens does it automatically."
                             : Transcriber.Failure.notInstalled.description)
                            .font(.caption).foregroundStyle(.secondary)
                            .multilineTextAlignment(.center)
                    }
                    Spacer()
                }
                .padding(.horizontal, 16)
                .frame(maxWidth: .infinity)
            }
        }
    }
}

/// ⌘F: find in the transcript. ⏎ / ⇧⏎ (or ⌘G / ⇧⌘G) go to the next /
/// previous hit and take the playhead there; ESC closes it.
struct FindBar: View {
    @ObservedObject var controller: ReviewController
    @FocusState private var focused: Bool

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: "magnifyingglass").foregroundStyle(.secondary)
            TextField("Find in transcript", text: $controller.findText)
                .textFieldStyle(.plain)
                .focused($focused)
            Text(count).font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                .help(controller.found.fuzzy ? "No exact match: these are near matches (a letter or two off)" : "")
            Button { controller.findNext(-1) } label: { Image(systemName: "chevron.up") }
                .buttonStyle(.borderless).disabled(controller.found.matches.isEmpty)
                .help("Previous match (⇧⏎ or ⇧⌘G)")
            Button { controller.findNext(1) } label: { Image(systemName: "chevron.down") }
                .buttonStyle(.borderless).disabled(controller.found.matches.isEmpty)
                .help("Next match (⏎ or ⌘G)")
            Button { controller.closeFind() } label: { Image(systemName: "xmark.circle.fill").foregroundStyle(.secondary) }
                .buttonStyle(.borderless)
                .help("Close (ESC)")
        }
        .padding(.horizontal, 10).padding(.vertical, 6)
        .onAppear { DispatchQueue.main.async { focused = true } }
        .onChange(of: controller.findFocusRequest) { _, _ in DispatchQueue.main.async { focused = true } }
        .onChange(of: focused) { _, v in controller.findFieldFocused = v }
        .onDisappear { controller.findFieldFocused = false }
    }

    private var count: String {
        guard TranscriptSearch.searchable(controller.findText) else { return "" }
        guard controller.transcript != nil else { return "no transcript" }
        let n = controller.found.matches.count
        guard n > 0, let i = controller.currentFound else { return "no match" }
        return "\(controller.found.fuzzy ? "≈ " : "")\(i + 1) of \(n)"
    }
}

struct NotesList: View {
    @ObservedObject var controller: ReviewController
    @ObservedObject var store: ReviewStore
    @State private var showArchived = false
    @State private var showPrevious = false

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 8) {
                Text("\(store.notes.count) note\(store.notes.count == 1 ? "" : "s")").font(.headline)
                if let c = store.lengthChange {
                    Badge(text: "new cut \(ReviewStore.mmss(c.from)) → \(ReviewStore.mmss(c.to)) · \(c.kept) kept", tint: .orange)
                        .help("This is a different cut from the one these notes were made on, so their times no longer line up: they are kept under Previous cut, where a click still jumps near them and ↩ brings one back")
                } else if store.reexportedSameLength {
                    Badge(text: "re-exported · same length · notes kept", tint: .green)
                        .help("The file was overwritten since the last open, but its length is the same, so the notes still line up")
                } else if !store.loadedFromDisk {
                    Badge(text: "new", tint: .secondary)
                }
                if !store.archived.isEmpty {
                    Button(showArchived ? "Hide archived" : "Archived (\(store.archived.count))") { showArchived.toggle() }
                        .controlSize(.small)
                        .help("Notes you archived by hand: dealt with. They stay in notes.json but are left out of the export")
                }
                if store.previousNoteCount > 0 {
                    Button(showPrevious ? "Hide previous cut" : "Previous cut (\(store.previousNoteCount))") { showPrevious.toggle() }
                        .controlSize(.small)
                        .foregroundStyle(.secondary)
                        .help("Notes from earlier cuts of this file. Their times are adrift, so they are out of the way and out of the export — but a click still jumps near where the note was, and ↩ brings one back to this cut")
                }
                Spacer()
                Button("Archive") { controller.archiveSelected() }
                    .controlSize(.small)
                    .disabled(controller.selection.isEmpty)
                    .help("Archive the selected notes (\(Shortcuts.label(.archiveNotes))): kept below, hidden from the export")
                Button { controller.copyNotesJSON() } label: { Label("Copy JSON", systemImage: "doc.on.doc") }
                    .controlSize(.small)
                    .disabled(store.notes.isEmpty)
                    .help("Copy the live notes to the clipboard as JSON (⌘⇧C): time, timecode, seconds, text — archived and previous-cut notes left out")
                Text("⇧click / \(Shortcuts.label(.selectAllNotes)): select more · \(Shortcuts.label(.archiveNotes)): archive · \(Shortcuts.label(.deleteNote)): delete · \(Shortcuts.label(.undo)): undo")
                    .font(.caption).foregroundStyle(.secondary)
            }
            .padding(10)
            Divider()
            List(selection: Binding(get: { controller.selection },
                                    set: { controller.setSelection($0) })) {
                ForEach(store.notes) { note in
                    NoteRow(controller: controller, store: store, note: note)
                        .tag(note.id)
                }
                if showArchived, !store.archived.isEmpty {
                    Section("Archived — dealt with, not exported") {
                        ForEach(store.archived) { note in
                            ArchivedRow(controller: controller, note: note)
                                .tag(note.id)
                        }
                    }
                }
                if showPrevious {
                    ForEach(store.versions) { version in
                        if !version.notes.isEmpty {
                            Section(sectionTitle(version)) {
                                ForEach(version.notes) { note in
                                    PreviousRow(controller: controller, note: note)
                                        .tag(note.id)
                                }
                            }
                        }
                    }
                }
            }
            .listStyle(.inset)
        }
    }

    /// "Previous cut · 12:16.8 · 8 notes · 5 dealt with — times are approximate"
    private func sectionTitle(_ v: NoteVersion) -> String {
        let n = v.notes.count
        var t = "Previous cut · \(v.label) · \(n) note\(n == 1 ? "" : "s")"
        if v.doneCount == n { t += " · dealt with" }
        else if v.doneCount > 0 { t += " · \(v.doneCount) dealt with" }
        return t + " — times are approximate"
    }
}

struct ArchivedRow: View {
    @ObservedObject var controller: ReviewController
    let note: Note

    var body: some View {
        let fs = controller.panelFontSize
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Text(controller.timecode(note.seconds))
                .font(.system(size: fs - 2, design: .monospaced))
            Text(note.text)
                .font(.system(size: fs))
                .lineLimit(controller.selectedID == note.id ? nil : 1)
                .frame(maxWidth: .infinity, alignment: .leading)
            Button { controller.restoreNote(note.id) } label: {
                Image(systemName: "arrow.uturn.backward")
            }
            .buttonStyle(.borderless)
            .help("Restore to the live notes")
        }
        .foregroundStyle(.secondary)
        .padding(.vertical, 2)
        .help(note.archivedReason ?? "archived")
    }
}

/// A note from a cut that no longer exists: dimmed, its timecode marked
/// approximate. Clicking it still seeks (roughly where the note was, which
/// is close enough to watch what became of it); ↩ or the button brings it
/// back to this cut.
struct PreviousRow: View {
    @ObservedObject var controller: ReviewController
    let note: Note

    var body: some View {
        let fs = controller.panelFontSize
        let done = note.archivedAt != nil
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Text((done ? "✓ ≈ " : "≈ ") + controller.timecode(note.seconds))
                .font(.system(size: fs - 2, design: .monospaced))
                .help(done ? "Archived during that pass: dealt with" : "Still open when the cut changed")
            Text(note.text)
                .font(.system(size: fs))
                .lineLimit(controller.selectedID == note.id ? nil : 1)
                .frame(maxWidth: .infinity, alignment: .leading)
            Button { controller.bringBackNote(note.id) } label: {
                Image(systemName: "arrow.uturn.backward")
            }
            .buttonStyle(.borderless)
            .help("Bring this note back to the current cut (↩); its time comes with it, nudge it with \(Shortcuts.label(.seekBack)) / \(Shortcuts.label(.seekForward))")
        }
        .foregroundStyle(.tertiary)
        .padding(.vertical, 2)
        .help("From an earlier cut of this file — the time is approximate")
    }
}

struct NoteRow: View {
    @ObservedObject var controller: ReviewController
    @ObservedObject var store: ReviewStore
    let note: Note

    var body: some View {
        let selected = controller.selectedID == note.id
        let fs = controller.panelFontSize
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Text(controller.timecode(note.seconds))
                .font(.system(size: fs - 2, design: .monospaced))
            if selected {
                // Selected: the whole text, wrapped and editable. ⏎ or ESC
                // hands focus back to the note field (⌥⏎ inserts a line break).
                TextField("", text: Binding(get: { store.note(note.id)?.text ?? "" },
                                            set: { store.setText(note.id, $0) }), axis: .vertical)
                    .textFieldStyle(.plain)
                    .font(.system(size: fs))
                    .lineLimit(1...12)
                    .onSubmit { controller.focusField() }
            } else {
                Text(store.note(note.id)?.text ?? "")
                    .font(.system(size: fs))
                    .lineLimit(1)
                    .truncationMode(.tail)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            Spacer(minLength: 0)
            Button { controller.deleteNote(note.id) } label: {
                Image(systemName: "trash")
            }
            .buttonStyle(.borderless)
            .help("Delete (⌫)")
        }
        .padding(.vertical, 2)
    }
}

/// A breathing accent-coloured ring around the note field while it has
/// keyboard focus: "whatever you type or dictate lands here".
struct FocusPulse: View {
    let on: Bool
    @State private var bright = false

    private let glow = Color(red: 1, green: 0.18, blue: 0.18)

    var body: some View {
        RoundedRectangle(cornerRadius: 8)
            .stroke(glow.opacity(on ? (bright ? 1 : 0.45) : 0), lineWidth: bright ? 3 : 2)
            .shadow(color: glow.opacity(on ? (bright ? 0.7 : 0.2) : 0), radius: bright ? 12 : 5)
            .allowsHitTesting(false)
            .onAppear { restart() }
            .onChange(of: on) { _, _ in restart() }
    }

    private func restart() {
        bright = false
        guard on else { return }
        withAnimation(.easeInOut(duration: 1.2).repeatForever(autoreverses: true)) { bright = true }
    }
}

/// A small tinted capsule for the state of the notes / transcript vs. the file.
struct Badge: View {
    let text: String
    let tint: Color

    var body: some View {
        Text(text)
            .font(.caption.weight(.medium))
            .foregroundStyle(tint)
            .padding(.horizontal, 7).padding(.vertical, 2)
            .background(tint.opacity(0.14), in: Capsule())
            .lineLimit(1)
    }
}
