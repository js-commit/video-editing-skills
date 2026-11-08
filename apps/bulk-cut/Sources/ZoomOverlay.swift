import AppKit
import SwiftUI

/// Over the video: drag out a rectangle and the clip zooms into it on
/// release (over a photo, it is cropped to it). The rectangle keeps the
/// picture's own shape unless ⇧ is held. Drawn inside a zoom, it zooms in
/// further.
struct ZoomOverlay: View {
    /// The picture's size as shown, in pixels.
    let display: CGSize
    let zoom: ZoomRect?
    /// Sizes as a video zoom comes out (even); a photo crop is exact.
    var evenSizes = true
    let commit: (ZoomRect) -> Void
    @State private var drag: (start: CGPoint, end: CGPoint, free: Bool)?

    static let hint = "Drag on the video to zoom into that area (hold ⇧ for any shape). Zooming re-encodes the clip on Apply."
    static let photoHint = "Drag on the photo to crop to that area (hold ⇧ for any shape). Cropping re-encodes the photo on Apply."
    /// Smaller than this many pixels a side is no zoom at all.
    static let minPixels = 32.0

    var body: some View {
        GeometryReader { geo in
            let shown = Picture.shownRect(view: geo.size, display: display, zoom: zoom)
            ZStack(alignment: .topLeading) {
                Color.clear.contentShape(Rectangle())
                if let d = drag, let r = Self.rect(d.start, d.end, in: shown, aspect: d.free ? nil : aspect) {
                    Path { p in p.addRect(shown); p.addRect(r) }
                        .fill(Color.black.opacity(0.5), style: FillStyle(eoFill: true))
                    Rectangle().path(in: r).stroke(Color.yellow, lineWidth: 1.5)
                    Text(zoomed(r, in: shown).label(in: display, even: evenSizes))
                        .font(.system(size: 11, weight: .semibold, design: .monospaced))
                        .foregroundStyle(.black)
                        .padding(.horizontal, 5).padding(.vertical, 1)
                        .background(Color.yellow, in: RoundedRectangle(cornerRadius: 3))
                        .offset(x: r.minX, y: max(0, r.minY - 20))
                }
            }
            .pointerStyle(.rectSelection)
            .gesture(
                DragGesture(minimumDistance: 3)
                    .onChanged { v in drag = (v.startLocation, v.location, NSEvent.modifierFlags.contains(.shift)) }
                    .onEnded { v in
                        drag = nil
                        let free = NSEvent.modifierFlags.contains(.shift)
                        guard let r = Self.rect(v.startLocation, v.location, in: shown, aspect: free ? nil : aspect),
                              r.width >= 6, r.height >= 6 else { return }
                        let z = zoomed(r, in: shown)
                        guard z.w * display.width >= Self.minPixels, z.h * display.height >= Self.minPixels else { return }
                        commit(z)
                    }
            )
        }
    }

    private var aspect: CGFloat { display.width / display.height }

    /// Rectangle `r` drawn over `shown` (the part of the picture on screen) as a part of the whole frame.
    private func zoomed(_ r: CGRect, in shown: CGRect) -> ZoomRect {
        (zoom ?? .full).compose(ZoomRect(x: (r.minX - shown.minX) / shown.width, y: (r.minY - shown.minY) / shown.height,
                                         w: r.width / shown.width, h: r.height / shown.height))
    }

    /// The rectangle dragged from `a` to `b`, inside `bounds`. With an
    /// `aspect` (width / height), that shape, as big as the drag and the
    /// room allow.
    static func rect(_ a: CGPoint, _ b: CGPoint, in bounds: CGRect, aspect: CGFloat?) -> CGRect? {
        func clampX(_ x: CGFloat) -> CGFloat { min(max(x, bounds.minX), bounds.maxX) }
        func clampY(_ y: CGFloat) -> CGFloat { min(max(y, bounds.minY), bounds.maxY) }
        let ax = clampX(a.x), ay = clampY(a.y)
        let right = b.x >= a.x, down = b.y >= a.y
        var w = abs(clampX(b.x) - ax), h = abs(clampY(b.y) - ay)
        if let k = aspect, k > 0 {
            let roomX = right ? bounds.maxX - ax : ax - bounds.minX
            let roomY = down ? bounds.maxY - ay : ay - bounds.minY
            w = min(max(w, h * k), roomX, roomY * k)
            h = w / k
        }
        guard w > 0, h > 0 else { return nil }
        return CGRect(x: right ? ax : ax - w, y: down ? ay : ay - h, width: w, height: h)
    }
}
