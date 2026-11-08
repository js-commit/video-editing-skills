import CoreGraphics
import Foundation
import QuartzCore

/// The part of the picture a zoom keeps, as fractions (0…1) of the frame
/// as it is shown (the clip's own rotation and any staged turn applied),
/// measured from its top-left corner.
struct ZoomRect: Codable, Equatable {
    var x: Double
    var y: Double
    var w: Double
    var h: Double

    static let full = ZoomRect(x: 0, y: 0, w: 1, h: 1)

    /// The same part of the picture once the frame is turned 180°.
    var turned: ZoomRect { ZoomRect(x: 1 - x - w, y: 1 - y - h, w: w, h: h) }

    /// The same part of the picture once the frame is turned `k` quarter
    /// turns clockwise (negative: anticlockwise).
    func rotated(_ k: Int) -> ZoomRect {
        var r = self
        // A quarter turn clockwise takes (u, v) to (1 − v, u).
        for _ in 0..<((k % 4 + 4) % 4) { r = ZoomRect(x: 1 - r.y - r.h, y: r.x, w: r.h, h: r.w) }
        return r
    }

    /// `inner`, a part of this area, as a part of the whole frame.
    func compose(_ inner: ZoomRect) -> ZoomRect {
        ZoomRect(x: x + inner.x * w, y: y + inner.y * h, w: inner.w * w, h: inner.h * h)
    }

    /// The area in pixels of a `size` frame: whole pixels, inside the frame,
    /// with `even` (for video: 4:2:0 needs it) an even width and height. nil
    /// when that is the whole frame, so there is nothing to zoom.
    func pixels(in size: CGSize, even: Bool = true) -> CGRect? {
        func span(_ start: Double, _ length: Double, _ total: CGFloat) -> (CGFloat, CGFloat) {
            let t = Double(total)
            var l = (length * t).rounded()
            l = even ? max(2, min(l - l.truncatingRemainder(dividingBy: 2), t - t.truncatingRemainder(dividingBy: 2)))
                     : max(1, min(l, t))
            return (CGFloat(min(max(0, (start * t).rounded()), t - l)), CGFloat(l))
        }
        let (px, pw) = span(x, w, size.width)
        let (py, ph) = span(y, h, size.height)
        guard pw < size.width - 2 || ph < size.height - 2 else { return nil }
        return CGRect(x: px, y: py, width: pw, height: ph)
    }

    /// "1920×1080": the size a zoom comes out at, from a `size` frame.
    func label(in size: CGSize, even: Bool = true) -> String {
        guard let r = pixels(in: size, even: even) else { return "whole frame" }
        return "\(Int(r.width))×\(Int(r.height))"
    }
}

enum Picture {
    /// `k` quarter turns clockwise, exactly, counting y down (as a video's
    /// matrices and layer instructions do).
    static func quarter(_ k: Int) -> CGAffineTransform {
        switch ((k % 4) + 4) % 4 {
        case 1: CGAffineTransform(a: 0, b: 1, c: -1, d: 0, tx: 0, ty: 0)
        case 2: CGAffineTransform(a: -1, b: 0, c: 0, d: -1, tx: 0, ty: 0)
        case 3: CGAffineTransform(a: 0, b: -1, c: 1, d: 0, tx: 0, ty: 0)
        default: .identity
        }
    }

    /// A `size` picture's size once turned `turns` quarter turns.
    static func turned(_ size: CGSize, turns: Int) -> CGSize {
        turns % 2 != 0 ? CGSize(width: size.height, height: size.width) : size
    }

    /// Lay out the on-screen picture of a `display`-sized turned frame:
    /// `frame` clips to the part shown (the zoom area, or all of it) as big
    /// as fits `view`, centred; `layer` holds the picture upright at the
    /// frame's centre, then turned. Layers count y up; zoom areas y down.
    static func lay(_ layer: CALayer, in frame: CALayer, view v: CGSize, display d: CGSize, turns: Int, zoom: ZoomRect?) {
        let z = zoom ?? .full
        let shown = shownRect(view: v, display: d, zoom: zoom)
        frame.frame = CGRect(x: shown.minX, y: v.height - shown.maxY, width: shown.width, height: shown.height)
        // The whole turned frame in points; upright, a quarter turn swaps its sides.
        let fw = shown.width / z.w, fh = shown.height / z.h
        layer.bounds = turns % 2 != 0 ? CGRect(x: 0, y: 0, width: fh, height: fw) : CGRect(x: 0, y: 0, width: fw, height: fh)
        layer.position = CGPoint(x: -z.x * fw + fw / 2, y: shown.height + z.y * fh - fh / 2)
        // With y running up, turning back counts as clockwise on screen.
        layer.setAffineTransform(quarter(-turns))
    }

    /// Where the part of a `display`-sized picture on screen (the zoom area,
    /// or all of it) sits in a `view`-sized box: as big as fits, centred.
    /// Top-left origin.
    static func shownRect(view: CGSize, display: CGSize, zoom: ZoomRect?) -> CGRect {
        let z = zoom ?? .full
        let w = display.width * z.w, h = display.height * z.h
        guard w > 0, h > 0, view.width > 0, view.height > 0 else { return CGRect(origin: .zero, size: view) }
        let s = min(view.width / w, view.height / h)
        return CGRect(x: (view.width - w * s) / 2, y: (view.height - h * s) / 2, width: w * s, height: h * s)
    }
}

/// A lossless quarter turn of a QuickTime / MP4 file: each video track's
/// display matrix (`moov/trak/tkhd`) is rewritten in place, as
/// `ffmpeg -display_rotation` would do. No sample is touched; players and
/// editors read the matrix as the track's rotation (AVFoundation's
/// preferredTransform), as they do for a phone held sideways or upside down.
enum TrackHeaders {
    private struct Box {
        let type: String
        /// Offsets of the payload in the buffer.
        let body: Range<Int>
    }

    /// `k` quarter turns clockwise.
    static func turn(_ url: URL, by k: Int) throws {
        let h = try FileHandle(forUpdating: url)
        defer { try? h.close() }
        let fileSize = try h.seekToEnd()

        var off: UInt64 = 0
        var moov: (start: UInt64, size: Int)?
        while off + 8 <= fileSize {
            try h.seek(toOffset: off)
            guard let head = try h.read(upToCount: 16), head.count >= 8 else { break }
            let b = [UInt8](head)
            var size = UInt64(be32(b, 0))
            var header: UInt64 = 8
            if size == 1 {
                guard b.count >= 16 else { break }
                size = be64(b, 8)
                header = 16
            } else if size == 0 {
                size = fileSize - off
            }
            guard size >= header else { throw failure("a broken atom at byte \(off)") }
            if fourCC(b, 4) == "moov" { moov = (off, Int(size)); break }
            off += size
        }
        guard let moov else { throw failure("no movie header (moov)") }
        try h.seek(toOffset: moov.start)
        guard let data = try h.read(upToCount: moov.size), data.count == moov.size else {
            throw failure("the movie header was cut short")
        }
        let bytes = [UInt8](data)
        guard let root = boxes(bytes, in: 0..<bytes.count).first, root.type == "moov" else {
            throw failure("no movie header (moov)")
        }

        var turned = 0
        for trak in boxes(bytes, in: root.body) where trak.type == "trak" {
            let kids = boxes(bytes, in: trak.body)
            guard let tkhd = kids.first(where: { $0.type == "tkhd" }), handler(bytes, kids) == "vide" else { continue }
            let v = tkhd.body.lowerBound
            // version + flags, the times / ID / duration (longer in version 1),
            // reserved, layer, group, volume, reserved; then the matrix and size.
            let m = v + 4 + (bytes[v] == 1 ? 32 : 20) + 16
            guard m + 44 <= tkhd.body.upperBound else { throw failure("a short track header") }
            func fixed(_ i: Int) -> CGFloat { CGFloat(Int32(bitPattern: be32(bytes, i))) / 65536 }
            let old = CGAffineTransform(a: fixed(m), b: fixed(m + 4), c: fixed(m + 12), d: fixed(m + 16),
                                        tx: fixed(m + 24), ty: fixed(m + 28))
            let size = CGSize(width: fixed(m + 36), height: fixed(m + 40))
            let new = old.concatenating(quarterTurns(k, of: size, under: old))
            var patch = [UInt8](bytes[m..<m + 36])
            for (i, x) in [(0, new.a), (4, new.b), (12, new.c), (16, new.d), (24, new.tx), (28, new.ty)] {
                let n = (x * 65536).rounded()
                guard abs(n) < Double(Int32.max) else { throw failure("a matrix value out of range") }
                put32(&patch, i, UInt32(bitPattern: Int32(n)))
            }
            try h.seek(toOffset: moov.start + UInt64(m))
            try h.write(contentsOf: patch)
            turned += 1
        }
        guard turned > 0 else { throw failure("no video track header") }
        try h.synchronize()
    }

    /// `k` quarter turns clockwise of where `transform` shows a `size`
    /// frame, its top-left corner kept where it was.
    static func quarterTurns(_ k: Int, of size: CGSize, under transform: CGAffineTransform) -> CGAffineTransform {
        let r = CGRect(origin: .zero, size: size).applying(transform)
        let spin = Picture.quarter(k)
        let turned = r.applying(spin)
        return spin.concatenating(CGAffineTransform(translationX: r.minX - turned.minX, y: r.minY - turned.minY))
    }

    /// The boxes laid end to end in `range`.
    private static func boxes(_ b: [UInt8], in range: Range<Int>) -> [Box] {
        var out: [Box] = []
        var i = range.lowerBound
        while i + 8 <= range.upperBound {
            var size = Int(be32(b, i))
            var header = 8
            if size == 1 {
                guard i + 16 <= range.upperBound else { break }
                size = Int(be64(b, i + 8))
                header = 16
            } else if size == 0 {
                size = range.upperBound - i
            }
            guard size >= header, i + size <= range.upperBound else { break }
            out.append(Box(type: fourCC(b, i + 4), body: i + header..<i + size))
            i += size
        }
        return out
    }

    /// The track's media type: `vide`, `soun`, `tmcd`, …
    private static func handler(_ b: [UInt8], _ trakKids: [Box]) -> String? {
        guard let mdia = trakKids.first(where: { $0.type == "mdia" }),
              let hdlr = boxes(b, in: mdia.body).first(where: { $0.type == "hdlr" }),
              hdlr.body.count >= 12 else { return nil }
        // version + flags, then the component type, then the subtype.
        return fourCC(b, hdlr.body.lowerBound + 8)
    }

    private static func be32(_ b: [UInt8], _ i: Int) -> UInt32 {
        UInt32(b[i]) << 24 | UInt32(b[i + 1]) << 16 | UInt32(b[i + 2]) << 8 | UInt32(b[i + 3])
    }

    private static func be64(_ b: [UInt8], _ i: Int) -> UInt64 {
        UInt64(be32(b, i)) << 32 | UInt64(be32(b, i + 4))
    }

    private static func put32(_ b: inout [UInt8], _ i: Int, _ v: UInt32) {
        b[i] = UInt8(v >> 24 & 255); b[i + 1] = UInt8(v >> 16 & 255); b[i + 2] = UInt8(v >> 8 & 255); b[i + 3] = UInt8(v & 255)
    }

    private static func fourCC(_ b: [UInt8], _ i: Int) -> String {
        String(bytes: b[i..<i + 4], encoding: .isoLatin1) ?? "?"
    }

    private static func failure(_ why: String) -> NSError {
        NSError(domain: "bulk-cut", code: 5, userInfo: [NSLocalizedDescriptionKey: "can't turn it: \(why)"])
    }
}
