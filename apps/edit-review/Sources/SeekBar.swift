import AVFoundation
import SwiftUI

/// The timeline under the transport: an audio waveform with a time ruler
/// over the scrub bar (played portion, playhead, a tick per note — a click
/// on one selects it and jumps there). Hover shows the timecode and a small
/// thumbnail, click / drag anywhere seeks. ⌃E / ⌃W zoom the whole strip in
/// and out around the playhead; the window then pages along with it. The
/// scroll wheel over it zooms around the pointer, ⇧scroll moves it along.
///
/// With a cuts sidecar there is a clip strip between the two: one block per
/// clip, carrying the clip's first frame at its left end and its last frame at
/// its right end (only the first when there is room for one, none when there
/// is room for neither — ⌃E makes room), and a line through the waveform at
/// every cut. A click or drag snaps to a cut within a few points of it (⌥
/// held: no snap); the hover thumbnail always follows the pointer itself.
/// ↑ / ↓ put the playhead on the previous / next cut.
struct SeekBar: View {
    @ObservedObject var controller: ReviewController
    @ObservedObject var player: PlayerModel
    @ObservedObject var store: ReviewStore
    @ObservedObject var waveform: WaveformModel

    @State private var hoverX: CGFloat?
    @State private var thumb: CGImage?
    @State private var thumbTask: Task<Void, Never>?

    init(controller: ReviewController, player: PlayerModel, store: ReviewStore) {
        self.controller = controller
        self.player = player
        self.store = store
        self.waveform = player.waveform
    }

    private let waveHeight: CGFloat = 64
    private let barHeight: CGFloat = 24
    private var stripHeight: CGFloat { controller.cuts == nil ? 0 : 72 }
    private var height: CGFloat { waveHeight + stripHeight + barHeight }
    private let previewSize = CGSize(width: 192, height: 108)
    /// How close, in points, the pointer has to be for a cut to pull it in.
    private let snapReach: CGFloat = 7

    var body: some View {
        GeometryReader { geo in
            let w = max(geo.size.width, 1)
            let win = controller.visibleWindow
            let toX = { (s: Double) -> CGFloat in CGFloat((s - win.start) / win.length) * w }
            let toSeconds = { (x: CGFloat) -> Double in
                min(max(win.start + Double(min(max(x, 0), w) / w) * win.length, 0), max(player.duration, 0))
            }
            let barY = waveHeight + stripHeight + barHeight / 2
            let snap = { (x: CGFloat) -> (seconds: Double, boundary: Double?) in
                controller.snapped(toSeconds(x), reach: Double(snapReach / w) * win.length)
            }

            ZStack(alignment: .topLeading) {
                WaveformCanvas(peaks: waveform.peaks, bucket: WaveformModel.bucket,
                               start: win.start, length: win.length, building: waveform.building)
                    .equatable()
                    .frame(width: w, height: waveHeight)
                    .clipShape(RoundedRectangle(cornerRadius: 4))

                if let cuts = controller.cuts {
                    CutsCanvas(cuts: cuts.cuts, start: win.start, length: win.length,
                               current: cuts.cut(at: player.currentSeconds)?.index,
                               waveHeight: waveHeight, stripHeight: stripHeight,
                               thumbsVersion: player.thumbsVersion, player: player)
                        .equatable()
                        .frame(width: w, height: waveHeight + stripHeight)
                        .allowsHitTesting(false)
                }

                if let ch = controller.changes {
                    ChangesCanvas(changes: ch.changes, start: win.start, length: win.length,
                                  hot: [controller.currentChangeID, controller.focusedChangeID].compactMap { $0 },
                                  seen: controller.seenChanges,
                                  waveHeight: waveHeight, stripHeight: stripHeight, barY: barY)
                        .equatable()
                        .frame(width: w, height: height)
                        .allowsHitTesting(false)
                }

                // Played portion of the window, on the waveform.
                Rectangle().fill(Color.accentColor.opacity(0.10))
                    .frame(width: max(0, min(toX(player.currentSeconds), w)), height: waveHeight)
                    .allowsHitTesting(false)

                if controller.zoomWindow != nil {
                    Text("\(ReviewStore.mmss(win.length)) across · scroll / \(Shortcuts.label(.zoomIn)) / \(Shortcuts.label(.zoomOut))")
                        .font(.system(size: 10, weight: .medium, design: .monospaced))
                        .foregroundStyle(.secondary)
                        .padding(.horizontal, 5).padding(.vertical, 1)
                        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 3))
                        .padding(4)
                        .frame(width: w, alignment: .topTrailing)
                        .allowsHitTesting(false)
                }

                Capsule().fill(Color.secondary.opacity(0.22)).frame(width: w, height: 6)
                    .position(x: w / 2, y: barY)
                Capsule().fill(Color.accentColor.opacity(0.75))
                    .frame(width: max(0, min(toX(player.currentSeconds), w)), height: 6)
                    .position(x: max(0, min(toX(player.currentSeconds), w)) / 2, y: barY)

                ForEach(store.notes) { n in
                    let x = toX(n.seconds)
                    if x >= -2, x <= w + 2 {
                        let sel = controller.selection.contains(n.id)
                        Rectangle()
                            .fill((sel ? Color.accentColor : Color.orange).opacity(0.45))
                            .frame(width: 1, height: waveHeight)
                            .position(x: x, y: waveHeight / 2)
                            .allowsHitTesting(false)
                        RoundedRectangle(cornerRadius: 1)
                            .fill(sel ? Color.accentColor : Color.orange)
                            .frame(width: sel ? 4 : 2.5, height: sel ? 18 : 14)
                            .position(x: x, y: barY)
                    }
                }

                // Playhead: a line through the waveform, a knob on the bar.
                let px = toX(player.currentSeconds)
                if px >= 0, px <= w {
                    Rectangle().fill(Color.primary.opacity(0.8))
                        .frame(width: 1.5, height: waveHeight)
                        .position(x: px, y: waveHeight / 2)
                        .allowsHitTesting(false)
                    Circle()
                        .fill(Color.primary)
                        .frame(width: 12, height: 12)
                        .shadow(radius: 1)
                        .position(x: px, y: barY)
                }
            }
            .frame(width: w, height: height)
            .contentShape(Rectangle())
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { v in controller.scrub(to: snap(v.location.x).seconds) }
                    .onEnded { v in
                        let moved = abs(v.translation.width) > 3
                        if !moved, let c = changeFlag(at: v.location, toX: toX) {
                            controller.jumpToChange(c.id)
                        } else if !moved, let n = nearestNote(x: v.location.x, toX: toX) {
                            controller.select(n.id)
                        } else {
                            controller.scrubEnded(at: snap(v.location.x).seconds)
                        }
                    }
            )
            .onContinuousHover { phase in
                switch phase {
                case .active(let p):
                    hoverX = p.x
                    controller.timelineHover = (Double(min(max(p.x, 0), w) / w), Double(w))
                    requestThumb(at: toSeconds(p.x))
                case .ended:
                    hoverX = nil
                    controller.timelineHover = nil
                    thumbTask?.cancel()
                }
            }
            .overlay(alignment: .topLeading) {
                // One thumbnail that follows the pointer, as on a YouTube scrub bar.
                if let x = hoverX {
                    preview(at: toSeconds(x), note: nearestNote(x: x, toX: toX))
                        .offset(x: min(max(x - previewSize.width / 2, 0), max(0, w - previewSize.width)),
                                y: -(previewSize.height + 26))
                        .allowsHitTesting(false)
                }
            }
            .onChange(of: player.currentSeconds) { _, _ in controller.keepPlayheadInView() }
        }
        .frame(height: height)
        .help(controller.cuts == nil
              ? "click / drag: seek · click a tick: jump to that note · scroll / \(Shortcuts.label(.zoomIn)) / \(Shortcuts.label(.zoomOut)): zoom · ⇧scroll: move along"
              : "click / drag: seek, snapping to cuts (⌥: no snap) · \(Shortcuts.label(.previousCut)) / \(Shortcuts.label(.nextCut)): previous / next cut · click a tick: that note · scroll / \(Shortcuts.label(.zoomIn)) / \(Shortcuts.label(.zoomOut)): zoom · ⇧scroll: move along")
    }

    /// The numbered flag under a click, if any (same place ChangesCanvas draws them).
    private var visibleEnd: Double { controller.visibleWindow.start + controller.visibleWindow.length }

    private func changeFlag(at p: CGPoint, toX: (Double) -> CGFloat) -> Change? {
        guard let list = controller.changes, abs(p.y - (waveHeight - ChangesCanvas.flagInset)) <= 9 else { return nil }
        let w = toX(visibleEnd) - toX(controller.visibleWindow.start)
        let hits = list.changes.map { (c: $0, d: abs(ChangesCanvas.flagX(toX($0.start), width: w) - p.x)) }
        return hits.min { $0.d < $1.d }.flatMap { $0.d <= 9 ? $0.c : nil }
    }

    private func nearestNote(x: CGFloat, toX: (Double) -> CGFloat) -> Note? {
        store.notes.min { abs(toX($0.seconds) - x) < abs(toX($1.seconds) - x) }
            .flatMap { abs(toX($0.seconds) - x) <= 5 ? $0 : nil }
    }

    @ViewBuilder
    private func preview(at seconds: Double, note: Note?) -> some View {
        VStack(spacing: 3) {
            Group {
                if let thumb {
                    Image(decorative: thumb, scale: 1).resizable().scaledToFill()
                } else {
                    Color.black.opacity(0.6)
                }
            }
            .frame(width: previewSize.width, height: previewSize.height)
            .clipShape(RoundedRectangle(cornerRadius: 6))
            .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(Color.black.opacity(0.6), lineWidth: 1))
            Text(note.map { "\(controller.timecode($0.seconds))  \($0.text)" }
                 ?? controller.changes.flatMap { l in l.change(at: seconds).map { c in
                     "\(controller.timecode(seconds))  \(l.number(of: c.id) ?? 0) · \(c.title)" } }
                 ?? controller.timecode(seconds))
                .font(.system(size: 11, weight: .medium, design: .monospaced))
                .lineLimit(1)
                .padding(.horizontal, 6).padding(.vertical, 2)
                .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 4))
                .frame(maxWidth: previewSize.width)
        }
    }

    /// Storyboard hit: show it now, so the preview tracks the pointer. Miss:
    /// debounced one-off decode, so a fast sweep does not queue one per pixel.
    private func requestThumb(at seconds: Double) {
        thumbTask?.cancel()
        if let img = player.cachedThumbnail(at: seconds) { thumb = img; return }
        thumbTask = Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(50))
            guard !Task.isCancelled else { return }
            if let img = await player.thumbnail(at: seconds), !Task.isCancelled { thumb = img }
        }
    }
}

/// The changes layer: a purple band over the waveform for each change (a dashed
/// line for a removed shot), the band's clips outlined in the clip strip, a run
/// under the seek bar, and a numbered flag at the band's bottom left (click one
/// to play that change). Lit: the change under the playhead and the one last
/// jumped to; dimmed flags and runs: played through.
struct ChangesCanvas: View, Equatable {
    let changes: [Change]
    let start: Double
    let length: Double
    let hot: [String]
    let seen: Set<String>
    let waveHeight: CGFloat
    let stripHeight: CGFloat
    let barY: CGFloat
    /// The flags' centre sits this far above the bottom of the waveform.
    static let flagInset: CGFloat = 9
    /// A flag sits just inside its band's left end, and never off either end of the timeline.
    static func flagX(_ bandStart: CGFloat, width w: CGFloat) -> CGFloat { min(max(bandStart, 0) + 8, w - 8) }

    var body: some View {
        Canvas(rendersAsynchronously: false) { ctx, size in
            let w = size.width
            let toX = { (s: Double) -> CGFloat in CGFloat((s - start) / length) * w }
            var lastFlag: CGFloat = -100
            for (i, c) in changes.enumerated() where c.end >= start && c.start <= start + length {
                let lit = hot.contains(c.id)
                let done = seen.contains(c.id)
                let x0 = toX(c.start), x1 = max(toX(c.end), x0 + 2)
                if c.isPoint {
                    var line = Path()
                    line.move(to: CGPoint(x: x0, y: 0))
                    line.addLine(to: CGPoint(x: x0, y: waveHeight + stripHeight))
                    ctx.stroke(line, with: .color(Color.change.opacity(lit ? 1 : 0.85)),
                               style: StrokeStyle(lineWidth: lit ? 2.5 : 1.5, dash: [4, 3]))
                } else {
                    ctx.fill(Path(CGRect(x: x0, y: 0, width: x1 - x0, height: waveHeight)),
                             with: .color(Color.change.opacity(lit ? 0.32 : 0.17)))
                    if stripHeight > 0 {
                        let strip = CGRect(x: x0, y: waveHeight + 1, width: x1 - x0, height: stripHeight - 2)
                        ctx.stroke(Path(roundedRect: strip.insetBy(dx: 1, dy: 1), cornerRadius: 3),
                                   with: .color(Color.change.opacity(lit ? 1 : 0.7)), lineWidth: lit ? 3 : 1.5)
                    }
                }
                let run = CGRect(x: x0 - (c.isPoint ? 1.5 : 0), y: barY + 5, width: max(x1 - x0, 3), height: 3.5)
                ctx.fill(Path(roundedRect: run, cornerRadius: 1.5), with: .color(Color.change.opacity(done ? 0.4 : 0.95)))
                let fx = Self.flagX(x0, width: w)
                if fx - lastFlag >= 16 {
                    lastFlag = fx
                    let r = CGRect(x: fx - 7, y: waveHeight - Self.flagInset - 7, width: 14, height: 14)
                    ctx.fill(Path(ellipseIn: r), with: .color(Color.change.opacity(done && !lit ? 0.45 : 1)))
                    if lit { ctx.stroke(Path(ellipseIn: r.insetBy(dx: -1.5, dy: -1.5)), with: .color(.white), lineWidth: 1.5) }
                    ctx.draw(Text("\(i + 1)").font(.system(size: i + 1 >= 10 ? 7.5 : 8.5, weight: .bold)).foregroundStyle(Color.white),
                             at: CGPoint(x: r.midX, y: r.midY))
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

/// Cut lines through the waveform and, under it, the clip strip: one block per
/// clip (V1 grey, upper tracks teal, gaps dark, the clip under the playhead
/// outlined) with the clip's first frame at its left end and its last frame
/// at its right — both when the block is wide enough for two, the first
/// alone when it fits one, neither below that — and, between them, as many
/// scrub-storyboard pictures as fit (a filmstrip). Named in the free space,
/// or on a chip over the pictures when there is none. Redrawn only when the
/// cuts, the window, the current clip or the set of thumbnails change.
struct CutsCanvas: View, Equatable {
    let cuts: [Cut]
    let start: Double
    let length: Double
    let current: Int?
    let waveHeight: CGFloat
    let stripHeight: CGFloat
    let thumbsVersion: Int
    /// Source of the pictures; not part of equality (`thumbsVersion` is).
    let player: PlayerModel

    static func == (a: Self, b: Self) -> Bool {
        a.cuts == b.cuts && a.start == b.start && a.length == b.length && a.current == b.current
            && a.waveHeight == b.waveHeight && a.stripHeight == b.stripHeight && a.thumbsVersion == b.thumbsVersion
    }

    var body: some View {
        Canvas(rendersAsynchronously: false) { ctx, size in
            let w = size.width
            let toX = { (s: Double) -> CGFloat in CGFloat((s - start) / length) * w }
            let fps = max(player.fps, 1)
            let thumbH = stripHeight - 4
            let thumbW = (thumbH * CGFloat(player.aspect)).rounded()
            var lines = Path()
            for c in cuts where c.end > start && c.start < start + length {
                let x0 = toX(c.start), x1 = toX(c.end)
                if c.start > start, c.index != cuts.first?.index {
                    lines.move(to: CGPoint(x: x0, y: 10))          // below the ruler labels
                    lines.addLine(to: CGPoint(x: x0, y: waveHeight))
                }
                let rect = CGRect(x: x0 + 0.5, y: waveHeight + 2, width: max(1, x1 - x0 - 1), height: thumbH)
                let shape = Path(roundedRect: rect, cornerRadius: 3)
                let fill: Color = c.isGap ? .black.opacity(0.45)
                    : c.track > 1 ? .teal.opacity(0.5) : .secondary.opacity(0.32)
                ctx.fill(shape, with: .color(fill))

                var nameFrom = rect.minX + 4, nameTo = rect.maxX - 4
                var filled = false          // the middle carries pictures: the name needs a chip
                if !c.isGap, rect.width >= thumbW {
                    var inner = ctx
                    inner.clip(to: shape)
                    let first = CGRect(x: rect.minX, y: rect.minY, width: thumbW, height: thumbH)
                    if first.maxX > 0, first.minX < w,
                       let img = player.stripThumb(frame: c.firstFrame(fps: fps), start: c.start, end: c.end, atEnd: false) {
                        inner.draw(Image(decorative: img, scale: 1), in: first)
                    }
                    nameFrom = first.maxX + 4
                    if rect.width >= thumbW * 2 + 3 {
                        let last = CGRect(x: rect.maxX - thumbW, y: rect.minY, width: thumbW, height: thumbH)
                        if last.maxX > 0, last.minX < w,
                           let img = player.stripThumb(frame: c.lastFrame(fps: fps), start: c.start, end: c.end, atEnd: true) {
                            inner.draw(Image(decorative: img, scale: 1), in: last)
                        }
                        nameTo = last.minX - 4
                        // The middle: scrub-storyboard pictures edge to edge. The count is
                        // the nearest whole number of thumbnail widths, each tile stretched
                        // or squeezed to fill (the picture is cropped to it, never distorted),
                        // each showing the image nearest the time under its centre. Only the
                        // ones on screen are drawn (a long clip zoomed in is very wide).
                        let room = last.minX - first.maxX
                        if room >= thumbW * 0.6 {
                            let n = max(1, Int((room / thumbW).rounded()))
                            let pitch = room / CGFloat(n)
                            let x0 = first.maxX
                            let from = max(0, Int(((0 - pitch - x0) / pitch).rounded(.up)))
                            let to = min(n - 1, Int(((w - x0) / pitch).rounded(.down)))
                            if from <= to {
                                for i in from...to {
                                    let tile = CGRect(x: x0 + CGFloat(i) * pitch + 0.5, y: rect.minY,
                                                      width: pitch - 1, height: thumbH)
                                    let t = start + Double(tile.midX / w) * length
                                    if let img = player.filmstripThumb(near: t, start: c.start, end: c.end) {
                                        // Aspect-fill: scale to cover the tile, centre, clip.
                                        let ia = CGFloat(img.width) / CGFloat(max(img.height, 1))
                                        let cover = tile.width / tile.height > ia
                                            ? CGSize(width: tile.width, height: tile.width / ia)
                                            : CGSize(width: tile.height * ia, height: tile.height)
                                        var cell = inner
                                        cell.clip(to: Path(tile))
                                        cell.draw(Image(decorative: img, scale: 1),
                                                  in: CGRect(x: tile.midX - cover.width / 2, y: tile.midY - cover.height / 2,
                                                             width: cover.width, height: cover.height))
                                        filled = true
                                    }
                                }
                            }
                        }
                    }
                }
                let label = Text(c.name).font(.system(size: 10, weight: .medium))
                if filled {
                    // A chip over the pictures, bottom left, kept on screen while the block is.
                    let text = ctx.resolve(label.foregroundStyle(Color.white))
                    let room = min(rect.maxX, w) - max(rect.minX, 0) - 8
                    let sz = text.measure(in: CGSize(width: max(room, 0), height: 14))
                    if room > 40 {
                        let chip = CGRect(x: max(rect.minX, 0) + 2, y: rect.maxY - sz.height - 3,
                                          width: min(sz.width, room) + 6, height: sz.height + 2)
                        ctx.fill(Path(roundedRect: chip, cornerRadius: 2.5), with: .color(.black.opacity(0.6)))
                        var inner = ctx
                        inner.clip(to: Path(chip))
                        inner.draw(text, at: CGPoint(x: chip.minX + 3, y: chip.midY), anchor: .leading)
                    }
                } else {
                    // The name rides in the free space, kept on screen while the block is.
                    let from = max(nameFrom, 4), to = min(nameTo, w - 4)
                    if to - from > 40 {
                        var inner = ctx
                        inner.clip(to: Path(CGRect(x: from, y: rect.minY, width: to - from, height: rect.height)))
                        inner.draw(label.foregroundStyle(Color.primary.opacity(0.8)),
                                   at: CGPoint(x: from, y: rect.midY), anchor: .leading)
                    }
                }
                if c.index == current {
                    ctx.stroke(Path(roundedRect: rect.insetBy(dx: 0.5, dy: 0.5), cornerRadius: 3),
                               with: .color(.accentColor), lineWidth: 2)
                }
            }
            ctx.stroke(lines, with: .color(.primary.opacity(0.28)), lineWidth: 1)
        }
    }
}
