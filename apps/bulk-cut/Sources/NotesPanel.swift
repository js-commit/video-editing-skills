import SwiftUI

/// Over the video: what the folder's bulkcut.json says about the selected
/// clip — the privacy note first (it decides a delete), then the description
/// and who wrote it, why it was picked, what was said over it, the annotated
/// segment under the playhead, and where it was cut from. As tall as its
/// text up to a cap, then it scrolls. ⌘I hides it.
struct NotesPanel: View {
    let notes: ClipNotes
    let player: PlayerModel
    var libraryLabel = "In library"
    @State private var contentHeight: CGFloat = 0

    var body: some View {
        ScrollView {
            content
                .padding(.horizontal, 12).padding(.vertical, 8)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(GeometryReader { g in
                    Color.clear.preference(key: HeightKey.self, value: g.size.height)
                })
        }
        .frame(height: min(max(contentHeight, 1), 180))
        .onPreferenceChange(HeightKey.self) { contentHeight = $0 }
    }

    private var content: some View {
        VStack(alignment: .leading, spacing: 6) {
            if let p = notes.privacy {
                line(icon: "exclamationmark.triangle.fill", label: "Privacy", color: .orange, text: p, strong: true)
            }
            if !notes.taken.isEmpty {
                let total = notes.taken.reduce(0) { $0 + $1.end - $1.start }
                line(icon: "checkmark.rectangle.stack", label: libraryLabel, color: .orange,
                     text: String(format: "%.1f s in %d range%@ (orange on the timeline, don't cut it again): ",
                                  total, notes.taken.count, notes.taken.count == 1 ? "" : "s")
                        + notes.taken.map { "\(Format.clock($0.start))–\(Format.clock($0.end))" }.joined(separator: ", "))
            }
            if let d = notes.description {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    noteBadge(notes.annotatorLabel ?? "note", color: .purple)
                        .help(notes.annotator.map { "Written by \($0)" } ?? "")
                    Text(d).font(.system(size: 13)).textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            if let meta = meta {
                Text(meta).font(.system(size: 11)).foregroundStyle(.secondary)
            }
            if let w = notes.why { line(icon: "hand.point.right", label: "Why picked", color: .secondary, text: w) }
            if let s = notes.said { line(icon: "quote.bubble", label: "Said over it", color: .secondary, text: s) }
            if !notes.segments.isEmpty { SegmentLine(notes: notes, player: player) }
            if let o = notes.origin { line(icon: "film", label: "Cut from", color: .secondary, text: o) }
        }
    }

    private var meta: String? {
        var parts: [String] = []
        if !notes.quality.isEmpty { parts.append(notes.quality.joined(separator: ", ")) }
        if !notes.tags.isEmpty { parts.append(notes.tags.map { "#" + $0 }.joined(separator: " ")) }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    private func line(icon: String, label: String, color: Color, text: String, strong: Bool = false) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 6) {
            Label(label, systemImage: icon)
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(color)
                .fixedSize()
            Text(text)
                .font(.system(size: 12, weight: strong ? .medium : .regular))
                .foregroundStyle(strong ? Color.orange : Color.primary.opacity(0.85))
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private struct HeightKey: PreferenceKey {
        static let defaultValue: CGFloat = 0
        static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) { value = max(value, nextValue()) }
    }
}

func noteBadge(_ text: String, color: Color) -> some View {
    Text(text)
        .font(.system(size: 10, weight: .bold))
        .padding(.horizontal, 6).padding(.vertical, 1)
        .background(color.opacity(0.22), in: Capsule())
        .foregroundStyle(color == .gray ? Color.secondary : color)
}

/// A speed is baked into the file, so it plays slow (or fast) at 1×:
/// a tortoise (hare) and "Slowed to 40%", or just "40%" over a thumbnail.
struct SpeedChip: View {
    let speed: Double
    var onVideo = false

    var body: some View {
        let pct = "\(Int((speed * 100).rounded()))%"
        HStack(spacing: 3) {
            Image(systemName: speed < 1 ? "tortoise.fill" : "hare.fill")
            Text(onVideo ? pct : (speed < 1 ? "Slowed to " : "Sped up to ") + pct)
        }
        .font(.system(size: onVideo ? 10 : 11, weight: .bold))
        .padding(.horizontal, 6).padding(.vertical, onVideo ? 1 : 2)
        .background(Color.orange.opacity(onVideo ? 0.9 : 0.2), in: Capsule())
        .foregroundStyle(onVideo ? Color.white : Color.orange)
        .help("This file itself plays at \(pct) speed: it was cut with the speed it had in an edit")
    }
}

/// The annotated segment under the playhead; the only part of the panel
/// that follows the playhead, so only it redraws as the clip plays.
struct SegmentLine: View {
    let notes: ClipNotes
    @ObservedObject var player: PlayerModel

    var body: some View {
        let n = notes.segments.count
        let cur = notes.segment(at: player.currentSeconds)
        HStack(alignment: .firstTextBaseline, spacing: 6) {
            Label(cur.map { "Segment \($0.index + 1)/\(n)" } ?? "\(n) segments", systemImage: "rectangle.split.3x1")
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(.teal)
                .fixedSize()
                .help("Segments from bulkcut.json")
            if let (_, s) = cur {
                Text("\(Format.clock(s.start))–\(Format.clock(s.end))")
                    .font(.system(size: 11, design: .monospaced)).foregroundStyle(.secondary)
                    .fixedSize()
                Text(text(s))
                    .font(.system(size: 12)).foregroundStyle(Color.primary.opacity(0.85))
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                Text("none under the playhead").font(.system(size: 12)).foregroundStyle(.secondary)
            }
        }
    }

    private func text(_ s: ClipNotes.Segment) -> String {
        var t = s.description
        var extra: [String] = []
        if let q = s.quality { extra.append(q) }
        if s.shaky { extra.append("shaky") }
        if !extra.isEmpty { t += "  (\(extra.joined(separator: ", ")))" }
        if let note = s.note { t += "  — note: \(note)" }
        return t
    }
}

/// What the library already holds: an orange wash over the waveform with an
/// "in library" tag, so a review leaves those stretches alone.
struct TakenCanvas: View, Equatable {
    let taken: [ClipNotes.Taken]
    let start: Double
    let length: Double
    let waveHeight: CGFloat
    /// Outside a review folder's focus: drawn faint, as it is skipped.
    var faded = false
    var label = "in library"

    var body: some View {
        Canvas(rendersAsynchronously: false) { ctx, size in
            guard !taken.isEmpty, length > 0 else { return }
            let w = size.width
            let toX = { (s: Double) -> CGFloat in CGFloat((s - start) / length) * w }
            for t in taken {
                let x0 = max(toX(t.start), 0), x1 = min(toX(t.end), w)
                guard x1 > x0 else { continue }
                let r = CGRect(x: x0, y: 0, width: max(1, x1 - x0), height: waveHeight)
                let k = faded ? 0.35 : 1
                ctx.fill(Path(r), with: .color(.orange.opacity(0.28 * k)))
                var edges = Path()
                edges.move(to: CGPoint(x: x0, y: 0)); edges.addLine(to: CGPoint(x: x0, y: waveHeight))
                edges.move(to: CGPoint(x: x1, y: 0)); edges.addLine(to: CGPoint(x: x1, y: waveHeight))
                ctx.stroke(edges, with: .color(.orange.opacity(0.9 * k)), lineWidth: 1)
                if x1 - x0 > 54 {
                    ctx.draw(Text(label).font(.system(size: 9, weight: .bold)).foregroundColor(.orange.opacity(k)),
                             at: CGPoint(x: x0 + 4, y: 3), anchor: .topLeading)
                }
            }
        }
    }
}

/// The annotated segments as a strip along the bottom of the waveform,
/// alternating shades so the boundaries read; poor ones red.
struct SegmentsCanvas: View, Equatable {
    let segments: [ClipNotes.Segment]
    let start: Double
    let length: Double
    let waveHeight: CGFloat

    var body: some View {
        Canvas(rendersAsynchronously: false) { ctx, size in
            guard !segments.isEmpty, length > 0 else { return }
            let w = size.width
            let toX = { (s: Double) -> CGFloat in CGFloat((s - start) / length) * w }
            var bounds = Path()
            for (i, s) in segments.enumerated() {
                let x0 = toX(s.start), x1 = toX(s.end)
                guard x1 > 0, x0 < w else { continue }
                let color: Color = s.quality == "poor" ? .red : .teal
                ctx.fill(Path(CGRect(x: x0 + 0.5, y: waveHeight - 9, width: max(1, x1 - x0 - 1), height: 5)),
                         with: .color(color.opacity(i % 2 == 0 ? 0.8 : 0.45)))
                if i > 0 {
                    bounds.move(to: CGPoint(x: x0, y: 12))
                    bounds.addLine(to: CGPoint(x: x0, y: waveHeight - 4))
                }
            }
            ctx.stroke(bounds, with: .color(.teal.opacity(0.35)), style: StrokeStyle(lineWidth: 1, dash: [3, 3]))
        }
    }
}
