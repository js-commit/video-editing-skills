import Foundation

/// What a tool wrote about a clip in the folder's `bulkcut.json`
/// (Manifest.swift). Read-only: the app never writes the manifest.
struct ClipNotes: Equatable, Sendable {
    /// One sentence on what the clip shows, and who wrote it.
    var description: String?
    var annotator: String?
    var tags: [String] = []
    var quality: [String] = []
    /// Why a tool picked it, a privacy concern, what was said over it in an
    /// edit, where it was cut from.
    var why: String?
    var privacy: String?
    var said: String?
    var origin: String?
    /// A speed baked into the file (0.4: plays at 40%); nil at 1×.
    var speed: Double?
    /// Annotated segments, in this file's own time.
    var segments: [Segment] = []
    /// Stretches of this file the library already holds, so a review does not
    /// cut the same moment twice.
    var taken: [Taken] = []

    struct Taken: Equatable, Sendable {
        var start: Double
        var end: Double
        var label: String
    }

    typealias Segment = Manifest.Segment

    var isEmpty: Bool {
        description == nil && why == nil && privacy == nil && said == nil && origin == nil && segments.isEmpty
            && taken.isEmpty && tags.isEmpty
    }

    /// "slowed to 40%", "sped up 4×"; nil at 1×.
    var speedLabel: String? {
        guard let s = speed else { return nil }
        if s < 1 { return "slowed to \(Int((s * 100).rounded()))%" }
        let x = (s * 100).rounded() / 100
        return "sped up " + (x == x.rounded() ? String(Int(x)) : String(x)) + "×"
    }

    /// The line to show where there is room for one.
    var headline: String? { description ?? segments.first?.description ?? why }

    /// Who wrote `description`, for a badge.
    var annotatorLabel: String? { annotator == "human" ? "you" : annotator }

    func segment(at t: Double) -> (index: Int, segment: Segment)? {
        segments.firstIndex { t >= $0.start && t < $0.end }.map { ($0, segments[$0]) }
    }
}

enum Annotations {
    /// Notes by Clip.key for `clips`, from `manifest`.
    static func notes(_ manifest: Manifest?, clips: [Clip]) -> [String: ClipNotes] {
        guard let m = manifest else { return [:] }
        var out: [String: ClipNotes] = [:]
        for clip in clips {
            guard let e = m.entry(clip) else { continue }
            var n = ClipNotes()
            n.description = e.description
            n.annotator = e.by
            n.tags = e.tags
            n.quality = e.quality
            n.why = e.why
            n.privacy = e.privacy
            n.said = e.context
            n.speed = e.speed
            n.origin = e.origin.map { $0 + (n.speedLabel.map { ", \($0)" } ?? "") }
            n.segments = e.segments
            n.taken = e.library.map { ClipNotes.Taken(start: $0.start, end: $0.end, label: $0.clip ?? "") }
            if !n.isEmpty { out[clip.key] = n }
        }
        return out
    }
}
