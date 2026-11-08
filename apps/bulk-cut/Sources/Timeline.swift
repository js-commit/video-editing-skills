import AppKit
import SwiftUI

/// Which stretch of the clip the timeline shows. The whole clip by default;
/// zoomed (⌃E / ⌃W, or the scroll wheel over it) it shows a window that
/// pages along with the playhead. ⇧scroll moves the window.
@MainActor
final class TimelineState: ObservableObject {
    @Published private(set) var zoomWindow: Double?
    @Published private(set) var viewStart: Double = 0
    /// The pointer over the timeline: fraction across, width in points.
    var hover: (fraction: Double, width: Double)?
    /// Scrolled away from the playhead by hand: do not page back while playing.
    private var scrolledAway = false
    static let minWindow = 0.5

    func reset() {
        zoomWindow = nil
        viewStart = 0
        scrolledAway = false
    }

    func window(duration: Double) -> (start: Double, length: Double) {
        let full = max(duration, 0.001)
        guard let len = zoomWindow, len < full else { return (0, full) }
        return (clamp(viewStart, len, duration), len)
    }

    private func clamp(_ start: Double, _ window: Double, _ duration: Double) -> Double {
        min(max(0, start), max(0, duration - window))
    }

    static func span(_ s: Double) -> String { s < 60 ? String(format: "%.1f s", s) : Format.duration(s) }

    func zoomIn(around t: Double, duration: Double) -> String {
        guard duration > 0 else { return "" }
        let cur = zoomWindow ?? duration
        let next = max(cur / 2, Self.minWindow)
        guard next < cur else { return "Zoomed all the way in" }
        zoomWindow = next
        viewStart = clamp(t - next / 2, next, duration)
        return "Timeline: \(Self.span(next)) across"
    }

    func zoomOut(around t: Double, duration: Double) -> String {
        guard let cur = zoomWindow else { return "Whole clip shown" }
        let next = cur * 2
        if next >= duration { reset(); return "Whole clip shown" }
        zoomWindow = next
        viewStart = clamp(t - next / 2, next, duration)
        return "Timeline: \(Self.span(next)) across"
    }

    /// As the playhead moves: page the window when it runs off an end.
    func follow(_ t: Double, playing: Bool, duration: Double) {
        guard let len = zoomWindow else { return }
        if scrolledAway {
            if t >= viewStart, t <= viewStart + len { scrolledAway = false }
            else if playing { return }
        }
        if t < viewStart || t > viewStart + len {
            scrolledAway = false
            viewStart = clamp(t - len * 0.15, len, duration)
        }
    }

    /// The scroll wheel over the timeline: plain zooms around the pointer,
    /// ⇧ (or a sideways swipe) moves along. True when it was ours.
    func scroll(_ e: NSEvent, duration: Double, playhead: Double) -> Bool {
        guard let hover else { return false }
        let precise = e.hasPreciseScrollingDeltas
        var dx = Double(e.scrollingDeltaX), dy = Double(e.scrollingDeltaY)
        if e.modifierFlags.contains(.shift), dx == 0 { dx = dy }
        let pan = e.modifierFlags.contains(.shift) || abs(dx) > abs(dy)
        let win = window(duration: duration)
        if pan {
            guard zoomWindow != nil, dx != 0 else { return true }
            let points = precise ? dx : dx * 12
            viewStart = clamp(win.start - points / max(hover.width, 1) * win.length, win.length, duration)
        } else {
            guard dy != 0 else { return true }
            let next = min(max(win.length * exp(-dy * (precise ? 0.01 : 0.12)), Self.minWindow), duration)
            guard next != win.length else { return true }
            if next >= duration {
                zoomWindow = nil
                viewStart = 0
            } else {
                let anchor = win.start + hover.fraction * win.length
                zoomWindow = next
                viewStart = clamp(anchor - hover.fraction * next, next, duration)
            }
        }
        scrolledAway = zoomWindow != nil && (playhead < viewStart || playhead > viewStart + (zoomWindow ?? duration))
        return true
    }
}

/// Under the video: the waveform with a time ruler, the kept ranges over it
/// (what goes is greyed out, what stays has yellow brackets), and the scrub
/// bar with the playhead. Click / drag seeks; dragging a bracket moves that
/// edge, frame by frame, with the picture following it.
struct ClipTimeline: View {
    @ObservedObject var model: AppModel
    @ObservedObject var player: PlayerModel
    @ObservedObject var timeline: TimelineState
    @ObservedObject var waveform: WaveformModel
    @State private var drag: DragKind?
    @State private var hoverEdge = false

    private enum DragKind { case scrub, edge }

    init(model: AppModel) {
        self.model = model
        self.player = model.player
        self.timeline = model.timeline
        self.waveform = model.player.waveform
    }

    private let waveHeight: CGFloat = 84
    private let barHeight: CGFloat = 22
    private var height: CGFloat { waveHeight + barHeight }
    /// How close, in points, the pointer must be to grab a range edge.
    private let edgeReach: CGFloat = 6

    var body: some View {
        let ranges = model.selectedLoaded ? model.selectedEdit.ranges : []
        let segments = model.selectedLoaded ? (model.selected.flatMap { model.notes[$0.key]?.segments } ?? []) : []
        let taken = model.selectedLoaded ? (model.selected.flatMap { model.notes[$0.key]?.taken } ?? []) : []
        let takenLabel = model.reviewFolder?.legend.library ?? "in library"
        // With a focus, the ranges outside it are drawn dimmed (still draggable).
        let lit: [Bool] = model.focus == .everything ? [] : model.selected.map { c in ranges.map { model.inFocus($0, c) } } ?? []
        GeometryReader { geo in
            let w = max(geo.size.width, 1)
            let win = timeline.window(duration: player.duration)
            let toX = { (s: Double) -> CGFloat in CGFloat((s - win.start) / win.length) * w }
            let toSeconds = { (x: CGFloat) -> Double in
                min(max(win.start + Double(min(max(x, 0), w) / w) * win.length, 0), max(player.duration, 0))
            }
            let barY = waveHeight + barHeight / 2

            ZStack(alignment: .topLeading) {
                WaveformCanvas(peaks: waveform.peaks, bucket: WaveformModel.bucket,
                               start: win.start, length: win.length, building: waveform.building)
                    .equatable()
                    .frame(width: w, height: waveHeight)
                    .clipShape(RoundedRectangle(cornerRadius: 4))

                TakenCanvas(taken: taken, start: win.start, length: win.length, waveHeight: waveHeight,
                            faded: model.focus != .everything, label: takenLabel)
                    .equatable()
                    .frame(width: w, height: waveHeight)
                    .allowsHitTesting(false)

                SegmentsCanvas(segments: segments, start: win.start, length: win.length, waveHeight: waveHeight)
                    .equatable()
                    .frame(width: w, height: waveHeight)
                    .allowsHitTesting(false)

                Capsule().fill(Color.secondary.opacity(0.22)).frame(width: w, height: 6)
                    .position(x: w / 2, y: barY)

                RangesCanvas(ranges: ranges, start: win.start, length: win.length, duration: player.duration,
                             waveHeight: waveHeight, barHeight: barHeight, dim: model.reviewFolder != nil ? 0.3 : 0.55,
                             lit: lit)
                    .equatable()
                    .frame(width: w, height: height)
                    .allowsHitTesting(false)

                let px = toX(player.currentSeconds)
                if player.loadedURL != nil, px >= 0, px <= w {
                    Rectangle().fill(Color.primary.opacity(0.85))
                        .frame(width: 1.5, height: waveHeight)
                        .position(x: px, y: waveHeight / 2)
                    Circle().fill(Color.primary)
                        .frame(width: 12, height: 12)
                        .shadow(radius: 1)
                        .position(x: px, y: barY)
                }

                if timeline.zoomWindow != nil {
                    Text("\(TimelineState.span(win.length)) across · scroll / \(model.keymap.label(.zoomIn)) / \(model.keymap.label(.zoomOut)) · ⇧scroll moves")
                        .font(.system(size: 10, weight: .medium, design: .monospaced))
                        .foregroundStyle(.secondary)
                        .padding(.horizontal, 5).padding(.vertical, 1)
                        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 3))
                        .padding(4)
                        .frame(width: w, alignment: .topTrailing)
                }

                if player.waveformDeferred {
                    Button("Build waveform (network file)") { player.buildWaveform() }
                        .controlSize(.small)
                        .frame(width: w, height: waveHeight)
                }
            }
            .frame(width: w, height: height)
            .contentShape(Rectangle())
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { v in
                        guard player.loadedURL != nil else { return }
                        if drag == nil {
                            if let hit = edgeHit(v.startLocation.x, ranges: ranges, toX: toX) {
                                drag = .edge
                                model.beginEdgeDrag(index: hit.index, edge: hit.edge)
                            } else {
                                drag = .scrub
                            }
                        }
                        if drag == .edge { model.dragEdge(to: toSeconds(v.location.x)) }
                        else { player.scrub(to: toSeconds(v.location.x)) }
                    }
                    .onEnded { v in
                        if drag == .edge { model.endEdgeDrag() }
                        else if drag == .scrub { player.endScrub(at: toSeconds(v.location.x)) }
                        drag = nil
                    }
            )
            .onContinuousHover { phase in
                switch phase {
                case .active(let p):
                    timeline.hover = (Double(min(max(p.x, 0), w) / w), Double(w))
                    let near = edgeHit(p.x, ranges: ranges, toX: toX) != nil
                    if near != hoverEdge {
                        hoverEdge = near
                        (near ? NSCursor.resizeLeftRight : NSCursor.arrow).set()
                    }
                case .ended:
                    timeline.hover = nil
                    if hoverEdge { hoverEdge = false; NSCursor.arrow.set() }
                }
            }
            .onChange(of: player.currentSeconds) { _, t in
                timeline.follow(t, playing: player.isPlaying, duration: player.duration)
            }
        }
        .frame(height: height)
        .help("click / drag: seek · drag a yellow edge: move it · scroll / \(model.keymap.label(.zoomIn)) / \(model.keymap.label(.zoomOut)): zoom around the playhead · ⇧scroll: move along")
    }

    private func edgeHit(_ x: CGFloat, ranges: [KeepRange], toX: (Double) -> CGFloat) -> (index: Int, edge: Edge)? {
        var best: (index: Int, edge: Edge, d: CGFloat)?
        for (i, r) in RangeOps.settle(ranges).enumerated() {
            for (edge, t) in [(Edge.start, r.start), (Edge.end, r.end)] {
                let d = abs(toX(t) - x)
                if d <= edgeReach, d < (best?.d ?? .infinity) { best = (i, edge, d) }
            }
        }
        return best.map { ($0.index, $0.edge) }
    }
}

/// The kept ranges over the waveform and bar: dropped stretches darkened,
/// kept ones bracketed in yellow (an open range — waiting for its other key —
/// paler, its open edge dashed), numbered when there are several. Redrawn
/// only when the ranges or the window change.
extension KeepRange {
    /// Yellow for the user's own ranges; teal for a proposed sequence clip
    /// and purple for a proposed pick (`kind`, from bulkcut.json).
    var tint: Color {
        switch kind {
        case "beat": Color(red: 0.2, green: 0.8, blue: 0.8)
        case "pick": Color(red: 0.72, green: 0.45, blue: 1)
        default: Color(red: 1, green: 0.8, blue: 0.1)
        }
    }
}

struct RangesCanvas: View, Equatable {
    let ranges: [KeepRange]
    let start: Double
    let length: Double
    let duration: Double
    let waveHeight: CGFloat
    let barHeight: CGFloat
    /// How dark the dropped stretches are; a review folder dims them less
    /// (the grey reads too harsh next to the coloured ranges).
    var dim = 0.55
    /// Per range, is it in the focus (AppModel.focus)? Those that are not are
    /// drawn faint. Empty: every range is.
    var lit: [Bool] = []

    /// How strongly a range is drawn: 1, or faint outside the focus.
    private func strength(_ r: KeepRange) -> Double {
        guard !lit.isEmpty, let i = ranges.firstIndex(where: { abs($0.start - r.start) < RangeOps.eps }),
              lit.indices.contains(i) else { return 1 }
        return lit[i] ? 1 : 0.3
    }

    var body: some View {
        Canvas(rendersAsynchronously: false) { ctx, size in
            guard !ranges.isEmpty, length > 0 else { return }
            let w = size.width, h = size.height
            let toX = { (s: Double) -> CGFloat in CGFloat((s - start) / length) * w }
            let settled = RangeOps.settle(ranges)

            var cursor = 0.0
            var gaps: [(Double, Double)] = []
            for r in settled {
                if r.start > cursor { gaps.append((cursor, r.start)) }
                cursor = max(cursor, r.end)
            }
            if cursor < duration { gaps.append((cursor, duration)) }
            for (a, b) in gaps {
                let x0 = max(toX(a), 0), x1 = min(toX(b), w)
                guard x1 > x0 else { continue }
                ctx.fill(Path(CGRect(x: x0, y: 0, width: x1 - x0, height: h)), with: .color(.black.opacity(dim)))
                var hatch = Path()
                var x = x0 - h
                while x < x1 {
                    hatch.move(to: CGPoint(x: x, y: h))
                    hatch.addLine(to: CGPoint(x: x + h, y: 0))
                    x += 9
                }
                var inner = ctx
                inner.clip(to: Path(CGRect(x: x0, y: 0, width: x1 - x0, height: h)))
                inner.stroke(hatch, with: .color(.white.opacity(0.06)), lineWidth: 1)
            }

            for r in ranges {
                let x0 = toX(r.start), x1 = toX(r.end)
                guard x1 >= -4, x0 <= w + 4 else { continue }
                let yellow = r.tint.opacity(strength(r))
                let pale = r.open != nil
                let bar = CGRect(x: x0, y: waveHeight + barHeight / 2 - 3, width: max(1, x1 - x0), height: 6)
                ctx.fill(Path(roundedRect: bar, cornerRadius: 3), with: .color(yellow.opacity(pale ? 0.45 : 0.95)))
                ctx.fill(Path(CGRect(x: x0, y: 0, width: x1 - x0, height: 2)), with: .color(yellow.opacity(pale ? 0.4 : 0.9)))
                ctx.fill(Path(CGRect(x: x0, y: waveHeight - 2, width: x1 - x0, height: 2)),
                         with: .color(yellow.opacity(pale ? 0.4 : 0.9)))
                for (edge, x) in [(Edge.start, x0), (Edge.end, x1)] {
                    let open = r.open == edge
                    var line = Path()
                    line.move(to: CGPoint(x: x, y: 0))
                    line.addLine(to: CGPoint(x: x, y: h))
                    ctx.stroke(line, with: .color(yellow.opacity(open ? 0.55 : 1)),
                               style: StrokeStyle(lineWidth: open ? 1.5 : 2.5, dash: open ? [4, 3] : []))
                    guard !open else { continue }
                    // Bracket tabs pointing into the kept side.
                    let dir: CGFloat = edge == .start ? 1 : -1
                    for y in [CGFloat(0), waveHeight - 4] {
                        ctx.fill(Path(CGRect(x: dir > 0 ? x : x - 8, y: y, width: 8, height: 4)), with: .color(yellow))
                    }
                }
            }

            if settled.count > 1 || settled.contains(where: { $0.label != nil || $0.note != nil }) {
                for (i, r) in settled.enumerated() {
                    let x0 = max(toX(r.start), 0), x1 = min(toX(r.end), w)
                    guard x1 - x0 > 22 else { continue }
                    let label = Text("\(i + 1)").font(.system(size: 11, weight: .bold, design: .rounded))
                        .foregroundStyle(Color.black)
                    let chip = CGRect(x: x0 + 5, y: waveHeight - 22, width: 16, height: 15)
                    let tint = r.tint.opacity(strength(r))
                    ctx.fill(Path(roundedRect: chip, cornerRadius: 3), with: .color(tint))
                    ctx.draw(label, at: CGPoint(x: chip.midX, y: chip.midY), anchor: .center)
                    // A proposed range says what it is: "beat 3: lid off";
                    // one the user described, their words (✎).
                    if let text = r.note.map({ "✎ " + $0 }) ?? r.label, x1 - x0 > 60 {
                        ctx.draw(Text(text).font(.system(size: 10, weight: .semibold)).foregroundColor(tint),
                                 in: CGRect(x: x0 + 25, y: waveHeight - 21, width: x1 - x0 - 30, height: 13))
                    }
                }
            }
        }
    }
}

/// The waveform itself plus a time ruler, drawn once per (peaks, window)
/// change — Equatable so the per-tick playhead redraws leave it alone
/// (Array == is an identity check first, so comparing the peaks is cheap).
struct WaveformCanvas: View, Equatable {
    let peaks: [Float]
    let bucket: Double
    let start: Double
    let length: Double
    let building: Bool

    static func == (a: Self, b: Self) -> Bool {
        a.peaks == b.peaks && a.start == b.start && a.length == b.length && a.building == b.building
    }

    var body: some View {
        Canvas(rendersAsynchronously: false) { ctx, size in
            let w = size.width, h = size.height
            ctx.fill(Path(CGRect(origin: .zero, size: size)), with: .color(.secondary.opacity(0.08)))
            let mid = h * 0.56          // ruler labels sit in the top strip
            let amp = h * 0.42
            let secondsPerPx = length / Double(w)
            var bars = Path()
            let columns = Int(w.rounded(.up))
            for col in 0..<columns {
                let t0 = start + Double(col) * secondsPerPx
                let t1 = t0 + secondsPerPx
                let k0 = max(0, Int(t0 / bucket))
                let k1 = max(k0, Int(t1 / bucket))
                guard k0 < peaks.count else { break }
                var p: Float = 0
                var k = k0
                while k <= k1, k < peaks.count { if peaks[k] > p { p = peaks[k] }; k += 1 }
                let half = max(0.5, CGFloat(p) * amp)
                bars.addRect(CGRect(x: CGFloat(col), y: mid - half, width: 1, height: half * 2))
            }
            ctx.fill(bars, with: .color(.accentColor.opacity(0.55)))
            if building {
                let doneX = CGFloat((Double(peaks.count) * bucket - start) / length) * w
                if doneX < w {
                    let text = Text("building waveform…").font(.system(size: 10)).foregroundStyle(.secondary)
                    ctx.draw(text, at: CGPoint(x: min(max(doneX + 6, 6), w - 60), y: mid), anchor: .leading)
                }
            }
            // Ruler: ticks every `step` seconds, ~80 px apart or more.
            let steps: [Double] = [0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600]
            let step = steps.first { $0 / secondsPerPx >= 80 } ?? 3600
            var ticks = Path()
            var t = (start / step).rounded(.up) * step
            while t <= start + length {
                let x = CGFloat((t - start) / length) * w
                ticks.move(to: CGPoint(x: x, y: 0))
                ticks.addLine(to: CGPoint(x: x, y: 8))
                let label = Text(Self.label(t, step: step))
                    .font(.system(size: 9, weight: .medium, design: .monospaced))
                    .foregroundStyle(.secondary)
                ctx.draw(label, at: CGPoint(x: x + 3, y: 2), anchor: .topLeading)
                t += step
            }
            ctx.stroke(ticks, with: .color(.secondary.opacity(0.6)), lineWidth: 1)
        }
    }

    private static func label(_ t: Double, step: Double) -> String {
        let m = Int(t) / 60
        let s = t - Double(m * 60)
        if step < 1 { return String(format: "%d:%04.1f", m, s) }
        return String(format: "%d:%02d", m, Int(s.rounded()))
    }
}
