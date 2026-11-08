// Draws the BulkCut app icon into an .iconset folder (build.sh turns it into
// AppIcon.icns with iconutil). No image files are kept in the repo: the icon
// is drawn here, at build time, with AppKit / Core Graphics only.
//
//   swiftc -O scripts/make_icon.swift -o build/make_icon
//   build/make_icon build/AppIcon.iconset
//
// The picture: a stack of clip thumbnails, the top one with a timeline whose
// middle stretch is kept (yellow brackets) and the rest greyed out ("go down
// the clips, keep the good parts"). Change the colours below to make it yours.
import AppKit

let tealTop = CGColor(red: 24 / 255, green: 92 / 255, blue: 100 / 255, alpha: 1)
let tealBottom = CGColor(red: 10 / 255, green: 30 / 255, blue: 36 / 255, alpha: 1)
let keep = CGColor(red: 1, green: 0.8, blue: 0.1, alpha: 1)
let screen = CGColor(red: 30 / 255, green: 44 / 255, blue: 52 / 255, alpha: 1)

func white(_ a: CGFloat) -> CGColor { CGColor(gray: 1, alpha: a) }

func rounded(_ r: CGRect, _ radius: CGFloat) -> CGPath {
    CGPath(roundedRect: r, cornerWidth: radius, cornerHeight: radius, transform: nil)
}

/// Draws on a 1024 x 1024 canvas with the origin at the top left.
func draw(_ cg: CGContext) {
    let box = CGRect(x: 100, y: 100, width: 824, height: 824)
    let squircle = rounded(box, 824 * 0.2237)

    // Background: teal to near-black, plus a soft highlight at the top.
    cg.saveGState()
    cg.addPath(squircle)
    cg.clip()
    let grad = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(),
                          colors: [tealTop, tealBottom] as CFArray, locations: [0, 1])!
    cg.drawLinearGradient(grad, start: CGPoint(x: 0, y: 100), end: CGPoint(x: 0, y: 924), options: [])
    cg.setFillColor(white(0.05))
    cg.addPath(rounded(CGRect(x: 100, y: 100, width: 824, height: 400), 184))
    cg.fillPath()
    cg.restoreGState()

    // Two cards behind: the rest of the folder.
    for (i, a) in [(2, 0.25), (1, 0.45)] {
        let d = CGFloat(i) * 34
        let r = CGRect(x: 230 + d, y: 210 - d, width: 564, height: 330)
        cg.setFillColor(white(a))
        cg.addPath(rounded(r, 40))
        cg.fillPath()
    }

    // The clip on top: a frame with a play triangle.
    let frame = CGRect(x: 190, y: 250, width: 564, height: 330)
    cg.saveGState()
    cg.setShadow(offset: CGSize(width: 0, height: 10), blur: 30, color: CGColor(gray: 0, alpha: 0.5))
    cg.setFillColor(screen)
    cg.addPath(rounded(frame, 44))
    cg.fillPath()
    cg.restoreGState()
    cg.setStrokeColor(white(1))
    cg.setLineWidth(24)
    cg.addPath(rounded(frame, 44))
    cg.strokePath()
    let cx: CGFloat = 490, cy: CGFloat = 415, t: CGFloat = 92
    cg.setFillColor(white(1))
    cg.move(to: CGPoint(x: cx - t * 0.8, y: cy - t))
    cg.addLine(to: CGPoint(x: cx - t * 0.8, y: cy + t))
    cg.addLine(to: CGPoint(x: cx + t, y: cy))
    cg.closePath()
    cg.fillPath()

    // The timeline: grey where it is dropped, the kept stretch bracketed.
    let ty: CGFloat = 730, th: CGFloat = 70
    let left: CGFloat = 190, right: CGFloat = 834, k0: CGFloat = 390, k1: CGFloat = 650
    cg.setFillColor(white(0.18))
    cg.addPath(rounded(CGRect(x: left, y: ty - th / 2, width: right - left, height: th), 16))
    cg.fillPath()
    cg.setFillColor(keep.copy(alpha: 0.35)!)
    cg.fill(CGRect(x: k0, y: ty - th / 2, width: k1 - k0, height: th))
    cg.setFillColor(keep)
    for (x, dir) in [(k0, CGFloat(1)), (k1, CGFloat(-1))] {
        cg.fill(CGRect(x: x - 9, y: ty - th / 2 - 18, width: 18, height: th + 36))
        for y in [ty - th / 2 - 18, ty + th / 2 + 4] {
            cg.fill(CGRect(x: dir > 0 ? x : x - 44, y: y, width: 44, height: 14))
        }
    }
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
