// Draws the EditReview app icon into an .iconset folder (build.sh turns it
// into AppIcon.icns with iconutil). No image files are kept in the repo: the
// icon is drawn here, at build time, with AppKit / Core Graphics only.
//
//   swiftc -O scripts/make_icon.swift -o build/make_icon
//   build/make_icon build/AppIcon.iconset
//
// The picture: a video frame with a play triangle, a timeline under it, and a
// yellow note pinned at the playhead ("pause, type a note, it is stamped at
// the time"). Change the colours below to make it yours.
import AppKit

let indigoTop = CGColor(red: 52 / 255, green: 60 / 255, blue: 110 / 255, alpha: 1)
let indigoBottom = CGColor(red: 18 / 255, green: 20 / 255, blue: 38 / 255, alpha: 1)
let accent = CGColor(red: 120 / 255, green: 200 / 255, blue: 1, alpha: 1)
let pinYellow = CGColor(red: 1, green: 204 / 255, blue: 0, alpha: 1)
let ink = CGColor(red: 40 / 255, green: 30 / 255, blue: 0, alpha: 0.9)

func white(_ a: CGFloat) -> CGColor { CGColor(gray: 1, alpha: a) }

func rounded(_ r: CGRect, _ radius: CGFloat) -> CGPath {
    CGPath(roundedRect: r, cornerWidth: radius, cornerHeight: radius, transform: nil)
}

/// Draws on a 1024 x 1024 canvas with the origin at the top left.
func draw(_ cg: CGContext) {
    let box = CGRect(x: 100, y: 100, width: 824, height: 824)
    let squircle = rounded(box, 824 * 0.2237)

    // Background: indigo to near-black, plus a soft highlight at the top.
    cg.saveGState()
    cg.addPath(squircle)
    cg.clip()
    let grad = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(),
                          colors: [indigoTop, indigoBottom] as CFArray, locations: [0, 1])!
    cg.drawLinearGradient(grad, start: CGPoint(x: 0, y: 100), end: CGPoint(x: 0, y: 924), options: [])
    cg.setFillColor(white(0.06))
    cg.addPath(rounded(CGRect(x: 100, y: 100, width: 824, height: 430), 184))
    cg.fillPath()
    cg.restoreGState()

    // Video frame (16:9) with a play triangle.
    let frame = CGRect(x: 205, y: 205, width: 614, height: 345)
    cg.setFillColor(white(0.11))
    cg.addPath(rounded(frame, 51))
    cg.fillPath()
    cg.setStrokeColor(white(1))
    cg.setLineWidth(29)
    cg.addPath(rounded(frame, 51))
    cg.strokePath()
    let cx: CGFloat = 524, cy: CGFloat = 377, t: CGFloat = 113
    cg.setFillColor(white(1))
    cg.move(to: CGPoint(x: cx - t * 0.8, y: cy - t))
    cg.addLine(to: CGPoint(x: cx - t * 0.8, y: cy + t))
    cg.addLine(to: CGPoint(x: cx + t, y: cy))
    cg.closePath()
    cg.fillPath()

    // Timeline, played up to the playhead.
    let ty: CGFloat = 778, th: CGFloat = 33, ph: CGFloat = 586
    cg.setFillColor(white(0.27))
    cg.addPath(rounded(CGRect(x: 205, y: ty - th / 2, width: 614, height: th), th / 2))
    cg.fillPath()
    cg.setFillColor(accent)
    cg.addPath(rounded(CGRect(x: 205, y: ty - th / 2, width: ph - 205, height: th), th / 2))
    cg.fillPath()

    // The note pinned at the playhead, with a drop shadow.
    let pw: CGFloat = 143, top: CGFloat = 609
    let pin = CGRect(x: ph - pw / 2, y: top, width: pw, height: pw * 0.86)
    let note = CGMutablePath()
    note.addPath(rounded(pin, pw * 0.22))
    note.move(to: CGPoint(x: ph - pw * 0.26, y: pin.maxY - 2))
    note.addLine(to: CGPoint(x: ph + pw * 0.26, y: pin.maxY - 2))
    note.addLine(to: CGPoint(x: ph, y: ty))
    note.closeSubpath()
    cg.saveGState()
    cg.setShadow(offset: CGSize(width: 8, height: 8), blur: 24, color: CGColor(gray: 0, alpha: 0.55))
    cg.setFillColor(pinYellow)
    cg.addPath(note)
    cg.fillPath()
    cg.restoreGState()
    cg.setFillColor(ink)
    for (i, frac) in [1.0, 0.75, 0.5].enumerated() {
        let x0 = pin.minX + pw * 0.2, x1 = pin.maxX - pw * 0.2
        let y = top + pw * (0.26 + CGFloat(i) * 0.19)
        cg.addPath(rounded(CGRect(x: x0, y: y, width: (x1 - x0) * frac, height: 12), 6))
        cg.fillPath()
    }
    cg.setFillColor(pinYellow)
    cg.fillEllipse(in: CGRect(x: ph - 28, y: ty - 28, width: 56, height: 56))
}

func png(_ px: Int) -> Data {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: px, pixelsHigh: px,
                               bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                               colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    let ctx = NSGraphicsContext(bitmapImageRep: rep)!
    let cg = ctx.cgContext
    let s = CGFloat(px) / 1024
    cg.translateBy(x: 0, y: CGFloat(px))
    cg.scaleBy(x: s, y: -s)            // top-left origin, 1024-point canvas
    draw(cg)
    ctx.flushGraphics()
    return rep.representation(using: .png, properties: [:])!
}

let args = CommandLine.arguments
guard args.count == 2 else {
    FileHandle.standardError.write("usage: make_icon <out.iconset>\n".data(using: .utf8)!)
    exit(2)
}
let out = URL(fileURLWithPath: args[1])
try FileManager.default.createDirectory(at: out, withIntermediateDirectories: true)
for pt in [16, 32, 128, 256, 512] {
    try png(pt).write(to: out.appendingPathComponent("icon_\(pt)x\(pt).png"))
    try png(pt * 2).write(to: out.appendingPathComponent("icon_\(pt)x\(pt)@2x.png"))
}
print("wrote \(out.path)")
