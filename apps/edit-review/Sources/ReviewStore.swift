import Foundation

struct Note: Identifiable, Codable, Equatable {
    var id: String
    var seconds: Double          // file-relative playhead time, the source of truth
    var text: String
    var createdAt: String
    var archivedAt: String?      // set while the note sits in `archived`
    var archivedReason: String?  // optional free text: why it was archived

    enum CodingKeys: String, CodingKey {
        case id, seconds, text, createdAt = "created_at", archivedAt = "archived_at", archivedReason = "archived_reason"
    }
}

/// A whole review pass on a cut of this file that no longer exists — a
/// re-export whose length changed ends the pass, because every timestamp in
/// it is adrift by however much the cut moved.
///
/// It carries the pass entire: the notes still open when the cut changed and
/// the ones archived (dealt with) during it, which are just as adrift. The
/// current cut therefore starts with an empty list and an empty archive.
/// Nothing here is exported, but the pass can still be walked through —
/// clicking a note seeks to roughly where it was — and any note can be
/// brought back to the current cut when the drift is small enough to matter.
struct NoteVersion: Identifiable, Codable, Equatable {
    var id: String               // "20250101-120000", also the transcript file's stem
    var supersededAt: String
    var videoDuration: Double?   // the length this cut had
    var videoBytes: Int?
    var transcript: String?      // file inside <review>/versions/, when one was snapshotted
    var notes: [Note]

    enum CodingKeys: String, CodingKey {
        case id, supersededAt = "superseded_at", videoDuration = "video_duration",
             videoBytes = "video_bytes", transcript, notes
    }

    /// The length of that cut when it is known, else the day the pass ended.
    var label: String {
        if let d = videoDuration { return ReviewStore.mmss(d) }
        guard let date = ISO8601DateFormatter().date(from: supersededAt) else { return "earlier cut" }
        let f = DateFormatter()
        f.dateFormat = "d MMM"
        return f.string(from: date)
    }

    /// Notes that were already archived — dealt with — when the cut changed.
    var doneCount: Int { notes.filter { $0.archivedAt != nil }.count }
}

struct ReviewDocument: Codable {
    var schema = "edit-review/4"
    var video: String
    var frameRate: Double
    var startTimecode: String
    var videoDuration: Double?   // seconds, as AVFoundation reports it, when the notes were last saved
    var videoBytes: Int?
    var notes: [Note]            // the live notes — the only ones export_review.py reads
    var archived: [Note]?        // notes the user archived by hand: dealt with
    var versions: [NoteVersion]? // notes from earlier cuts of this file, newest first

    enum CodingKeys: String, CodingKey {
        case schema, video, frameRate = "frame_rate", startTimecode = "start_timecode",
             videoDuration = "video_duration", videoBytes = "video_bytes", notes, archived, versions
    }
}

/// Notes for one video, persisted in `<video-stem>.review/notes.json` after
/// every change.
///
/// The file also remembers the video's length. A re-export of the same cut
/// (different bytes, same length to the frame) keeps every note; a re-export
/// whose length changed is a new cut, so the live notes move to a version
/// entry — kept, walkable, out of the way — and the transcript goes with
/// them when a fresh one is made.
@MainActor
final class ReviewStore: ObservableObject {
    @Published private(set) var notes: [Note] = []
    @Published private(set) var archived: [Note] = []
    /// Notes from earlier cuts of this file, newest first. Never exported.
    @Published private(set) var versions: [NoteVersion] = []
    @Published var startTimecode: String { didSet { if startTimecode != oldValue { save() } } }

    let videoURL: URL
    /// `<stem>.review/` beside the video. Made by the first save, which only
    /// ever comes with something to keep (a note, a start timecode), not on open.
    let reviewDir: URL
    private(set) var reviewDirExists: Bool
    let fps: Double
    let videoDuration: Double
    let videoBytes: Int
    private(set) var loadedFromDisk = false
    /// Set by load(): the file's length differs from the one the notes were
    /// made on, so this is a new cut; `kept` live notes moved to versions[0].
    private(set) var lengthChange: (from: Double, to: Double, kept: Int)?
    /// Set by load(): same length, different bytes — a re-export of the same cut.
    private(set) var reexportedSameLength = false

    /// A Resolve re-export of the same timeline matches to the frame; anything
    /// past two frames at 24 fps is a real cut.
    static let lengthTolerance = 0.1

    /// Transcripts of older cuts are 0.5-1 MB each: keep the newest few.
    static let keptTranscripts = 3

    private enum UndoAction {
        case added(Note), deleted(Note), archived([Note]), restored([Note])
        case broughtBack(version: String, notes: [Note])
    }
    private var undoStack: [UndoAction] = []

    static func reviewDir(for videoURL: URL) -> URL {
        videoURL.deletingPathExtension().appendingPathExtension("review")
    }

    init(videoURL: URL, fps: Double, fileStartTimecode: String, duration: Double, bytes: Int) {
        self.videoURL = videoURL
        self.reviewDir = Self.reviewDir(for: videoURL)
        self.fps = fps
        self.videoDuration = duration
        self.videoBytes = bytes
        self.startTimecode = fileStartTimecode
        self.reviewDirExists = FileManager.default.fileExists(atPath: Self.reviewDir(for: videoURL).path)
        load()
    }

    var notesURL: URL { reviewDir.appendingPathComponent("notes.json") }

    func note(_ id: String) -> Note? { notes.first { $0.id == id } }
    func archivedNote(_ id: String) -> Note? { archived.first { $0.id == id } }
    /// A note in one of the earlier cuts, with the version it belongs to.
    func versionNote(_ id: String) -> (version: NoteVersion, note: Note)? {
        for v in versions {
            if let n = v.notes.first(where: { $0.id == id }) { return (v, n) }
        }
        return nil
    }
    func anyNote(_ id: String) -> Note? { note(id) ?? archivedNote(id) ?? versionNote(id)?.note }
    var versionsDir: URL { reviewDir.appendingPathComponent("versions") }
    var previousNoteCount: Int { versions.reduce(0) { $0 + $1.notes.count } }

    nonisolated static func mmss(_ s: Double) -> String {
        let m = Int(s) / 60
        return String(format: "%d:%04.1f", m, s - Double(m * 60))
    }

    // MARK: persistence

    private func load() {
        guard let data = try? Data(contentsOf: notesURL) else { return }
        do {
            let doc = try JSONDecoder().decode(ReviewDocument.self, from: data)
            notes = doc.notes.sorted { $0.seconds < $1.seconds }
            archived = (doc.archived ?? []).sorted { $0.seconds < $1.seconds }
            versions = doc.versions ?? []
            if !doc.startTimecode.isEmpty { startTimecode = doc.startTimecode }
            loadedFromDisk = true

            // Archived notes from a cut that is gone belong with that cut.
            var dirty = migrateArchivedOfOlderCuts()
            dirty = dirty || doc.videoDuration == nil || doc.videoBytes == nil
            if let was = doc.videoDuration, abs(was - videoDuration) > Self.lengthTolerance {
                let kept = supersede(duration: was, bytes: doc.videoBytes)
                lengthChange = (was, videoDuration, kept)
                dirty = true
            } else if let b = doc.videoBytes, b != videoBytes {
                reexportedSameLength = true
                dirty = true
            }
            if dirty { save() }         // record the length/bytes this file has now
        } catch {
            // Never clobber a file we could not parse: move it aside.
            let stamp = ISO8601DateFormatter().string(from: Date()).replacingOccurrences(of: ":", with: "-")
            try? FileManager.default.moveItem(at: notesURL,
                                              to: reviewDir.appendingPathComponent("notes.unreadable-\(stamp).json"))
            NSLog("edit-review: notes.json unreadable (%@), moved aside", "\(error)")
        }
    }

    /// Notes in `archived` that were archived during a pass that has since
    /// ended belong to that pass, not to this cut: a note dealt with on the
    /// 12:16.8 render is exactly as adrift on the 12:14.6 one as an open note
    /// is. So `archived` only ever holds what was archived on the cut that is
    /// open now; everything older moves into the version entry for its pass.
    /// Returns true when anything moved.
    private func migrateArchivedOfOlderCuts() -> Bool {
        var moved = false
        // Anything archived before the newest cut change was dealt with on a
        // file that is gone. Group by the moment it was archived: one batch
        // per pass (they stay marked as dealt with inside it).
        if let lastChange = versions.map(\.supersededAt).max() {
            let stale = archived.filter { ($0.archivedAt ?? "") < lastChange }
            if !stale.isEmpty {
                archived.removeAll { stale.contains($0) }
                for stamp in Set(stale.compactMap(\.archivedAt)) {
                    var group = stale.filter { $0.archivedAt == stamp }
                    for i in group.indices { group[i].archivedReason = nil }
                    versions.append(NoteVersion(id: Self.versionID(from: stamp), supersededAt: stamp,
                                                videoDuration: nil, videoBytes: nil, transcript: nil,
                                                notes: group.sorted { $0.seconds < $1.seconds }))
                }
                moved = true
            }
        }
        if moved { versions.sort { $0.supersededAt > $1.supersededAt } }   // newest pass first
        return moved
    }

    private static let versionStamp: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyyMMdd-HHmmss"
        f.timeZone = .current
        return f
    }()

    static func versionID(from iso: String? = nil) -> String {
        let date = iso.flatMap { ISO8601DateFormatter().date(from: $0) } ?? Date()
        return versionStamp.string(from: date)
    }

    /// A new cut: the whole pass belongs to the file that is gone — the open
    /// notes and the ones archived during it, which are equally adrift. Move
    /// them into a version entry (newest first) and return how many moved.
    /// Always makes the entry, even with nothing in it, so the old transcript
    /// has somewhere to land.
    @discardableResult
    private func supersede(duration: Double?, bytes: Int?) -> Int {
        let moved = (notes + archived).sorted { $0.seconds < $1.seconds }
        notes = []
        archived = []
        versions.insert(NoteVersion(id: Self.versionID(), supersededAt: ISO8601DateFormatter().string(from: Date()),
                                    videoDuration: duration, videoBytes: bytes, transcript: nil,
                                    notes: moved), at: 0)
        return moved.count
    }

    /// A note from an earlier pass, deliberately made live on this cut. Its
    /// seconds are whatever they were: the drift is the user's to judge. A
    /// note that had been dealt with comes back open.
    @discardableResult
    func bringBack(_ ids: Set<String>) -> [Note] {
        var moved: [Note] = []          // as they were, for undo
        var from: String?
        for i in versions.indices {
            let take = versions[i].notes.filter { ids.contains($0.id) }
            guard !take.isEmpty else { continue }
            from = from ?? versions[i].id
            versions[i].notes.removeAll { ids.contains($0.id) }
            moved.append(contentsOf: take)
        }
        guard !moved.isEmpty, let from else { return [] }
        notes.append(contentsOf: moved.map {
            var n = $0
            n.archivedAt = nil
            n.archivedReason = nil
            return n
        })
        resort()
        undoStack.append(.broughtBack(version: from, notes: moved))
        save()
        resort()
        return notes.filter { ids.contains($0.id) }
    }

    /// Park the transcript of the cut that is gone next to its notes:
    /// `<review>/versions/<version-id>.transcript.json`. Attaches to the
    /// newest version that has no transcript yet, or makes an empty entry
    /// for it. Returns the file it wrote, if it moved one.
    @discardableResult
    func snapshotTranscript(_ sidecar: URL, duration: Double?) -> URL? {
        guard FileManager.default.fileExists(atPath: sidecar.path) else { return nil }
        var index = versions.firstIndex { $0.transcript == nil }
        if index == nil {
            versions.insert(NoteVersion(id: Self.versionID(), supersededAt: ISO8601DateFormatter().string(from: Date()),
                                        videoDuration: duration, videoBytes: nil, transcript: nil, notes: []), at: 0)
            index = 0
        }
        guard let i = index else { return nil }
        let fm = FileManager.default
        try? fm.createDirectory(at: versionsDir, withIntermediateDirectories: true)
        let dest = versionsDir.appendingPathComponent("\(versions[i].id).transcript.json")
        try? fm.removeItem(at: dest)
        do { try fm.moveItem(at: sidecar, to: dest) } catch {
            NSLog("edit-review: could not park the old transcript: %@", "\(error)")
            return nil
        }
        if versions[i].videoDuration == nil { versions[i].videoDuration = duration }
        versions[i].transcript = dest.lastPathComponent
        // The engine's raw output (if the script kept one) goes with it.
        let orig = sidecar.deletingPathExtension().deletingPathExtension()
            .appendingPathExtension("transcript.original.json")
        try? fm.removeItem(at: versionsDir.appendingPathComponent("\(versions[i].id).transcript.original.json"))
        try? fm.moveItem(at: orig, to: versionsDir.appendingPathComponent("\(versions[i].id).transcript.original.json"))
        pruneTranscripts()
        save()
        return dest
    }

    /// Keep the newest `keptTranscripts` snapshots; the notes of older cuts
    /// stay, only their (0.5-1 MB) transcripts go.
    private func pruneTranscripts() {
        let withT = versions.enumerated().filter { $0.element.transcript != nil }
        guard withT.count > Self.keptTranscripts else { return }
        for (i, v) in withT.dropFirst(Self.keptTranscripts) {
            for name in [v.transcript, v.transcript.map { $0.replacingOccurrences(of: ".transcript.json", with: ".transcript.original.json") }] {
                if let name { try? FileManager.default.removeItem(at: versionsDir.appendingPathComponent(name)) }
            }
            versions[i].transcript = nil
        }
    }

    func save() {
        if !reviewDirExists {
            try? FileManager.default.createDirectory(at: reviewDir, withIntermediateDirectories: true)
            reviewDirExists = true
        }
        let doc = ReviewDocument(video: videoURL.lastPathComponent, frameRate: fps,
                                 startTimecode: startTimecode, videoDuration: videoDuration,
                                 videoBytes: videoBytes, notes: notes, archived: archived,
                                 versions: versions.isEmpty ? nil : versions)
        let enc = JSONEncoder()
        enc.outputFormatting = [.prettyPrinted, .sortedKeys]
        do {
            try enc.encode(doc).write(to: notesURL, options: .atomic)
        } catch {
            NSLog("edit-review: save failed: %@", "\(error)")
        }
    }

    // MARK: mutations (all autosave)

    private func resort() {
        notes.sort { $0.seconds < $1.seconds }
        archived.sort { $0.seconds < $1.seconds }
    }

    /// Add a finished note; Cmd+Z can take it back.
    func add(_ note: Note) {
        notes.append(note)
        resort()
        undoStack.append(.added(note))
        save()
    }

    func setText(_ id: String, _ text: String) {
        guard let i = notes.firstIndex(where: { $0.id == id }), notes[i].text != text else { return }
        notes[i].text = text
        save()
    }

    func setSeconds(_ id: String, _ seconds: Double) {
        guard let i = notes.firstIndex(where: { $0.id == id }) else { return }
        notes[i].seconds = seconds
        resort()
        save()
    }

    func delete(_ id: String) {
        guard let i = notes.firstIndex(where: { $0.id == id }) else { return }
        undoStack.append(.deleted(notes.remove(at: i)))
        save()
    }

    /// Live → archived: still in the file, hidden from the export. Returns
    /// the notes that moved (time order).
    @discardableResult
    func archive(_ ids: Set<String>, reason: String? = nil) -> [Note] {
        let moved = moveToArchive(ids, reason: reason)
        guard !moved.isEmpty else { return [] }
        undoStack.append(.archived(moved))
        save()
        return moved
    }

    /// Archived → live.
    @discardableResult
    func restore(_ ids: Set<String>) -> [Note] {
        let back = moveToLive(ids)
        guard !back.isEmpty else { return [] }
        undoStack.append(.restored(back))
        save()
        return back
    }

    private func moveToArchive(_ ids: Set<String>, reason: String?) -> [Note] {
        let stamp = ISO8601DateFormatter().string(from: Date())
        var moved: [Note] = []
        notes.removeAll { n in
            guard ids.contains(n.id) else { return false }
            var a = n
            a.archivedAt = stamp
            a.archivedReason = reason
            moved.append(a)
            return true
        }
        archived.append(contentsOf: moved)
        resort()
        return moved
    }

    private func moveToLive(_ ids: Set<String>) -> [Note] {
        var back: [Note] = []
        archived.removeAll { n in
            guard ids.contains(n.id) else { return false }
            var l = n
            l.archivedAt = nil
            l.archivedReason = nil
            back.append(l)
            return true
        }
        notes.append(contentsOf: back)
        resort()
        return back
    }

    /// Undo the last delete / add / archive / restore. Returns the note to
    /// select afterwards (if one came back) and a status line.
    func undo() -> (select: String?, message: String)? {
        guard let action = undoStack.popLast() else { return nil }
        switch action {
        case .deleted(let n):
            notes.append(n)
            resort()
            save()
            return (n.id, "Restored note")
        case .added(let n):
            notes.removeAll { $0.id == n.id }
            save()
            return (nil, "Removed last note")
        case .archived(let ns):
            let back = moveToLive(Set(ns.map(\.id)))
            save()
            return (back.count == 1 ? back.first?.id : nil, "Restored \(back.count) archived note\(back.count == 1 ? "" : "s")")
        case .restored(let ns):
            let moved = moveToArchive(Set(ns.map(\.id)), reason: ns.first?.archivedReason)
            save()
            return (nil, "Archived \(moved.count) note\(moved.count == 1 ? "" : "s") again")
        case .broughtBack(let version, let ns):
            let ids = Set(ns.map(\.id))
            notes.removeAll { ids.contains($0.id) }
            if let i = versions.firstIndex(where: { $0.id == version }) {
                versions[i].notes.append(contentsOf: ns)     // with the dealt-with mark they had
                versions[i].notes.sort { $0.seconds < $1.seconds }
            }
            save()
            return (nil, "Put \(ns.count) note\(ns.count == 1 ? "" : "s") back under the previous cut")
        }
    }

    var canUndo: Bool { !undoStack.isEmpty }
}
