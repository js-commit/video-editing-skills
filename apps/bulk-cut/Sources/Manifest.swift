import Foundation

/// `bulkcut.json`: what a tool (a Claude Code skill, a script) put next to a
/// folder of clips for the user to look at in BulkCut. Optional: without it
/// the app is a plain triage tool. The format is documented in SPEC.md.
///
/// - Notes per file (a description, why it was picked, a privacy warning,
///   what the library already holds of it, annotated segments): shown in the
///   notes panel (⌘I) and on the timeline. Read-only.
/// - Proposed ranges per file: staged as keep ranges the first time the
///   folder opens with this manifest `id` (a new `id` proposes again).
/// - `"mode": "review"` makes it a review folder (ReviewFolder.swift): the
///   files are copies or links, nothing is ever trashed or cut, every change
///   is written to `bulkcut-review.json` for the tool to read back, and Apply
///   becomes the manifest's `send` action (or a plain "Done").
struct Manifest: Sendable {
    static let fileName = "bulkcut.json"
    static let reviewFileName = "bulkcut-review.json"

    /// Proposals are staged once per id.
    let id: String
    let title: String?
    let isReview: Bool
    let send: Send?
    let files: [String: FileEntry]
    let sequences: [Sequence]
    let legend: Legend

    struct Send: Sendable, Equatable {
        /// The button's title: "Send to library".
        let label: String
        /// argv; the first item is an absolute path to the program.
        let command: [String]
        /// What the command does, one line a step, for the sheet.
        let steps: [String]
    }

    struct Proposal: Sendable, Equatable {
        let start: Double
        let end: Double
        /// "pick" (purple) or "beat" (teal, a clip of a sequence); nil: an
        /// ordinary keep range (yellow).
        let kind: String?
        /// Drawn on the range: "beat 3: lid off".
        let label: String?
        /// Its description and who wrote it (the description box shows it).
        let text: String?
        let by: String?
        /// A beat's sequence (`sequences[].name`).
        let sequence: String?
    }

    /// A stretch the library already holds (drawn orange, read-only).
    struct LibraryClip: Sendable, Equatable {
        let start: Double
        let end: Double
        let text: String
        let by: String
        /// The library clip's name.
        let clip: String?
    }

    struct Segment: Sendable, Equatable {
        let start: Double
        let end: Double
        let description: String
        let tags: [String]
        let quality: String?
        let shaky: Bool
        let note: String?
    }

    struct FileEntry: Sendable {
        var source: String?
        /// false: starts "not kept" (staged for delete; in a review folder
        /// nothing is deleted) unless it has proposals.
        var kept = true
        var description: String?
        var by: String?
        var tags: [String] = []
        var quality: [String] = []
        var why: String?
        var privacy: String?
        var context: String?
        var origin: String?
        var speed: Double?
        var proposals: [Proposal] = []
        var library: [LibraryClip] = []
        var segments: [Segment] = []
    }

    struct Sequence: Sendable, Equatable {
        let name: String
        let kind: String
        let beats: [Beat]

        /// "unboxing: desk lamp unboxing"
        var title: String { "\(kind): " + name.replacingOccurrences(of: "-", with: " ") }
    }

    struct Beat: Sendable, Equatable {
        let file: String
        let start: Double
        let end: Double
    }

    /// What the colours are called in this folder.
    struct Legend: Sendable, Equatable {
        var pick = "proposed"
        var beat = "sequence clip"
        var mine = "yours"
        var library = "already in the library"
    }

    /// The manifest of `folder`, nil when there is none or it can't be read.
    static func load(_ folder: URL) -> Manifest? {
        guard let data = try? Data(contentsOf: folder.appendingPathComponent(fileName)),
              let doc = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else { return nil }
        return Manifest(doc)
    }

    /// Is `folder` a review folder? (The scan needs to know before it starts: a
    /// review folder's files may be symbolic links to the originals.)
    static func isReview(_ folder: URL) -> Bool { load(folder)?.isReview ?? false }

    init(_ doc: [String: Any]) {
        id = Self.string(doc["id"]) ?? "1"
        title = Self.string(doc["title"])
        isReview = (doc["mode"] as? String) == "review"
        if let s = doc["send"] as? [String: Any], let cmd = s["command"] as? [String], !cmd.isEmpty {
            send = Send(label: Self.string(s["label"]) ?? "Send", command: cmd,
                        steps: (s["steps"] as? [String]) ?? [])
        } else {
            send = nil
        }
        var files: [String: FileEntry] = [:]
        for (name, value) in doc["files"] as? [String: Any] ?? [:] {
            guard let f = value as? [String: Any] else { continue }
            var e = FileEntry()
            e.source = Self.string(f["source"])
            e.kept = (f["kept"] as? Bool) ?? true
            e.description = Self.string(f["description"])
            e.by = Self.string(f["by"])
            e.tags = f["tags"] as? [String] ?? []
            e.quality = f["quality"] as? [String] ?? (Self.string(f["quality"]).map { [$0] } ?? [])
            e.why = Self.string(f["why"])
            e.privacy = Self.string(f["privacy"])
            e.context = Self.string(f["context"])
            e.origin = Self.string(f["origin"])
            if let s = Self.number(f["speed"]), s > 0, abs(s - 1) > 1e-3 { e.speed = s }
            e.proposals = (f["proposals"] as? [[String: Any]] ?? []).compactMap { p in
                guard let a = Self.number(p["start"]), let b = Self.number(p["end"]), b > a else { return nil }
                let kind = p["kind"] as? String
                return Proposal(start: a, end: b, kind: kind == "pick" || kind == "beat" ? kind : nil,
                                label: Self.string(p["label"]), text: Self.string(p["text"]),
                                by: Self.string(p["by"]), sequence: Self.string(p["sequence"]))
            }.sorted { $0.start < $1.start }
            e.library = (f["library"] as? [[String: Any]] ?? []).compactMap { l in
                guard let a = Self.number(l["start"]), let b = Self.number(l["end"]), b > a else { return nil }
                return LibraryClip(start: a, end: b, text: Self.string(l["text"]) ?? "",
                                   by: Self.string(l["by"]) ?? "", clip: Self.string(l["clip"]))
            }.sorted { $0.start < $1.start }
            e.segments = (f["segments"] as? [[String: Any]] ?? []).compactMap { s in
                guard let a = Self.number(s["start"]), let b = Self.number(s["end"]), b > a else { return nil }
                return Segment(start: a, end: b, description: Self.string(s["description"]) ?? "",
                               tags: s["tags"] as? [String] ?? [], quality: Self.string(s["quality"]),
                               shaky: s["shaky"] as? Bool ?? false, note: Self.string(s["note"]))
            }.sorted { $0.start < $1.start }
            files[name] = e
        }
        self.files = files
        sequences = (doc["sequences"] as? [[String: Any]] ?? []).map { s in
            Sequence(name: Self.string(s["name"]) ?? "sequence", kind: Self.string(s["kind"]) ?? "sequence",
                     beats: (s["beats"] as? [[String: Any]] ?? []).compactMap { b in
                         guard let f = b["file"] as? String, let a = Self.number(b["in"]), let z = Self.number(b["out"])
                         else { return nil }
                         return Beat(file: f, start: a, end: z)
                     })
        }
        var legend = Legend()
        if let l = doc["legend"] as? [String: Any] {
            legend.pick = Self.string(l["pick"]) ?? legend.pick
            legend.beat = Self.string(l["beat"]) ?? legend.beat
            legend.mine = Self.string(l["mine"]) ?? legend.mine
            legend.library = Self.string(l["library"]) ?? legend.library
        }
        self.legend = legend
    }

    /// The entry for a clip: by its path under the folder, else its name.
    func entry(_ clip: Clip) -> FileEntry? { files[clip.key] ?? files[clip.name] }

    /// The edit a file starts with: its proposals as keep ranges; "not kept"
    /// when `kept` is false and nothing is proposed. nil: nothing to stage.
    func proposedEdit(_ clip: Clip) -> ClipEdit? {
        guard let e = entry(clip) else { return nil }
        var edit = ClipEdit()
        edit.ranges = e.proposals.map {
            KeepRange(start: $0.start, end: $0.end, kind: $0.kind, label: $0.label, sequence: $0.sequence)
        }
        edit.deleted = edit.ranges.isEmpty && !e.kept
        return edit.isEmpty ? nil : edit
    }

    private static func number(_ v: Any?) -> Double? { (v as? Double) ?? (v as? Int).map(Double.init) }
    private static func string(_ v: Any?) -> String? {
        guard let t = (v as? String)?.trimmingCharacters(in: .whitespacesAndNewlines), !t.isEmpty else { return nil }
        return t
    }
}

/// `bulkcut-review.json`: what the user did in a review folder, written next
/// to the manifest after every change, for the tool that made the folder.
enum ReviewWriter {
    static func write(folder: URL, manifest: Manifest, clips: [Clip], edits: [String: ClipEdit]) {
        var files: [String: Any] = [:]
        for c in clips {
            let e = edits[c.key] ?? ClipEdit()
            let ranges: [[String: Any]] = (e.deleted ? [] : RangeOps.settle(e.ranges)).map { r in
                var d: [String: Any] = ["start": round3(r.start), "end": round3(r.end)]
                d["kind"] = r.kind ?? NSNull()
                if let l = r.label { d["label"] = l }
                if let s = r.sequence { d["sequence"] = s }
                if let n = r.note { d["note"] = n }
                return d
            }
            var f: [String: Any] = ["kind": c.isPhoto ? "photo" : "video", "deleted": e.deleted,
                                    "ranges": ranges, "turns": e.turns]
            if let s = manifest.entry(c)?.source { f["source"] = s }
            if let z = e.zoom {
                f["zoom"] = ["x": round3(z.x), "y": round3(z.y), "w": round3(z.w), "h": round3(z.h)]
            }
            files[c.key] = f
        }
        let doc: [String: Any] = [
            "schema": "bulkcut-review/1",
            "manifest_id": manifest.id,
            "saved": ISO8601DateFormatter().string(from: Date()),
            "folder": folder.path,
            "files": files,
        ]
        guard let data = try? JSONSerialization.data(withJSONObject: doc, options: [.prettyPrinted, .sortedKeys]) else { return }
        try? data.write(to: folder.appendingPathComponent(Manifest.reviewFileName), options: .atomic)
    }

    private static func round3(_ x: Double) -> Double { (x * 1000).rounded() / 1000 }
}

extension String {
    /// "already in the library" → "Already in the library".
    var capitalizedFirst: String { prefix(1).uppercased() + dropFirst() }
}
