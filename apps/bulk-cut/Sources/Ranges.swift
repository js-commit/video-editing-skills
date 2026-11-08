import Foundation

/// One stretch of a clip to keep, in file seconds: [start, end). A clip with
/// any ranges is cropped to them on apply, one output file per range.
struct KeepRange: Codable, Equatable {
    var start: Double
    var end: Double
    /// Set on a range made by a crop key pressed in grey (dropped) space: the
    /// edge the user did not choose runs to the neighbouring range. The other
    /// crop key pressed inside it finishes it as a range of its own; any other
    /// edit settles it, and it joins that neighbour (it extended it).
    var open: Edge?
    /// Who proposed it (bulkcut.json): "beat", a clip of a sequence (teal),
    /// or "pick", a tool's pick (purple). nil for one the user made (yellow).
    /// Survives drags.
    var kind: String?
    /// Drawn on the range: "beat 3: lid off", "pick: …".
    var label: String?
    /// A "beat" range's sequence (the manifest's `sequences[].name`), for the
    /// focus filter (Focus.swift). nil: matched to the beats by file and time.
    /// Survives drags, like `kind`.
    var sequence: String?
    /// The user's description of what this range shows, typed in a review
    /// folder's description box (DescriptionBox.swift); nil until typed.
    /// It replaces the tool's (bulkcut-review.json carries it as `note`).
    /// Survives drags; joined ranges join their notes.
    var note: String?

    var length: Double { end - start }
}

enum Edge: String, Codable { case start, end }

/// What the user has staged for one file.
struct ClipEdit: Codable, Equatable {
    var deleted = false
    var ranges: [KeepRange] = []
    /// Quarter turns clockwise, 0–3: lossless (a video's track header, a
    /// JPEG, HEIC or TIFF's orientation tag).
    var turns = 0
    /// The part of the picture to keep, in the turned frame; nil for all of
    /// it. A video zooms into it, a photo is cropped to it.
    var zoom: ZoomRect?

    var isEmpty: Bool { !deleted && ranges.isEmpty && turns == 0 && zoom == nil }

    /// Turn `by` quarter turns clockwise (negative: anticlockwise); a zoom keeps its part of the picture.
    mutating func turn(by k: Int) {
        turns = ((turns + k) % 4 + 4) % 4
        zoom = zoom?.rotated(k)
    }
}

extension ClipEdit {
    private enum Legacy: String, CodingKey { case turned }

    /// Sessions saved before a field existed lack it; before photos, a turn was `turned: true`.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        deleted = try c.decodeIfPresent(Bool.self, forKey: .deleted) ?? false
        ranges = try c.decodeIfPresent([KeepRange].self, forKey: .ranges) ?? []
        turns = try c.decodeIfPresent(Int.self, forKey: .turns)
            ?? (try decoder.container(keyedBy: Legacy.self).decodeIfPresent(Bool.self, forKey: .turned) == true ? 2 : 0)
        zoom = try c.decodeIfPresent(ZoomRect.self, forKey: .zoom)
    }
}

/// The crop keys' rules, as pure functions of the ranges.
///
/// - Crop left (in point) at `t`, the start of the frame on screen: inside a
///   range it moves that range's start there. In grey space it starts a new
///   range running to the next range (or the end of the clip).
/// - Crop right (out point) at `t`, the end of the frame on screen: inside a
///   range it moves that range's end there. In grey space it ends a new range
///   that runs back to the previous range (or the start of the clip).
///
/// So Q / W on a fresh clip crop it from the left / right; Q … W, Q … W
/// pulls out several pieces; Q before the first piece (or W after the last)
/// with no second key extends that piece.
enum RangeOps {
    static let eps = 1e-4
    /// Shorter than this is no range at all.
    static let minLength = 0.01

    static func contains(_ r: KeepRange, _ t: Double) -> Bool { r.start <= t + eps && t < r.end - eps }
    /// For an out point (a frame's end): the range holds the frame that ends at `t`.
    static func holdsEnd(_ r: KeepRange, _ t: Double) -> Bool { r.start < t - eps && t <= r.end + eps }

    static func setIn(_ ranges: [KeepRange], at t: Double, duration: Double) -> [KeepRange] {
        var r = ranges
        if let i = r.firstIndex(where: { $0.open != nil && contains($0, t) }) {
            r[i].start = t
            if r[i].open == .start { r[i].open = nil }
            return tidy(r)
        }
        r = settle(r)
        if let i = r.firstIndex(where: { contains($0, t) }) {
            r[i].start = t
            return tidy(r)
        }
        let next = r.first { $0.start > t }
        r.append(KeepRange(start: t, end: next?.start ?? duration, open: next == nil ? nil : .end))
        return tidy(r)
    }

    static func setOut(_ ranges: [KeepRange], at t: Double, duration: Double) -> [KeepRange] {
        var r = ranges
        if let i = r.firstIndex(where: { $0.open != nil && holdsEnd($0, t) }) {
            r[i].end = t
            if r[i].open == .end { r[i].open = nil }
            return tidy(r)
        }
        r = settle(r)
        if let i = r.firstIndex(where: { holdsEnd($0, t) }) {
            r[i].end = t
            return tidy(r)
        }
        let prev = r.last { $0.end <= t + eps }
        r.append(KeepRange(start: prev?.end ?? 0, end: t, open: prev == nil ? nil : .start))
        return tidy(r)
    }

    /// Drop the range under `t`; nil when there is none.
    static func remove(_ ranges: [KeepRange], at t: Double) -> [KeepRange]? {
        var r = settle(ranges)
        guard let i = r.firstIndex(where: { contains($0, t) }) else { return nil }
        r.remove(at: i)
        return r
    }

    /// Final form: an open range joins the neighbour it runs into, overlaps
    /// merge, flags clear. What apply exports and what the clip list counts.
    static func settle(_ ranges: [KeepRange]) -> [KeepRange] {
        var out: [KeepRange] = []
        for x in ranges.sorted(by: { $0.start < $1.start }) where x.length >= minLength {
            if var last = out.last {
                let joined = abs(x.start - last.end) < eps && (last.open == .end || x.open == .start)
                if x.start < last.end - eps || joined {
                    // A Q in the grey before a teal or purple range extends
                    // it: it stays that range (turning it yellow would lose
                    // what it was proposed as).
                    if last.open != nil, x.open == nil {
                        (last.kind, last.label, last.sequence, last.note) = (x.kind, x.label, x.sequence, x.note)
                    }
                    last.end = max(last.end, x.end)
                    out[out.count - 1] = last
                    continue
                }
            }
            out.append(x)
        }
        return out.map { var y = $0; y.open = nil; return y }
    }

    /// Sorted, overlaps merged, slivers dropped; open flags kept.
    static func tidy(_ ranges: [KeepRange]) -> [KeepRange] {
        var out: [KeepRange] = []
        for x in ranges.sorted(by: { $0.start < $1.start }) where x.length >= minLength {
            if var last = out.last, x.start < last.end - eps {
                last.end = max(last.end, x.end)
                last.open = nil
                out[out.count - 1] = last
                continue
            }
            out.append(x)
        }
        return out
    }

    /// Shorter than this, a range is one the user shrank away: an edge dragged
    /// onto the other one deletes the range.
    static let shrunk = 0.1
    /// Closer than this, two ranges are one: an edge dragged onto the next
    /// range joins them. Sequence clips (teal) join sequence clips,
    /// everything else everything else; a pick joined to one of the user's
    /// becomes the user's. Tools reading bulkcut-review.json get the ranges
    /// already tidied this way.
    static let joinGap = 0.05

    /// Shrunk ranges dropped, touching ones joined (labels "a + b", notes one after the other).
    static func tidyDrag(_ ranges: [KeepRange]) -> [KeepRange] {
        var out: [KeepRange] = []
        for x in ranges.sorted(by: { $0.start < $1.start }) where x.length >= shrunk {
            if var last = out.last, last.open == nil, x.open == nil, x.start - last.end < joinGap,
               (last.kind == "beat") == (x.kind == "beat") {
                last.end = max(last.end, x.end)
                if last.kind != x.kind { last.kind = nil }
                last.sequence = last.kind == "beat" ? last.sequence ?? x.sequence : nil
                let labels = [last.label, x.label].compactMap { $0 }
                last.label = labels.isEmpty ? nil : labels.joined(separator: " + ")
                let notes = [last.note, x.note].compactMap { $0 }
                last.note = notes.isEmpty ? nil : notes.joined(separator: " ")
                out[out.count - 1] = last
                continue
            }
            out.append(x)
        }
        return out
    }

    /// Every range edge, sorted, for the jump-to-edge keys.
    static func edges(_ ranges: [KeepRange]) -> [Double] {
        settle(ranges).flatMap { [$0.start, $0.end] }
    }

    /// Kept seconds once settled.
    static func keptLength(_ ranges: [KeepRange]) -> Double {
        settle(ranges).reduce(0) { $0 + $1.length }
    }

    /// One range over the whole file (to within `slack`): cropping to it changes nothing.
    static func isWhole(_ ranges: [KeepRange], duration: Double, slack: Double) -> Bool {
        let r = settle(ranges)
        return r.count == 1 && r[0].start <= slack && r[0].end >= duration - slack
    }

    /// Move one edge of settled range `i` to `t`, kept between its neighbours
    /// and at least `minLength` long.
    static func moveEdge(_ ranges: [KeepRange], index i: Int, edge: Edge, to t: Double, duration: Double) -> [KeepRange] {
        guard ranges.indices.contains(i) else { return ranges }
        var r = ranges
        switch edge {
        case .start:
            let lo = i > 0 ? r[i - 1].end : 0
            r[i].start = min(max(t, lo), r[i].end - minLength)
        case .end:
            let hi = i + 1 < r.count ? r[i + 1].start : duration
            r[i].end = max(min(t, hi), r[i].start + minLength)
        }
        return r
    }
}
