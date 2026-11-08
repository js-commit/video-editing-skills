import Foundation

/// One flat stretch of the rendered file: the topmost full-frame clip of the
/// Resolve timeline between two edit points (or a gap). Times are file seconds.
struct Cut: Identifiable, Codable, Equatable {
    var index: Int
    var start: Double
    var end: Double
    var track: Int
    var name: String
    var kind: String

    var id: Int { index }
    var isGap: Bool { kind == "gap" }
    var length: Double { end - start }
    /// File frame numbers of the clip's first and last picture.
    func firstFrame(fps: Double) -> Int { Int((start * fps).rounded()) }
    func lastFrame(fps: Double) -> Int { max(firstFrame(fps: fps), Int((end * fps).rounded()) - 1) }

    enum CodingKeys: String, CodingKey {
        case index, start = "start_s", end = "end_s", track, name, kind
    }
}

/// `<stem>.review/cuts.json` (schema edit-review-cuts/1), written by
/// scripts/export_cuts.py — on every draft export, or on demand from
/// Review › Get Cuts from Resolve. The app only reads it.
struct CutList: Equatable {
    let cuts: [Cut]
    let project: String
    let timeline: String
    /// Every place the picture changes, plus 0 and the end of the last cut. Sorted.
    let boundaries: [Double]

    private struct Document: Codable {
        var schema: String
        var project: String?
        var timeline: String?
        var duration: Double
        var cuts: [Cut]
        enum CodingKeys: String, CodingKey { case schema, project, timeline, duration = "duration_s", cuts }
    }

    enum LoadResult {
        case loaded(CutList)
        case missing
        /// The sidecar is there but not for this file; the text says why.
        case rejected(String)
    }

    @MainActor static func sidecarURL(for video: URL) -> URL {
        ReviewStore.reviewDir(for: video).appendingPathComponent("cuts.json")
    }

    /// A container's duration differs from frames / fps by audio priming and
    /// rounding; a different cut differs by whole shots. Same 0.2 s as the script.
    static let durationTolerance = 0.2

    @MainActor static func load(for video: URL, duration: Double) -> LoadResult {
        guard let data = try? Data(contentsOf: sidecarURL(for: video)) else { return .missing }
        guard let doc = try? JSONDecoder().decode(Document.self, from: data),
              doc.schema.hasPrefix("edit-review-cuts/") else {
            return .rejected("cuts.json is unreadable")
        }
        if abs(doc.duration - duration) > durationTolerance {
            return .rejected("cuts.json is from a \(ReviewStore.mmss(doc.duration)) cut, this file is \(ReviewStore.mmss(duration))")
        }
        let cuts = doc.cuts.sorted { $0.start < $1.start }
        guard !cuts.isEmpty else { return .rejected("cuts.json lists no cuts") }
        var edges = cuts.map(\.start)
        edges.append(cuts[cuts.count - 1].end)
        return .loaded(CutList(cuts: cuts, project: doc.project ?? "", timeline: doc.timeline ?? "",
                               boundaries: edges))
    }

    /// The cut playing at `seconds` (binary search; called per playhead tick).
    func cut(at seconds: Double) -> Cut? {
        var lo = 0, hi = cuts.count - 1
        while lo <= hi {
            let mid = (lo + hi) / 2
            if seconds < cuts[mid].start { hi = mid - 1 }
            else if seconds >= cuts[mid].end { lo = mid + 1 }
            else { return cuts[mid] }
        }
        return seconds >= (cuts.last?.end ?? 0) ? cuts.last : nil
    }

    /// Last boundary strictly before `seconds` / first strictly after it.
    func boundary(before seconds: Double) -> Double? { boundaries.last { $0 < seconds } }
    func boundary(after seconds: Double) -> Double? { boundaries.first { $0 > seconds } }

    /// The boundary within `reach` seconds of `seconds`, if any — for the
    /// pointer's snap. The file's first and last frame do not pull.
    func boundary(near seconds: Double, reach: Double) -> Double? {
        let inner = boundaries.dropFirst().dropLast()
        guard let b = inner.min(by: { abs($0 - seconds) < abs($1 - seconds) }),
              abs(b - seconds) <= reach else { return nil }
        return b
    }

    /// The cuts on either side of a boundary: what ends there, what starts there.
    func around(_ boundary: Double) -> (outgoing: Cut?, incoming: Cut?) {
        (cuts.last { abs($0.end - boundary) < 1e-4 }, cuts.first { abs($0.start - boundary) < 1e-4 })
    }
}
