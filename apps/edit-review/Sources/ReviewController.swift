import AppKit
import Combine
import Foundation
import UniformTypeIdentifiers

/// The keyboard state machine: one video, the note field always ready.
///
/// SPACE only ever plays / pauses. A note exists once you type (or dictate)
/// something into the field and press ⏎: it is stamped with the playhead time
/// at that moment. Pausing and resuming leaves nothing behind.
@MainActor
final class ReviewController: ObservableObject {
    let player = PlayerModel()
    let transcriber = Transcriber()

    @Published private(set) var store: ReviewStore?
    @Published var showShortcuts = false
    /// Notes highlighted in the list (⇧-click / ⌘-click / ⌘A extend it).
    @Published var selection = Set<String>()
    /// The one selected note, when exactly one is: arrows move it, it expands in the list.
    var selectedID: String? { selection.count == 1 ? selection.first : nil }
    @Published var fieldFocused = false
    @Published private(set) var focusRequest = 0
    @Published var status = "Open a video (⌘O) or drop one here."
    @Published var draftText = ""
    @Published private(set) var transcript: Transcript?
    @Published private(set) var currentWord: Int?

    /// ⌘F: the find bar over the transcript (see TranscriptSearch).
    @Published private(set) var findOpen = false
    @Published var findText = "" { didSet { if findText != oldValue { runFind() } } }
    @Published private(set) var found = TranscriptSearch.Result()
    @Published private(set) var foundRanges: [NSRange] = []
    @Published private(set) var currentFound: Int?
    @Published private(set) var findFocusRequest = 0
    /// Mirrored from the find field's focus (TranscriptPane).
    var findFieldFocused = false
    /// Typing lands on the first hit from here: the playhead when ⌘F was
    /// pressed, then wherever the last hit visited was.
    private var findAnchor: Double = 0
    private var findSeekTask: Task<Void, Never>?
    private var visitedFound: Int?
    /// tools/transcribe.py was found (checked on each open, not on every redraw).
    @Published private(set) var transcriberFound = false
    /// Why this file has no transcript after a run (no speech, no audio
    /// track, a read-only card); the transcript pane shows it.
    @Published private(set) var transcribeNote: String?
    @Published private(set) var recents: [URL] = NSDocumentController.shared.recentDocumentURLs
    /// Where the picture changes in this file, from `<stem>.review/cuts.json`
    /// (written by the draft export, or Review › Get Cuts from Resolve). nil: none.
    @Published private(set) var cuts: CutList?
    @Published private(set) var pullingCuts = false
    /// What changed since the previous cut, from `<stem>.review/changes.json`
    /// (the editing pipeline writes it with the draft). nil: none.
    @Published private(set) var changes: ChangeList?
    /// The change under the playhead (its pre-roll not counted).
    @Published private(set) var currentChangeID: String?
    /// The change last jumped to or clicked: its row stays open, ⌥↑ / ⌥↓ step from it.
    @Published private(set) var focusedChangeID: String?
    /// Changes played through to their end, remembered per file and round.
    @Published private(set) var seenChanges = Set<String>()
    private var seenKey: String?
    private var lastTick: Double = 0

    /// Timeline zoom: the length in seconds of the window the waveform and
    /// seek bar show, or nil for the whole file. ⌃E halves it, ⌃W doubles it,
    /// the scroll wheel over the timeline zooms around the pointer.
    @Published private(set) var zoomWindow: Double?
    /// Left edge of that window in seconds. Follows the playhead when it runs
    /// off either end (paging like a DAW, not a smooth scroll).
    @Published private(set) var viewStart: Double = 0

    /// Transcribe a video without a transcript as soon as it opens (Review menu;
    /// off by default, since the user's engine may be a paid cloud service).
    @Published var autoTranscribe: Bool = UserDefaults.standard.bool(forKey: "autoTranscribe") {
        didSet { UserDefaults.standard.set(autoTranscribe, forKey: "autoTranscribe") }
    }

    /// Point size of the transcript and notes text (View › Text Size); persisted.
    @Published var panelFontSize: Double = UserDefaults.standard.object(forKey: "panelFontSize") as? Double ?? 16 {
        didSet { UserDefaults.standard.set(panelFontSize, forKey: "panelFontSize") }
    }
    static let fontSizes: [Double] = [13, 14, 16, 18, 20, 22, 24, 28]

    private var monitor: Any?
    private var scrollMonitor: Any?
    /// Where the pointer is over the timeline (fraction across, width in
    /// points), nil when it is elsewhere; the seek bar keeps it up to date.
    var timelineHover: (fraction: Double, width: Double)?
    /// The user scrolled the playhead out of the window: playback stops paging
    /// the window back until the playhead is in view again.
    private var scrolledAway = false
    private var startFrames = 0
    private var cancellables = Set<AnyCancellable>()
    private static let lastDirectoryKey = "lastOpenDirectory"

    init() {
        player.$currentSeconds
            .sink { [weak self] t in
                guard let self else { return }
                if player.isScrubbing { followTranscriptThrottled() } else { followTranscript(at: t) }
                trackChanges(at: t)
            }
            .store(in: &cancellables)
    }

    /// While the seek bar is being dragged the playhead moves once per mouse
    /// event; re-highlighting and scrolling the transcript that often is the
    /// main-thread cost that made the drag choppy. Follow at ~8 Hz instead and
    /// land exactly when the drag ends.
    private var followTask: Task<Void, Never>?
    private func followTranscriptThrottled() {
        guard followTask == nil else { return }
        followTask = Task { @MainActor [weak self] in
            try? await Task.sleep(for: .milliseconds(120))
            guard let self else { return }
            followTask = nil
            followTranscript(at: player.currentSeconds)
        }
    }

    var fps: Double { store?.fps ?? player.fps }

    func adjustFontSize(by delta: Double) {
        panelFontSize = min(max(panelFontSize + delta, Self.fontSizes.first!), Self.fontSizes.last!)
    }
    var hasDraft: Bool { !draftText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }

    func timecode(_ seconds: Double) -> String {
        Timecode.string(seconds: seconds, fps: fps, startFrames: startFrames)
    }

    var playheadTimecode: String { timecode(player.currentSeconds) }

    // MARK: opening

    /// Where the last video came from; the open panel starts there.
    var lastDirectory: URL? {
        UserDefaults.standard.url(forKey: Self.lastDirectoryKey)
    }

    func openPanel() {
        let p = NSOpenPanel()
        p.allowedContentTypes = [.movie, .mpeg4Movie, .quickTimeMovie, .video]
        p.allowsMultipleSelection = false
        p.message = "Choose a Resolve export to review (⌘⇧G or paste a path to jump to a folder)"
        p.directoryURL = lastDirectory
        if p.runModal() == .OK, let url = p.url { open(url: url) }
    }

    /// Launch argument, else the open panel straight away — the usual first
    /// action anyway.
    func openFromArguments() {
        let args = CommandLine.arguments.dropFirst().filter { !$0.hasPrefix("-") }
        if let path = args.first {
            open(url: URL(fileURLWithPath: (path as NSString).expandingTildeInPath))
        } else if AppDelegate.pendingOpen == nil, ProcessInfo.processInfo.environment["EDIT_REVIEW_KEYS"] == nil {
            Task { @MainActor in
                try? await Task.sleep(for: .milliseconds(300))
                if store == nil { openPanel() }
            }
        }
    }

    /// ⌘⇧O: the clipboard holds a path (Finder ⌥⌘C, a terminal, a file URL) — open it.
    func openFromClipboard() {
        guard let url = clipboardFileURL() else {
            status = "Clipboard does not hold a path to an existing file"
            NSSound.beep()
            return
        }
        open(url: url)
    }

    /// ⌘⇧C / the Copy JSON button: the live notes as JSON on the clipboard —
    /// the quick way to hand a pass to a chat or a script without hunting
    /// for notes.json. Archived and previous-cut notes are left out, like the export.
    func copyNotesJSON() {
        guard let s = store else { status = "Open a video first"; NSSound.beep(); return }
        struct Out: Encodable {
            struct N: Encodable {
                let time: String; let timecode: String; let seconds: Double; let text: String
                let cut: Int?; let clip: String?; let clip_offset_s: Double?
                let change: String?; let change_title: String?
            }
            let video: String
            let frame_rate: Double
            let start_timecode: String
            let timeline: String?
            let changes_round: String?
            let notes: [N]
        }
        let out = Out(video: s.videoURL.path, frame_rate: s.fps, start_timecode: s.startTimecode,
                      timeline: cuts.map { "\($0.project) / \($0.timeline)" },
                      changes_round: changes?.round,
                      notes: s.notes.map { n in
                          let c = cuts?.cut(at: n.seconds)
                          let ch = changes?.change(near: n.seconds)
                          return .init(time: ReviewStore.mmss(n.seconds), timecode: timecode(n.seconds),
                                       seconds: (n.seconds * 10).rounded() / 10, text: n.text,
                                       cut: c?.index, clip: c?.name,
                                       clip_offset_s: c.map { ((n.seconds - $0.start) * 100).rounded() / 100 },
                                       change: ch?.id, change_title: ch?.title)
                      })
        let enc = JSONEncoder(); enc.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        guard let data = try? enc.encode(out), let json = String(data: data, encoding: .utf8) else { return }
        let pb = NSPasteboard.general
        pb.clearContents()
        pb.setString(json, forType: .string)
        status = "Copied \(s.notes.count) note\(s.notes.count == 1 ? "" : "s") as JSON"
    }

    /// A path to an existing file on the clipboard (Finder ⌥⌘C, a terminal, a file URL), if any.
    private func clipboardFileURL() -> URL? {
        let pb = NSPasteboard.general
        var url: URL?
        if let u = (pb.readObjects(forClasses: [NSURL.self]) as? [URL])?.first, u.isFileURL {
            url = u
        } else if var text = pb.string(forType: .string)?.trimmingCharacters(in: .whitespacesAndNewlines) {
            if text.hasPrefix("file://"), let u = URL(string: text) { text = u.path }
            if text.count >= 2, text.hasPrefix("'"), text.hasSuffix("'") { text = String(text.dropFirst().dropLast()) }
            text = text.replacingOccurrences(of: "\\ ", with: " ")
            url = URL(fileURLWithPath: (text as NSString).expandingTildeInPath)
        }
        guard let url, FileManager.default.fileExists(atPath: url.path) else { return nil }
        return url
    }

    func clearRecents() {
        NSDocumentController.shared.clearRecentDocuments(nil)
        recents = []
    }

    func open(url: URL) {
        Task { await load(url: url) }
    }

    private func load(url: URL) async {
        draftText = ""
        transcribeNote = nil
        findOpen = false
        findText = ""
        status = "Loading \(url.lastPathComponent)…"
        log("loading \(url.path)")
        do {
            let info = try await player.load(url: url)
            log("loaded fps=\(info.fps) duration=\(info.duration) startTC=\(info.startTimecode)")
            let bytes = ((try? FileManager.default.attributesOfItem(atPath: url.path))?[.size] as? Int) ?? 0
            let s = ReviewStore(videoURL: url, fps: info.fps, fileStartTimecode: info.startTimecode,
                                duration: info.duration, bytes: bytes)
            store = s
            selection = []
            zoomWindow = nil
            viewStart = 0
            let cutsNote = loadCuts(for: url, duration: info.duration)
            let changesNote = loadChanges(for: url, duration: info.duration)
            applyStartTimecode(s.startTimecode)
            let n = s.notes.count
            status = "\(url.lastPathComponent) · \(fmt(info.fps)) fps · \(n) note\(n == 1 ? "" : "s")"
            + (s.loadedFromDisk ? " reloaded" : "")
            if let c = s.lengthChange {
                log("new cut: length \(c.from) → \(c.to), \(c.kept) notes moved to the previous cut")
                if c.kept > 0 {
                    status = "New cut (\(ReviewStore.mmss(c.from)) → \(ReviewStore.mmss(c.to))): \(c.kept) note\(c.kept == 1 ? "" : "s") kept under Previous cut — click one to jump near it, ↩ brings it back"
                }
            } else if s.reexportedSameLength {
                log("file re-exported, same length: notes kept")
                status += " · re-exported, same length: notes kept"
            }
            if let cutsNote { status += " · " + cutsNote }
            if let changesNote { status += " · " + changesNote }
            // Testing: EDIT_REVIEW_ZOOM=<seconds across the bar> opens zoomed in at the start.
            if let z = ProcessInfo.processInfo.environment["EDIT_REVIEW_ZOOM"].flatMap(Double.init),
               z >= Self.minZoomWindow, z < info.duration {
                zoomWindow = z
            }
            NSDocumentController.shared.noteNewRecentDocumentURL(url)
            recents = NSDocumentController.shared.recentDocumentURLs
            UserDefaults.standard.set(url.deletingLastPathComponent(), forKey: Self.lastDirectoryKey)
            focusField()
            if let staleNote = loadTranscript() { status += " · " + staleNote }
            if transcript == nil || transcript?.stale == true, shouldAutoTranscribe(url) {
                transcribe(auto: true)
            }
        } catch {
            status = "Could not open \(url.lastPathComponent): \(error.localizedDescription)"
            log("open failed: \(error)")
        }
    }

    /// stderr diagnostics (visible when the binary is run from a terminal).
    func log(_ msg: String) {
        FileHandle.standardError.write(("edit-review: " + msg + "\n").data(using: .utf8)!)
    }

    private func fmt(_ fps: Double) -> String {
        fps == fps.rounded() ? String(Int(fps)) : String(fps)
    }

    /// Start-timecode setting. Returns false (and leaves things alone) if the
    /// text is not a valid HH:MM:SS:FF.
    @discardableResult
    func setStartTimecode(_ text: String) -> Bool {
        guard let s = store, let frames = Timecode.parse(text, fps: s.fps) else { return false }
        s.startTimecode = Timecode.string(frames: frames, fps: s.fps)
        startFrames = frames
        objectWillChange.send()
        loadTranscript()                    // paragraph timecodes carry the offset
        return true
    }

    // MARK: transcript

    var sidecarURL: URL? { store.map { Transcript.sidecarURL(for: $0.videoURL) } }
    /// The one rule for the transcript pane's buttons and the Review menu item.
    var canTranscribe: Bool {
        store != nil && transcriberFound && !transcriber.running && (transcript == nil || transcript?.changed == true)
    }

    /// Read `<stem>.transcript.json` next to the video. Without one (or with a
    /// stale one) nothing pops up: the transcript pane offers a Transcribe /
    /// Re-transcribe button. Returns a few words for the status line when the
    /// transcript is from another cut.
    @discardableResult
    func loadTranscript() -> String? {
        transcriberFound = Transcriber.executable() != nil
        guard let s = store else { transcript = nil; currentWord = nil; return nil }
        transcript = Transcript.load(for: s.videoURL, duration: player.duration) { [weak self] in self?.timecode($0) ?? "" }
        currentWord = nil
        runFind(seek: false)
        followTranscript(at: player.currentSeconds)
        if let t = transcript {
            log("transcript: \(t.words.count) words (\(t.engine ?? "engine not named"))" + (t.stale ? " (STALE: \(t.changeDetail ?? "file changed"))" : t.changed ? " (file re-exported, same length: keeping)" : ""))
            if t.stale {
                return "transcript is from a different version of this file (\(t.changeDetail ?? "changed")) — Re-transcribe in the transcript pane"
            }
        }
        return nil
    }

    /// No transcript, or one from another cut: transcribe straight away when
    /// Review › Transcribe When a Video Opens is on (off by default). A network
    /// file waits for the Transcribe button, like its caches: every read is over
    /// the network. A file an earlier auto-run failed on is not retried until it
    /// changes (the pane says why; the button still works).
    /// EDIT_REVIEW_AUTO_TRANSCRIBE=yes / no forces it on / off.
    private func shouldAutoTranscribe(_ url: URL) -> Bool {
        let env = ProcessInfo.processInfo.environment["EDIT_REVIEW_AUTO_TRANSCRIBE"]
        if env == "no" || (env != "yes" && (!autoTranscribe || !MediaCache.isLocal(url))) { return false }
        if let skip = MediaCache.load(AutoTranscribeSkip.self, from: Self.skipURL(url)),
           skip.stamp == AutoTranscribeSkip.stamp(url) {
            transcribeNote = skip.why
            log("auto-transcribe skipped, failed before on this file: \(skip.why)")
            return false
        }
        return true
    }

    private struct AutoTranscribeSkip: Codable, Sendable {
        let stamp: [Int]                // size, mtime
        let why: String
        static func stamp(_ url: URL) -> [Int] {
            let a = (try? FileManager.default.attributesOfItem(atPath: url.path)) ?? [:]
            return [(a[.size] as? Int) ?? 0, Int((a[.modificationDate] as? Date)?.timeIntervalSince1970 ?? 0)]
        }
    }
    private static func skipURL(_ video: URL) -> URL {
        MediaCache.dir(for: video).appendingPathComponent("transcribe-skip.plist")
    }

    /// `auto`: started by opening the file, so the status line keeps what the
    /// open said (notes reloaded, new cut); a failure only shows in the pane.
    func transcribe(auto: Bool = false) {
        defer { if !auto { focusField() } }     // an auto-run never takes the keys from a field in use
        guard let s = store, !transcriber.running else { return }
        let video = s.videoURL
        // A transcript of a cut that is gone belongs with that cut's notes,
        // not next to the new file: park it before transcribing again, so the
        // script makes a fresh one instead of reusing the stale one.
        if let t = transcript, t.stale {
            if let parked = s.snapshotTranscript(Transcript.sidecarURL(for: video), duration: t.sourceDuration) {
                log("previous cut's transcript → \(parked.path)")
            }
            transcript = nil
            currentWord = nil
        }
        if !auto { status = "Transcribing \(video.lastPathComponent)…" }
        Task { @MainActor in
            let result = await transcriber.run(video: video)
            if auto, case .failure(let f) = result, case .exit(let code, _) = f, code != 4 {
                MediaCache.save(AutoTranscribeSkip(stamp: AutoTranscribeSkip.stamp(video), why: f.note),
                                to: Self.skipURL(video))
            }
            guard let current = store?.videoURL, current == video else {
                // Another file opened while this one ran (its sidecar is still
                // written beside it): that one gets its turn now.
                if let current = store?.videoURL, transcript == nil || transcript?.stale == true,
                   shouldAutoTranscribe(current) {
                    transcribe(auto: true)
                }
                return
            }
            switch result {
            case .success(let sidecar):
                log("transcribed → \(sidecar.path)")
                loadTranscript()
                if !auto || transcript == nil {
                    status = transcript.map { "Transcript ready: \($0.words.count) words" } ?? "transcribe.py finished but the sidecar has no words"
                }
            case .failure(let f):
                log("transcription failed: \(f)")
                transcribeNote = f.note
                if !auto { status = "Transcription failed: \(f.description)" }
            }
        }
    }

    // MARK: find (⌘F)

    /// ⌘F: open the find bar, or put the cursor back in it.
    func openFind() {
        guard store != nil else { return }
        if !findOpen {
            findOpen = true
            findAnchor = player.currentSeconds
        }
        findFocusRequest &+= 1
        if transcript == nil { status = transcriber.running ? "Transcribing… find works once the transcript is in" : "No transcript to search yet" }
    }

    /// ESC, or the bar's close button: highlights go, the note field gets the keys back.
    func closeFind() {
        findOpen = false
        findText = ""
        focusField()
    }

    /// Match the transcript against the find text. While typing, the first
    /// hit at or after the anchor becomes current and the playhead follows
    /// it once typing pauses.
    private func runFind(seek: Bool = true) {
        findSeekTask?.cancel()
        visitedFound = nil
        guard findOpen, let t = transcript else {
            found = .init(); foundRanges = []; currentFound = nil
            return
        }
        found = t.search.find(findText)
        foundRanges = found.matches.map { t.range(of: $0) }
        guard !found.matches.isEmpty else { currentFound = nil; return }
        let i = found.matches.firstIndex { t.words[$0.lowerBound].start >= findAnchor - 0.05 } ?? 0
        currentFound = i
        guard seek else { return }
        findSeekTask = Task { @MainActor [weak self] in
            try? await Task.sleep(for: .milliseconds(250))
            guard !Task.isCancelled, let self, currentFound == i else { return }
            goToFound(i)
        }
    }

    /// ⏎ / ⌘G (+⇧ backwards), or the bar's arrows: the next hit, wrapping round.
    func findNext(_ direction: Int) {
        guard findOpen, !found.matches.isEmpty else {
            if findOpen { NSSound.beep() } else { openFind() }
            return
        }
        findSeekTask?.cancel()
        let n = found.matches.count
        // Until the playhead has been taken to the current hit, ⏎ goes to it
        // rather than past it.
        let cur = currentFound ?? 0
        let i = visitedFound == cur || direction < 0 ? ((cur + (direction < 0 ? -1 : 1)) % n + n) % n : cur
        goToFound(i)
    }

    private func goToFound(_ i: Int) {
        guard let t = transcript, found.matches.indices.contains(i) else { return }
        currentFound = i
        visitedFound = i
        let s = t.words[found.matches[i].lowerBound].start
        findAnchor = s
        player.seek(to: s)
        selection = []
        status = "“\(findText.trimmingCharacters(in: .whitespaces))” \(i + 1) of \(found.matches.count)"
            + (found.fuzzy ? " (near matches)" : "") + " at \(timecode(s))"
    }

    /// The Build button over a network file's empty waveform.
    func buildCaches() {
        player.buildCaches()
        focusField()
    }

    private func followTranscript(at seconds: Double) {
        guard let t = transcript else { return }
        let i = t.index(at: seconds)
        if i != currentWord { currentWord = i }
    }

    /// Seek-bar drag: follow the pointer, keep playing if we were.
    func scrub(to seconds: Double) {
        player.scrub(to: seconds)
    }

    func scrubEnded(at seconds: Double) {
        player.endScrub(at: seconds)
        followTask?.cancel()
        followTask = nil
        followTranscript(at: player.currentSeconds)
        selection = []
        focusField()
    }

    /// A click on a transcript word: go there, keep playing if we were.
    func seekFromTranscript(to seconds: Double) {
        player.seek(to: seconds)
        selection = []
        focusField()
    }

    private func applyStartTimecode(_ text: String) {
        startFrames = Timecode.parse(text, fps: fps) ?? 0
    }

    // MARK: transport

    func togglePlay() {
        guard store != nil else { return }
        if player.isPlaying { pause() } else { play() }
    }

    func play() {
        selection = []              // arrows go back to seeking the playhead
        player.play()
        focusField()
    }

    func pause() {
        player.pause()
        focusField()
    }

    /// The note field is the home for keyboard focus: pausing, resuming,
    /// clicking a note or finishing an inline edit all land back in it.
    func focusField() {
        fieldFocused = true
        focusRequest &+= 1          // fires even when fieldFocused was already true
    }

    /// Put whatever the field holds where the playhead is, then carry on.
    func addNote() {
        guard let s = store else { return }
        let text = draftText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        let note = Note(id: UUID().uuidString, seconds: player.currentSeconds, text: text,
                        createdAt: ISO8601DateFormatter().string(from: Date()))
        s.add(note)
        draftText = ""
        status = "Note at \(timecode(note.seconds)) saved"
        play()
    }

    func clearDraft() {
        guard hasDraft || !draftText.isEmpty else { return }
        draftText = ""
        status = "Cleared"
    }

    // MARK: notes

    /// The list's selection changed (click, ⇧-click, ⌘-click). A single note
    /// pauses and jumps there; a range just highlights.
    func setSelection(_ ids: Set<String>) {
        selection = ids
        if ids.count == 1, let id = ids.first, let s = store, let n = s.anyNote(id) {
            player.pause()
            player.seek(to: n.seconds)
            if let v = s.versionNote(id)?.version {
                let drift = v.videoDuration.map { $0 - s.videoDuration } ?? 0
                status = "From the previous cut (\(v.label)) — this time is approximate"
                + (abs(drift) > 0.5 ? ", the cut moved by about \(String(format: "%.0f", abs(drift))) s" : "")
            }
        }
        focusField()
    }

    func select(_ id: String?) {
        setSelection(id.map { [$0] } ?? [])
    }

    /// ⌘A with an empty note field.
    func selectAllNotes() {
        guard let s = store, !s.notes.isEmpty else { return }
        selection = Set(s.notes.map(\.id))
        status = "\(s.notes.count) notes selected — \(Shortcuts.label(.archiveNotes)) archives them, \(Shortcuts.label(.deleteNote)) deletes them"
        focusField()
    }

    /// Selected notes → the Archived section: still in notes.json, left out
    /// of the export. The way to say "these are done" after a pass in Resolve.
    func archiveSelected() {
        guard let s = store, !selection.isEmpty else { return }
        let moved = s.archive(selection)
        selection = []
        guard !moved.isEmpty else { return }
        status = "Archived \(moved.count) note\(moved.count == 1 ? "" : "s") (hidden from the export) — \(Shortcuts.label(.undo)) restores"
        focusField()
    }

    /// A previous-cut note the user wants to act on after all: make it live
    /// here, at whatever time it had.
    func bringBackNote(_ id: String) {
        guard let s = store, let n = s.bringBack([id]).first else { return }
        selection = [n.id]
        status = "Brought back to \(timecode(n.seconds)) — the time is from the previous cut, nudge it with \(Shortcuts.label(.seekBack)) / \(Shortcuts.label(.seekForward))"
        focusField()
    }

    func bringBackSelected() {
        guard let s = store, !selection.isEmpty else { return }
        let moved = s.bringBack(selection)
        guard !moved.isEmpty else { return }
        selection = Set(moved.map(\.id))
        status = "Brought back \(moved.count) note\(moved.count == 1 ? "" : "s") from the previous cut — \(Shortcuts.label(.undo)) undoes"
        focusField()
    }

    /// Every selected row is a note from an earlier cut.
    var selectionIsPreviousCut: Bool {
        guard let s = store, !selection.isEmpty else { return false }
        return selection.allSatisfy { s.versionNote($0) != nil }
    }

    func restoreNote(_ id: String) {
        guard let s = store, let n = s.restore([id]).first else { return }
        selection = [n.id]
        status = "Restored note at \(timecode(n.seconds))"
        focusField()
    }

    /// ← / → and their ⇧ / ⌃ / ⌃⇧ variants: move the playhead by `delta`
    /// seconds — or, paused with a note selected, move that note instead.
    func step(by delta: Double) {
        if !player.isPlaying, let id = selectedID {
            nudge(id, by: delta)
        } else {
            player.seek(by: delta)
        }
    }

    func nudge(_ id: String, by delta: Double) {
        guard let s = store, let n = s.note(id) else { return }
        let t = min(max(0, n.seconds + delta), max(0, player.duration))
        s.setSeconds(id, t)
        player.seek(to: t)
        status = "Note moved to \(timecode(t))"
    }

    func deleteNote(_ id: String) {
        guard let s = store else { return }
        let tc = s.note(id).map { timecode($0.seconds) } ?? ""
        s.delete(id)
        selection.remove(id)
        status = "Deleted note at \(tc) — \(Shortcuts.label(.undo)) undoes"
    }

    func deleteSelected() {
        guard let s = store, !selection.isEmpty else { return }
        let ids = s.notes.filter { selection.contains($0.id) }.map(\.id)
        guard !ids.isEmpty else { return }      // archived / previous-cut rows: nothing to delete
        if ids.count == 1 { deleteNote(ids[0]); return }
        for id in ids { s.delete(id) }
        selection = []
        status = "Deleted \(ids.count) notes — \(Shortcuts.label(.undo)) undoes one at a time"
    }

    func undo() {
        guard let s = store, s.canUndo else { status = "Nothing to undo"; return }
        guard let r = s.undo() else { return }
        selection = r.select.map { [$0] } ?? []
        status = r.message
    }

    func cycleSpeed(_ step: Int = 1) {
        player.cycleSpeed(step)
        status = "Speed \(player.speedLabel)"
    }

    // MARK: timeline zoom

    /// Narrowest window ⌃E goes down to: 2 s across the bar is 20 ms a column
    /// at 1000 px, enough to land on one word.
    static let minZoomWindow = 2.0

    func zoomIn() {
        let full = max(player.duration, Self.minZoomWindow)
        let cur = zoomWindow ?? full
        let next = max(cur / 2, Self.minZoomWindow)
        guard next < cur else { status = "Zoomed all the way in (\(ReviewStore.mmss(cur)) across the bar)"; return }
        setZoomWindow(next)
    }

    func zoomOut() {
        let full = player.duration
        guard let cur = zoomWindow else { status = "Whole file shown"; return }
        let next = cur * 2
        if next >= full { resetZoom(); return }
        setZoomWindow(next)
    }

    func resetZoom() {
        zoomWindow = nil
        viewStart = 0
        status = "Whole file shown"
    }

    /// Zoom around the playhead: it lands in the middle of the new window.
    private func setZoomWindow(_ len: Double) {
        zoomWindow = len
        viewStart = clampViewStart(player.currentSeconds - len / 2, window: len)
        status = "Zoom: \(ReviewStore.mmss(len)) across the bar (\(Shortcuts.label(.zoomIn)) in · \(Shortcuts.label(.zoomOut)) out)"
    }

    private func clampViewStart(_ start: Double, window: Double) -> Double {
        min(max(0, start), max(0, player.duration - window))
    }

    /// Called as the playhead moves: page the window when it runs off an end,
    /// leaving it a little way in so the next few seconds are in view.
    func keepPlayheadInView() {
        guard let len = zoomWindow else { return }
        let t = player.currentSeconds
        if scrolledAway {
            if t >= viewStart, t <= viewStart + len { scrolledAway = false }
            else if player.isPlaying { return }
        }
        if t < viewStart || t > viewStart + len {
            scrolledAway = false
            viewStart = clampViewStart(t - len * 0.15, window: len)
        }
    }

    /// Scroll wheel over the timeline. Plain: zoom, keeping the time under the
    /// pointer where it is. ⇧ (or a sideways swipe): move the window along.
    private func handleScroll(_ e: NSEvent) -> NSEvent? {
        guard let hover = timelineHover, player.duration > 0 else { return e }
        let precise = e.hasPreciseScrollingDeltas
        var dx = Double(e.scrollingDeltaX), dy = Double(e.scrollingDeltaY)
        // A mouse wheel with ⇧ arrives as a horizontal delta already; a trackpad does not.
        if e.modifierFlags.contains(.shift), dx == 0 { dx = dy }
        let pan = e.modifierFlags.contains(.shift) || abs(dx) > abs(dy)
        let full = player.duration
        let win = visibleWindow
        if pan {
            guard zoomWindow != nil, dx != 0 else { return nil }
            let points = precise ? dx : dx * 12
            viewStart = clampViewStart(win.start - points / max(hover.width, 1) * win.length, window: win.length)
        } else {
            guard dy != 0 else { return nil }
            let next = min(max(win.length * exp(-dy * (precise ? 0.01 : 0.12)), Self.minZoomWindow), full)
            guard next != win.length else { return nil }
            if next >= full {
                zoomWindow = nil
                viewStart = 0
            } else {
                let anchor = win.start + hover.fraction * win.length
                zoomWindow = next
                viewStart = clampViewStart(anchor - hover.fraction * next, window: next)
            }
        }
        let t = player.currentSeconds
        scrolledAway = zoomWindow != nil && (t < viewStart || t > viewStart + (zoomWindow ?? full))
        return nil
    }

    /// The window the timeline shows, in seconds: (start, length).
    var visibleWindow: (start: Double, length: Double) {
        let full = max(player.duration, 0.001)
        guard let len = zoomWindow, len < full else { return (0, full) }
        return (clampViewStart(viewStart, window: len), len)
    }

    // MARK: cuts

    /// Reads the sidecar; returns a few words for the status line.
    @discardableResult
    private func loadCuts(for video: URL, duration: Double) -> String? {
        switch CutList.load(for: video, duration: duration) {
        case .loaded(let list):
            cuts = list
            log("cuts: \(list.cuts.count) from \(list.project) / \(list.timeline)")
            // Every clip's first frame, then every last frame: the strip shows
            // the first one whenever a block has room for only one.
            let f = max(player.fps, 1)
            let clips = list.cuts.filter { !$0.isGap }
            player.buildCutThumbs(frames: clips.map { $0.firstFrame(fps: f) } + clips.map { $0.lastFrame(fps: f) })
            return "\(list.cuts.count) cuts"
        case .missing:
            cuts = nil
            return nil
        case .rejected(let why):
            cuts = nil
            log("cuts: ignored — \(why)")
            return "cuts ignored: \(why)"
        }
    }

    /// Where the playhead is put for a boundary: a quarter frame inside the
    /// incoming clip. Exactly on the boundary, rounding (23.976, the sidecar's
    /// six decimals) can show — and stamp a note on — the outgoing clip's last frame.
    func landing(for boundary: Double) -> Double {
        min(boundary + 0.25 / max(player.fps, 1), max(player.duration, 0))
    }

    /// The pointer's snap: `seconds` pulled onto a cut within `reach` seconds of
    /// it (the timeline passes a few points' worth). ⌥ held: no snap.
    func snapped(_ seconds: Double, reach: Double) -> (seconds: Double, boundary: Double?) {
        guard let cuts, !NSEvent.modifierFlags.contains(.option),
              let b = cuts.boundary(near: seconds, reach: reach) else { return (seconds, nil) }
        return (landing(for: b), b)
    }

    /// ↑ / ↓, as in Resolve: the previous / next edit point. Paused with a note
    /// selected, the note goes there instead (same rule as ← / →).
    func jumpCut(_ direction: Int) {
        guard let cuts else {
            status = "No cuts for this file — Review › Get Cuts from Resolve, with its timeline open there"
            NSSound.beep()
            return
        }
        let moving = player.isPlaying ? nil : selectedID
        let from = moving.flatMap { store?.note($0)?.seconds } ?? player.currentSeconds
        let half = 0.5 / max(player.fps, 1)
        // Playing, ↑ within the first moments of a clip means "the one before",
        // or the playhead would keep falling back to the same cut.
        let slack = player.isPlaying ? 0.6 : half
        guard let b = direction < 0 ? cuts.boundary(before: from - slack) : cuts.boundary(after: from + half) else {
            NSSound.beep()
            return
        }
        let t = landing(for: b)
        if let id = moving, let s = store {
            s.setSeconds(id, t)
            player.seek(to: t)
            status = "Note moved to the cut at \(timecode(t))" + (cuts.cut(at: t).map { " · \($0.name)" } ?? "")
        } else {
            player.seek(to: t)
            if let c = cuts.cut(at: t) { status = "Cut \(c.index) of \(cuts.cuts.count) · \(c.name) · \(ReviewStore.mmss(c.length)) long" }
        }
    }

    /// Review › Set Skills Repo Folder…: where tools/transcribe.py and
    /// export_cuts.py live, when the app cannot work it out by itself.
    func pickRepo() {
        if let url = RepoTools.pickRepo() {
            status = "Skills repo: \(url.path)"
            loadTranscript()
        } else {
            status = "No repo picked (the folder must contain tools/)"
        }
        focusField()
    }

    /// Review › Get Cuts from Resolve: run scripts/export_cuts.py for this file.
    /// Resolve must have the project open; the script finds the timeline by length.
    func pullCutsFromResolve() {
        guard let s = store, !pullingCuts else { return }
        guard let script = RepoTools.script("apps/edit-review/scripts/export_cuts.py") else {
            status = "export_cuts.py not found: pick the repo folder (Review › Set Skills Repo Folder…)"
            NSSound.beep()
            return
        }
        let video = s.videoURL
        pullingCuts = true
        status = "Asking Resolve for the cuts of \(video.lastPathComponent)…"
        Task { @MainActor in
            let (code, text) = await Self.run(python: script, video: video)
            pullingCuts = false
            guard store?.videoURL == video else { return }
            if code == 0 {
                let note = loadCuts(for: video, duration: player.duration)
                status = cuts.map { "\($0.cuts.count) cuts from \($0.project) / \($0.timeline) · \(Shortcuts.label(.previousCut)) / \(Shortcuts.label(.nextCut)) jump between them" }
                    ?? (note ?? "Resolve answered but no cuts were written")
            } else {
                status = "No cuts: " + (text.isEmpty ? "export_cuts.py exit \(code)" : text)
                NSSound.beep()
            }
        }
    }

    /// A login shell, so `python3` is the one the terminal uses (the one that
    /// can load Resolve's scripting module). Returns the exit code and the last line said.
    nonisolated private static func run(python script: URL, video: URL) async -> (Int32, String) {
        let p = RepoTools.pythonProcess(script: script, arguments: [video.path])
        let out = Pipe()
        p.standardOutput = out
        p.standardError = out
        do { try p.run() } catch { return (-1, error.localizedDescription) }
        let data = await Task.detached { out.fileHandleForReading.readDataToEndOfFile() }.value
        p.waitUntilExit()
        let last = String(data: data, encoding: .utf8)?
            .split(whereSeparator: \.isNewline).last.map(String.init) ?? ""
        return (p.terminationStatus, last.trimmingCharacters(in: .whitespaces))
    }

    // MARK: changes

    /// Reads the changes sidecar; returns a few words for the status line.
    @discardableResult
    private func loadChanges(for video: URL, duration: Double) -> String? {
        currentChangeID = nil
        focusedChangeID = nil
        switch ChangeList.load(for: video, duration: duration) {
        case .loaded(let list):
            changes = list
            let mtime = (try? FileManager.default.attributesOfItem(atPath: ChangeList.sidecarURL(for: video).path))?[.modificationDate] as? Date
            seenKey = "changesSeen|\(video.path)|\(list.round)|\(Int(mtime?.timeIntervalSince1970 ?? 0))"
            seenChanges = Set(seenKey.flatMap { UserDefaults.standard.stringArray(forKey: $0) } ?? [])
            log("changes: \(list.changes.count) since \(list.previous ?? "the previous cut"), \(seenChanges.count) seen")
            return "\(list.changes.count) change\(list.changes.count == 1 ? "" : "s") since \(list.previous ?? "the last cut") · \(Shortcuts.label(.nextChange)) steps through them"
        case .missing:
            changes = nil
            return nil
        case .rejected(let why):
            changes = nil
            log("changes: ignored — \(why)")
            return "changes ignored: \(why)"
        }
    }

    /// Per playhead tick: which change is playing, and which have been played
    /// through to their end (a ✓ in the list).
    private func trackChanges(at t: Double) {
        guard let list = changes else { return }
        let id = list.change(at: t)?.id
        if id != currentChangeID { currentChangeID = id }
        defer { lastTick = t }
        guard player.isPlaying, !player.isScrubbing, t > lastTick, t - lastTick < 1.5 else { return }
        var added = false
        for c in list.changes where !seenChanges.contains(c.id) {
            let mark = c.isPoint ? c.start + ChangeList.pointReach : c.end - 0.05
            if lastTick < mark, t >= mark { seenChanges.insert(c.id); added = true }
        }
        if added, let k = seenKey { UserDefaults.standard.set(Array(seenChanges), forKey: k) }
    }

    /// A click on a change (list row or timeline flag): play it from just before.
    func jumpToChange(_ id: String) {
        guard let list = changes, let c = list.changes.first(where: { $0.id == id }) else { return }
        focusedChangeID = id
        let t = max(0, c.start - ChangeList.preroll)
        player.seek(to: t)
        lastTick = t
        play()
        let n = list.number(of: id) ?? 0
        status = "Change \(n) of \(list.changes.count) · \(c.title)" + (c.watch.map { " — watch: \($0)" } ?? "")
    }

    /// ⌥↑ / ⌥↓: the previous / next change, played from just before it.
    func jumpChange(_ direction: Int) {
        guard let list = changes else {
            status = "No changes file for this cut (<stem>.review/changes.json)"
            NSSound.beep()
            return
        }
        let t = player.currentSeconds
        var target: Change?
        if let f = focusedChangeID, let i = list.changes.firstIndex(where: { $0.id == f }), list.isOn(list.changes[i], at: t) {
            let j = i + direction
            target = list.changes.indices.contains(j) ? list.changes[j] : nil
        } else {
            target = direction < 0 ? list.previous(from: t) : list.next(from: t)
        }
        guard let c = target else {
            status = direction < 0 ? "No change before this one" : "That was the last change"
            NSSound.beep()
            return
        }
        jumpToChange(c.id)
    }

    /// Forget which changes were played (the list's ✓).
    func resetSeenChanges() {
        seenChanges = []
        if let k = seenKey { UserDefaults.standard.removeObject(forKey: k) }
    }

    // MARK: keyboard

    func installMonitor() {
        guard monitor == nil else { return }
        for m in Shortcuts.loaded.messages { log(m) }
        if !Shortcuts.loaded.messages.isEmpty {
            status = "shortcuts.json: \(Shortcuts.loaded.messages.count) problem(s) — see the legend (⌘/)"
        }
        monitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] e in
            guard let self else { return e }
            return self.handle(e)
        }
        scrollMonitor = NSEvent.addLocalMonitorForEvents(matching: .scrollWheel) { [weak self] e in
            guard let self else { return e }
            return self.handleScroll(e)
        }
    }

    private enum Key {
        static let ret: UInt16 = 36, enter: UInt16 = 76, space: UInt16 = 49, esc: UInt16 = 53, tab: UInt16 = 48
        static let left: UInt16 = 123, right: UInt16 = 124, backspace: UInt16 = 51, del: UInt16 = 117
        static let home: UInt16 = 115, end: UInt16 = 119, up: UInt16 = 126, down: UInt16 = 125
    }

    private var window: NSWindow? {
        NSApp.keyWindow ?? NSApp.mainWindow ?? NSApp.windows.first { $0.isVisible }
    }

    private var inTextEditing: Bool {
        window?.firstResponder is NSTextView
    }

    /// Some other text control has focus (an inline note edit, the Start TC
    /// field): keys belong to it, apart from ESC / ⏎ which hand focus back.
    private var inOtherTextEditing: Bool { inTextEditing && !fieldFocused }

    func blur() {
        window?.makeFirstResponder(nil)
    }

    /// Returns nil to swallow the event. The remappable keys come from
    /// `Shortcuts` (Shortcuts.swift, plus the user's shortcuts.json); ⏎ and
    /// ESC are fixed because they belong to the note field.
    func handle(_ e: NSEvent) -> NSEvent? {
        // The ⌘O panel runs inside the app too: its keys (⌘⇧G, ⌘F, SPACE) are its own.
        if e.window is NSSavePanel { return e }
        guard store != nil else { return e }
        let shift = e.modifierFlags.contains(.shift)
        let isReturn = e.keyCode == Key.ret || e.keyCode == Key.enter
        let action = Shortcuts.action(for: e)

        // Find works from anywhere, even while another field has the keys.
        switch action {
        case .find: openFind(); return nil
        case .findNext: findNext(1); return nil
        case .findPrevious: findNext(-1); return nil
        default: break
        }

        if inOtherTextEditing {
            if findFieldFocused {
                if e.keyCode == Key.esc { closeFind(); return nil }
                if isReturn { findNext(shift ? -1 : 1); return nil }
            } else {
                if e.keyCode == Key.esc { blur(); focusField(); return nil }
                if isReturn { return e }    // let onSubmit run; the view refocuses the field afterwards
            }
            // Zoom and frame steps never type anything, so they work here too.
            if let action, Self.worksWhileEditing.contains(action) { return perform(action) ? nil : e }
            return e
        }

        if let action {
            // With text in the field these keys type (a space, a deleted
            // character) or are the field's own (undo, select all).
            if !draftText.isEmpty && (Self.needsEmptyField.contains(action) || Self.types(e)) { return e }
            return perform(action) ? nil : e
        }

        if isReturn {
            if hasDraft { addNote() }
            else if !draftText.isEmpty { clearDraft() }
            else if selectionIsPreviousCut { bringBackSelected() }
            return nil
        }
        if e.keyCode == Key.esc {
            if draftText.isEmpty && findOpen { closeFind() } else { clearDraft() }
            return nil
        }
        return e
    }

    private static let worksWhileEditing: Set<ReviewAction> = [
        .zoomIn, .zoomOut, .frameBack, .frameForward, .halfSecondBack, .halfSecondForward,
    ]
    private static let needsEmptyField: Set<ReviewAction> = [
        .playPause, .deleteNote, .archiveNotes, .undo, .selectAllNotes,
    ]

    /// The key would put a character in a text field (space, ⌫, a letter).
    private static func types(_ e: NSEvent) -> Bool {
        let m = e.modifierFlags.intersection([.command, .control, .option])
        guard m.isEmpty else { return false }
        if [Key.space, Key.backspace, Key.del].contains(e.keyCode) { return true }
        guard let scalar = e.characters?.unicodeScalars.first else { return false }
        return scalar.value >= 0x20 && scalar.value < 0xF700 && scalar.value != 0x7F
    }

    /// Run one action; false when there was nothing to do (the key then goes
    /// on to the focused control, as if unbound).
    private func perform(_ action: ReviewAction) -> Bool {
        switch action {
        case .playPause: togglePlay()
        case .speedUp: cycleSpeed(1)
        case .speedDown: cycleSpeed(-1)
        case .seekBack: step(by: -Shortcuts.seekStep)
        case .seekForward: step(by: Shortcuts.seekStep)
        case .seekBackBig: step(by: -Shortcuts.bigSeekStep)
        case .seekForwardBig: step(by: Shortcuts.bigSeekStep)
        case .frameBack: step(by: -1 / max(player.fps, 1))
        case .frameForward: step(by: 1 / max(player.fps, 1))
        case .halfSecondBack: step(by: -Shortcuts.smallSeekStep)
        case .halfSecondForward: step(by: Shortcuts.smallSeekStep)
        case .zoomIn: zoomIn()
        case .zoomOut: zoomOut()
        case .previousCut: jumpCut(-1)
        case .nextCut: jumpCut(1)
        case .previousChange: jumpChange(-1)
        case .nextChange: jumpChange(1)
        case .goToStart: player.seek(to: 0)
        case .goToEnd: player.seek(to: player.duration)
        case .deleteNote:
            guard !selection.isEmpty else { return false }
            deleteSelected()
        case .archiveNotes:
            guard !selection.isEmpty else { return false }
            archiveSelected()
        case .undo: undo()
        case .selectAllNotes:
            guard store?.notes.isEmpty == false else { return false }
            selectAllNotes()
        case .find: openFind()
        case .findNext: findNext(1)
        case .findPrevious: findNext(-1)
        }
        return true
    }

    // MARK: drag & drop

    func handleDrop(_ providers: [NSItemProvider]) -> Bool {
        guard let p = providers.first(where: { $0.hasItemConformingToTypeIdentifier(UTType.fileURL.identifier) }) else {
            return false
        }
        p.loadItem(forTypeIdentifier: UTType.fileURL.identifier) { item, _ in
            var url: URL?
            if let d = item as? Data { url = URL(dataRepresentation: d, relativeTo: nil) }
            else if let u = item as? URL { url = u }
            guard let url else { return }
            Task { @MainActor in self.open(url: url) }
        }
        return true
    }
}


// MARK: - scripted keys (test hook)
//
// EDIT_REVIEW_KEYS="wait:3,space,wait:2,type:bad cut,enter,tab,left,dump,quit"
// posts real key events into the app's own event queue, so the exact same
// monitor / first-responder path runs as for physical keys. Used by the
// verification in the README; harmless when the variable is unset.
extension ReviewController {
    private static let keyTable: [String: (UInt16, String)] = [
        "space": (49, " "), "enter": (36, "\r"), "esc": (53, "\u{1B}"), "tab": (48, "\t"),
        "left": (123, "\u{F702}"), "right": (124, "\u{F703}"),
        "delete": (51, "\u{7F}"), "s": (1, "s"), "z": (6, "z"), "a": (0, "a"), "e": (14, "e"), "w": (13, "w"),
        "f": (3, "f"), "g": (5, "g"),
        "home": (115, "\u{F729}"), "end": (119, "\u{F72B}"), "up": (126, "\u{F700}"), "down": (125, "\u{F701}"),
    ]

    func runKeyScriptFromEnvironment() {
        guard let script = ProcessInfo.processInfo.environment["EDIT_REVIEW_KEYS"], !script.isEmpty else { return }
        Task { @MainActor in
            for raw in script.split(separator: ",") {
                let cmd = raw.trimmingCharacters(in: .whitespaces)
                if cmd.hasPrefix("wait:") {
                    try? await Task.sleep(for: .seconds(Double(cmd.dropFirst(5)) ?? 1))
                } else if cmd.hasPrefix("type:") {
                    for ch in cmd.dropFirst(5) {
                        let c = String(ch)
                        postKey(code: c == " " ? 49 : 0, chars: c, mods: [])
                        try? await Task.sleep(for: .milliseconds(40))
                    }
                } else if cmd == "dump" {
                    dumpState()
                } else if cmd.hasPrefix("seek:") {              // stands in for a click on a word
                    seekFromTranscript(to: Double(cmd.dropFirst(5)) ?? 0)
                } else if cmd == "quit" {
                    NSApp.terminate(nil)
                } else {
                    var mods: NSEvent.ModifierFlags = []
                    var name = cmd
                    while let r = name.range(of: #"^(shift|cmd|ctrl|opt)\+"#, options: .regularExpression) {
                        mods.insert(name[r].hasPrefix("shift") ? .shift : name[r].hasPrefix("ctrl") ? .control
                                    : name[r].hasPrefix("opt") ? .option : .command)
                        name.removeSubrange(r)
                    }
                    guard let (code, chars) = Self.keyTable[name] else { log("script: unknown key \(cmd)"); continue }
                    postKey(code: code, chars: chars, mods: mods)
                }
                try? await Task.sleep(for: .milliseconds(150))
            }
        }
    }

    private func postKey(code: UInt16, chars: String, mods: NSEvent.ModifierFlags) {
        guard let win = window else { log("script: no window"); return }
        for type in [NSEvent.EventType.keyDown, .keyUp] {
            if let e = NSEvent.keyEvent(with: type, location: .zero, modifierFlags: mods,
                                        timestamp: ProcessInfo.processInfo.systemUptime,
                                        windowNumber: win.windowNumber, context: nil,
                                        characters: chars, charactersIgnoringModifiers: chars,
                                        isARepeat: false, keyCode: code) {
                NSApp.postEvent(e, atStart: false)
            }
        }
    }

    func dumpState() {
        let word = currentWord.flatMap { i in transcript.map { "\(i):\($0.words[i].text)" } } ?? "-"
        var lines = ["state: playing=\(player.isPlaying) speed=\(player.speed) t=\(String(format: "%.2f", player.currentSeconds)) tc=\(playheadTimecode) draft=\"\(draftText)\" fieldFocused=\(fieldFocused) editing=\(inTextEditing) selected=\(selection.isEmpty ? "-" : selection.sorted().joined(separator: ",")) archived=\(store?.archived.count ?? 0) words=\(transcript?.words.count ?? 0) word=\(word) transcribing=\(transcriber.running) status=\"\(status)\""]
        if findOpen {
            let hits = found.matches.prefix(5).map { m in
                transcript.map { t in String(format: "%.2fs ", t.words[m.lowerBound].start) + t.words[m].map(\.text).joined(separator: " ") } ?? "?"
            }
            lines.append("  find \"\(findText)\" focused=\(findFieldFocused) hits=\(found.matches.count)\(found.fuzzy ? " fuzzy" : "") current=\(currentFound.map(String.init) ?? "-") first: \(hits.joined(separator: " | "))")
        }
        if let ch = changes {
            lines.append("  changes \(ch.changes.count) round=\(ch.round) current=\(currentChangeID ?? "-") focused=\(focusedChangeID ?? "-") seen=\(seenChanges.count)")
        }
        for n in store?.notes ?? [] {
            lines.append("  note \(timecode(n.seconds)) \(String(format: "%.2f", n.seconds))s text=\"\(n.text)\"")
        }
        log(lines.joined(separator: "\n"))
    }
}
