import AppKit
import ImageIO
import SwiftUI
import UniformTypeIdentifiers

/// What the list shows under a photo's name, read from its header.
struct PhotoInfo: Equatable, Sendable {
    /// As shown (its EXIF orientation applied), in pixels.
    var width: Int
    var height: Int
    /// ImageIO's type identifier, "public.jpeg".
    var type: String
    /// "JPEG", "HEIC", "PNG"…
    var format: String
    var frames: Int
    /// EXIF orientation, 1–8.
    var orientation: Int

    /// Turning and cropping write the photo back in its own format: not an
    /// animation, and not a format ImageIO only reads (WebP).
    var editable: Bool { frames == 1 && Photos.writable.contains(type) }
    /// Why `editable` is false, for the status line.
    var notEditable: String {
        frames > 1 ? "an animated \(format)" : "a \(format) (Bulk Cut can't write \(format) files)"
    }
    /// A turn alone only rewrites the orientation tag: no pixel is decoded.
    /// PNG has the tag too, but few apps read it, so a PNG is redrawn
    /// (losslessly) instead.
    var losslessTurn: Bool { Photos.orientationTypes.contains(type) }

    /// The size once turned `turns` quarter turns.
    func size(turns: Int) -> CGSize {
        Picture.turned(CGSize(width: width, height: height), turns: turns)
    }
}

enum Photos {
    static let writable = Set(CGImageDestinationCopyTypeIdentifiers() as? [String] ?? [])
    static let orientationTypes: Set<String> = ["public.jpeg", "public.heic", "public.heif", "public.tiff"]

    static func formatName(_ type: String) -> String {
        switch type {
        case "public.jpeg": "JPEG"
        case "public.heic": "HEIC"
        case "public.heif": "HEIF"
        case "public.png": "PNG"
        case "public.tiff": "TIFF"
        case "com.compuserve.gif": "GIF"
        case "com.microsoft.bmp": "BMP"
        case "org.webmproject.webp": "WebP"
        case "public.avif": "AVIF"
        default: UTType(type)?.preferredFilenameExtension?.uppercased() ?? type
        }
    }

    /// Read the header only.
    static func probe(_ url: URL) -> PhotoInfo? {
        let noCache = [kCGImageSourceShouldCache: false] as CFDictionary
        guard let src = CGImageSourceCreateWithURL(url as CFURL, noCache),
              let type = CGImageSourceGetType(src) as String?,
              let p = CGImageSourceCopyPropertiesAtIndex(src, 0, noCache) as? [CFString: Any],
              let w = (p[kCGImagePropertyPixelWidth] as? NSNumber)?.intValue,
              let h = (p[kCGImagePropertyPixelHeight] as? NSNumber)?.intValue else { return nil }
        let o = (p[kCGImagePropertyOrientation] as? NSNumber)?.intValue ?? 1
        let swap = (5...8).contains(o)
        return PhotoInfo(width: swap ? h : w, height: swap ? w : h, type: type, format: formatName(type),
                         frames: CGImageSourceGetCount(src), orientation: o)
    }

    /// The photo, upright, at most `maxPixels` on its long side (nil: full size).
    static func decode(_ url: URL, maxPixels: Int?) -> CGImage? {
        guard let src = CGImageSourceCreateWithURL(url as CFURL, [kCGImageSourceShouldCache: false] as CFDictionary)
        else { return nil }
        var limit = maxPixels
        if limit == nil, let p = CGImageSourceCopyPropertiesAtIndex(src, 0, nil) as? [CFString: Any] {
            limit = max((p[kCGImagePropertyPixelWidth] as? NSNumber)?.intValue ?? 0,
                        (p[kCGImagePropertyPixelHeight] as? NSNumber)?.intValue ?? 0)
        }
        guard let limit, limit > 0 else { return nil }
        let opts: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceShouldCacheImmediately: true,
            kCGImageSourceThumbnailMaxPixelSize: limit,
        ]
        return CGImageSourceCreateThumbnailAtIndex(src, 0, opts as CFDictionary)
    }

    /// The EXIF orientation that shows the stored pixels as `o` does, then
    /// turned `k` quarter turns clockwise. 1, 6, 3, 8 are 0°, 90°, 180°,
    /// 270° clockwise; 2, 7, 4, 5 the same after a mirror.
    static func orientation(_ o: Int, turnedBy k: Int) -> Int {
        let step = ((k % 4) + 4) % 4
        for ring in [[1, 6, 3, 8], [2, 7, 4, 5]] {
            if let i = ring.firstIndex(of: o) { return ring[(i + step) % 4] }
        }
        return [1, 6, 3, 8][step]
    }

    /// `img` turned `k` quarter turns clockwise, pixel for pixel.
    static func rotate(_ img: CGImage, quarterTurns k: Int) -> CGImage? {
        let k = ((k % 4) + 4) % 4
        guard k != 0 else { return img }
        let w = img.width, h = img.height
        let (nw, nh) = k % 2 == 1 ? (h, w) : (w, h)
        let opaque = [.none, .noneSkipLast, .noneSkipFirst].contains(img.alphaInfo)
        let alpha = (opaque ? CGImageAlphaInfo.noneSkipLast : .premultipliedLast).rawValue
        let srgb = CGColorSpace(name: CGColorSpace.sRGB)!
        func context(_ cs: CGColorSpace, _ bpc: Int) -> CGContext? {
            CGContext(data: nil, width: nw, height: nh, bitsPerComponent: bpc, bytesPerRow: 0, space: cs, bitmapInfo: alpha)
        }
        // The photo's own colour space and depth where Quartz can draw into them.
        guard let ctx = context(img.colorSpace ?? srgb, img.bitsPerComponent > 8 ? 16 : 8) ?? context(srgb, 8)
        else { return nil }
        ctx.interpolationQuality = .none
        switch k {   // y runs up; a clockwise turn is a negative angle
        case 1: ctx.translateBy(x: 0, y: CGFloat(nh)); ctx.rotate(by: -.pi / 2)
        case 2: ctx.translateBy(x: CGFloat(nw), y: CGFloat(nh)); ctx.rotate(by: .pi)
        default: ctx.translateBy(x: CGFloat(nw), y: 0); ctx.rotate(by: .pi / 2)
        }
        ctx.draw(img, in: CGRect(x: 0, y: 0, width: w, height: h))
        return ctx.makeImage()
    }

    private static func failure(_ why: String) -> NSError {
        NSError(domain: "bulk-cut", code: 8, userInfo: [NSLocalizedDescriptionKey: why])
    }

    /// Write `src` turned `turns` quarter turns clockwise and cropped to
    /// `crop` (in the turned frame) to `dst`, in its own format, with its
    /// metadata. A turn alone of a JPEG, HEIC or TIFF only changes the
    /// orientation tag; anything else is redrawn and re-encoded (PNG
    /// losslessly, JPEG / HEIC at high quality). Checked by reading it back.
    static func write(_ src: URL, turns: Int, crop: ZoomRect?, to dst: URL) throws {
        guard let info = probe(src), let source = CGImageSourceCreateWithURL(src as CFURL, nil),
              let type = CGImageSourceGetType(source) else { throw failure("can't read it") }
        guard info.editable else { throw failure("it is \(info.notEditable)") }
        let turned = info.size(turns: turns)
        let area = crop?.pixels(in: turned, even: false)
        guard let dest = CGImageDestinationCreateWithURL(dst as CFURL, type, 1, nil) else {
            throw failure("can't write \(info.format)")
        }
        if area == nil, info.losslessTurn {
            var err: Unmanaged<CFError>?
            let o = orientation(info.orientation, turnedBy: turns)
            guard CGImageDestinationCopyImageSource(dest, source, [kCGImageDestinationOrientation: o] as CFDictionary, &err) else {
                throw failure("the orientation tag was not rewritten" + (err.map { ": \($0.takeRetainedValue())" } ?? ""))
            }
        } else {
            guard var img = decode(src, maxPixels: nil) else { throw failure("can't decode it") }
            guard let r = rotate(img, quarterTurns: turns) else { throw failure("can't turn it") }
            img = r
            if let area {
                guard let c = img.cropping(to: area) else { throw failure("can't crop it") }
                img = c
            }
            // The pixels are now upright: orientation 1, and no stale sizes.
            var props = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any] ?? [:]
            props[kCGImagePropertyOrientation] = 1
            if var tiff = props[kCGImagePropertyTIFFDictionary] as? [CFString: Any] {
                tiff[kCGImagePropertyTIFFOrientation] = 1
                props[kCGImagePropertyTIFFDictionary] = tiff
            }
            if var exif = props[kCGImagePropertyExifDictionary] as? [CFString: Any] {
                exif[kCGImagePropertyExifPixelXDimension] = img.width
                exif[kCGImagePropertyExifPixelYDimension] = img.height
                props[kCGImagePropertyExifDictionary] = exif
            }
            props[kCGImageDestinationLossyCompressionQuality] = 0.95
            CGImageDestinationAddImage(dest, img, props as CFDictionary)
            guard CGImageDestinationFinalize(dest) else { throw failure("\(info.format) not written") }
        }
        let want = area?.size ?? turned
        guard let got = probe(dst) else { throw failure("the written photo can't be read back") }
        guard got.width == Int(want.width), got.height == Int(want.height) else {
            throw failure("it came out \(got.width)×\(got.height), expected \(Int(want.width))×\(Int(want.height))")
        }
    }
}

/// The photo on screen and its neighbours, upright, up to 3200 px on the
/// long side: decoded in the background so ↓ through a folder shows each
/// one at once.
@MainActor
final class PhotoStore {
    static let shared = PhotoStore()
    nonisolated static let pixels = 3200

    private final class Box { let image: CGImage; init(_ i: CGImage) { image = i } }
    private let memory = NSCache<NSURL, Box>()
    private var inflight: [URL: Task<CGImage?, Never>] = [:]

    private init() { memory.countLimit = 8 }

    func cached(_ url: URL) -> CGImage? { memory.object(forKey: url as NSURL)?.image }

    func image(for url: URL) async -> CGImage? {
        if let c = cached(url) { return c }
        if let t = inflight[url] { return await t.value }
        let t = Task.detached(priority: .userInitiated) { Photos.decode(url, maxPixels: Self.pixels) }
        inflight[url] = t
        let img = await t.value
        inflight[url] = nil
        if let img { memory.setObject(Box(img), forKey: url as NSURL) }
        return img
    }

    func prefetch(_ urls: [URL]) {
        for u in urls where cached(u) == nil && inflight[u] == nil {
            Task { _ = await image(for: u) }
        }
    }

    /// Forget a file's picture (it was rewritten in place).
    func drop(_ url: URL) { memory.removeObject(forKey: url as NSURL) }
}

/// The photo, turned and cropped as staged: the crop fills the box (fitted,
/// centred), as a zoom does for a video.
struct PhotoView: NSViewRepresentable {
    let image: CGImage?
    /// The photo's size as shown once turned, in pixels.
    var display: CGSize?
    var turns = 0
    var crop: ZoomRect?

    final class View: NSView {
        let frameLayer = CALayer()
        let imageLayer = CALayer()
        var image: CGImage?
        var display: CGSize?
        var turns = 0
        var crop: ZoomRect?

        override init(frame: NSRect) {
            super.init(frame: frame)
            frameLayer.masksToBounds = true
            imageLayer.contentsGravity = .resize
            imageLayer.minificationFilter = .trilinear
            frameLayer.addSublayer(imageLayer)
            wantsLayer = true
        }

        required init?(coder: NSCoder) { fatalError("not used") }

        override var acceptsFirstResponder: Bool { false }

        override func makeBackingLayer() -> CALayer {
            let root = CALayer()
            root.backgroundColor = NSColor.black.cgColor
            root.addSublayer(frameLayer)
            return root
        }

        override func setFrameSize(_ newSize: NSSize) {
            super.setFrameSize(newSize)
            place()
        }

        override func layout() {
            super.layout()
            place()
        }

        /// As PlayerView.place.
        func place() {
            CATransaction.begin()
            CATransaction.setDisableActions(true)
            defer { CATransaction.commit() }
            imageLayer.contents = image
            imageLayer.setAffineTransform(.identity)
            guard image != nil, let d = display, d.width > 0, d.height > 0 else {
                frameLayer.frame = .zero
                return
            }
            Picture.lay(imageLayer, in: frameLayer, view: bounds.size, display: d, turns: turns, zoom: crop)
        }
    }

    func makeNSView(context: Context) -> View { View() }

    func updateNSView(_ v: View, context: Context) {
        guard v.image !== image || v.display != display || v.turns != turns || v.crop != crop else { return }
        v.image = image
        v.display = display
        v.turns = turns
        v.crop = crop
        v.place()
    }
}
