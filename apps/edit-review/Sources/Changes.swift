import Foundation
import SwiftUI

/// One thing the editor changed since the previous cut, from
/// `<stem>.review/changes.json` (schema edit-review-changes/1). Times are file
/// seconds. A removal has no length (start == end): the join where the shot was.
struct Change: Identifiable, Codable, Equatable {
    var id: String
    var start: Double
    var end: Double
    var title: String
    /// What was done, in a sentence or two.
    var what: String?
    /// What to look at while it plays.
    var watch: String?
    /// The reviewer's note from the previous cut that this answers.
    var note: String?
    /// changed / added / removed / audio / music / answer — display only.
    var kind: String?

    var isPoint: Bool { end - start < 0.05 }

    enum CodingKeys: String, CodingKey {
        case id, start = "start_s", end = "end_s", title, what, watch, note, kind
    }
}

/// The changes sidecar. Written next to cuts.json by whoever made this cut
/// from the last one's notes (the edit-review-notes skill); the app only reads it.
struct ChangeList: Equatable {
    let changes: [Change]
    let round: String
    let previous: String?
    let summary: String?

    private struct Document: Codable {
        var schema: String
        var round: String?
        var previous: String?
        var summary: String?
        var duration: Double
        var changes: [Change]
        enum CodingKeys: String, CodingKey { case schema, round, previous, summary, duration = "duration_s", changes }
    }

    enum LoadResult {
        case loaded(ChangeList)
        case missing
        case rejected(String)
    }

    @MainActor static func sidecarURL(for video: URL) -> URL {
        ReviewStore.reviewDir(for: video).appendingPathComponent("changes.json")
    }

    @MainActor static func load(for video: URL, duration: Double) -> LoadResult {
        guard let data = try? Data(contentsOf: sidecarURL(for: video)) else { return .missing }
        guard let doc = try? JSONDecoder().decode(Document.self, from: data),
              doc.schema.hasPrefix("edit-review-changes/") else {
            return .rejected("changes.json is unreadable")
        }
        if abs(doc.duration - duration) > CutList.durationTolerance {
            return .rejected("changes.json is from a \(ReviewStore.mmss(doc.duration)) cut, this file is \(ReviewStore.mmss(duration))")
        }
        let list = doc.changes.map { c -> Change in
            var c = c
            c.start = max(0, min(c.start, duration)); c.end = max(c.start, min(c.end, duration))
            return c
        }.sorted { $0.start < $1.start }
        guard !list.isEmpty else { return .rejected("changes.json lists no changes") }
        return .loaded(ChangeList(changes: list, round: doc.round ?? "this cut", previous: doc.previous, summary: doc.summary))
    }

    /// Seconds either side of a removal that count as being on it.
    static let pointReach = 0.75
    /// A jump to a change starts this far before it, so the cut into it plays too.
    static let preroll = 1.0

    private func covers(_ c: Change, _ t: Double, lead: Double = 0, tail: Double = 0) -> Bool {
        let r = c.isPoint ? Self.pointReach : 0
        return t >= c.start - r - lead && t < max(c.end, c.start + r) + tail
    }

    /// The change playing at `seconds`: the shortest one that covers it (an audio
    /// tweak inside a re-cut shot wins over the shot).
    func change(at seconds: Double) -> Change? {
        changes.filter { covers($0, seconds) }.min { ($0.end - $0.start) < ($1.end - $1.start) }
    }

    /// The change a note stamped at `seconds` is about: the one playing, or the one that
    /// ended up to 2 s before (notes are stamped a beat after the moment).
    func change(near seconds: Double) -> Change? {
        change(at: seconds) ?? changes.filter { covers($0, seconds, tail: 2) }.last
    }

    func number(of id: String) -> Int? { changes.firstIndex { $0.id == id }.map { $0 + 1 } }

    /// The change ⌥↑ / ⌥↓ step from: the one the playhead is on, counting the
    /// pre-roll before it as on it.
    private func anchor(_ seconds: Double) -> Change? {
        changes.filter { covers($0, seconds, lead: Self.preroll + 0.1) }.max { $0.start < $1.start }
    }

    /// On `c` for stepping: inside it, or in the pre-roll a jump to it starts with.
    func isOn(_ c: Change, at seconds: Double) -> Bool { covers(c, seconds, lead: Self.preroll + 0.1) }

    func next(from seconds: Double) -> Change? {
        let from = anchor(seconds)?.start ?? seconds
        return changes.first { $0.start > from + 0.01 }
    }

    func previous(from seconds: Double) -> Change? {
        if let a = anchor(seconds) { return changes.last { $0.start < a.start - 0.01 } }
        return changes.last { $0.start < seconds - 0.01 }
    }
}

extension Color {
    /// The changes layer: bands, flags, the banner and the list.
    static let change = Color(red: 0.62, green: 0.38, blue: 0.96)
}
