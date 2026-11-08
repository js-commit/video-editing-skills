import AVFoundation
import Foundation
import ImageIO

/// The poster frame for each row of the clip list: a frame 30 % of the way
/// in (the first is often a fade or the camera settling), or the photo
/// itself, upright, up to 640 px on its long side so the biggest row size
/// stays sharp. Made on demand as rows come into view, four at a time, kept
/// in memory and in the MediaCache as `poster.bin` (HEIC), so a folder
/// opened again fills in at once. A photo on this Mac's own disks is quick
/// to read again, so only a network one's is kept on disk.
@MainActor
final class Thumbnails {
    static let shared = Thumbnails()
    nonisolated static let pixels = 640.0

    private final class Box { let image: CGImage; init(_ i: CGImage) { image = i } }
    private let memory = NSCache<NSURL, Box>()
    private var inflight: [URL: Task<CGImage?, Never>] = [:]
    private let gate = Gate(limit: 4)

    private init() {
        memory.countLimit = 600
        memory.totalCostLimit = 400 << 20
    }

    func cached(_ clip: Clip) -> CGImage? { memory.object(forKey: key(clip))?.image }

    /// The row's task is cancelled when it scrolls away: a request still
    /// waiting its turn is then dropped, so a fast scroll (or ↓ held down)
    /// through a network folder doesn't leave hundreds of reads queued.
    func image(for clip: Clip) async -> CGImage? {
        if let c = cached(clip) { return c }
        let t: Task<CGImage?, Never>
        if let running = inflight[clip.url] {
            t = running
        } else {
            let gate = self.gate
            t = Task.detached(priority: .utility) { () -> CGImage? in
                guard await gate.enter() else { return nil }
                guard !Task.isCancelled else { await gate.leave(); return nil }
                let img = await Self.make(clip)
                await gate.leave()
                return img
            }
            inflight[clip.url] = t
        }
        let img = await withTaskCancellationHandler { await t.value } onCancel: { t.cancel() }
        if inflight[clip.url] == t { inflight[clip.url] = nil }
        if let img { memory.setObject(Box(img), forKey: key(clip), cost: img.bytesPerRow * img.height) }
        // Another row's request dropped this one's read: start again.
        if img == nil, t.isCancelled, !Task.isCancelled { return await image(for: clip) }
        return img
    }

    /// Forget a file's picture (it was cropped or turned in place).
    func drop(_ url: URL) {
        memory.removeObject(forKey: url as NSURL)
        try? FileManager.default.removeItem(at: MediaCache.dir(for: url).appendingPathComponent("poster.bin"))
    }

    private func key(_ clip: Clip) -> NSURL { clip.url as NSURL }

    private struct Poster: Codable { var size: Int64; var mtime: Int; var pixels: Double; var data: Data }

    nonisolated private static func make(_ clip: Clip) async -> CGImage? {
        let cacheURL = MediaCache.dir(for: clip.url).appendingPathComponent("poster.bin")
        let mtime = Int(clip.modified.timeIntervalSince1970)
        if let p = MediaCache.load(Poster.self, from: cacheURL), p.size == clip.size, p.mtime == mtime,
           p.pixels == pixels, let img = decode(p.data) {
            return img
        }
        if clip.isPhoto {
            guard let img = Photos.decode(clip.url, maxPixels: Int(pixels)) else { return nil }
            if !MediaCache.isLocal(clip.url), let d = encode(img) {
                MediaCache.touch(cacheURL.deletingLastPathComponent(), video: clip.url)
                MediaCache.save(Poster(size: clip.size, mtime: mtime, pixels: pixels, data: d), to: cacheURL)
            }
            return img
        }
        let asset = AVURLAsset(url: clip.url)
        guard let dur = try? await asset.load(.duration), dur.isNumeric else { return nil }
        let g = AVAssetImageGenerator(asset: asset)
        g.appliesPreferredTrackTransform = true
        g.maximumSize = CGSize(width: pixels, height: pixels)
        // Nearest keyframe: one decode, no walking the GOP.
        g.requestedTimeToleranceBefore = CMTime(seconds: 1, preferredTimescale: 600)
        g.requestedTimeToleranceAfter = CMTime(seconds: 1, preferredTimescale: 600)
        guard let img = try? await g.image(at: CMTime(seconds: dur.seconds * 0.3, preferredTimescale: 600)).image
        else { return nil }
        if let d = encode(img) {
            MediaCache.touch(cacheURL.deletingLastPathComponent(), video: clip.url)
            MediaCache.save(Poster(size: clip.size, mtime: mtime, pixels: pixels, data: d), to: cacheURL)
        }
        return img
    }

    nonisolated private static func encode(_ img: CGImage) -> Data? {
        for type in ["public.heic", "public.jpeg"] {
            let data = NSMutableData()
            guard let dest = CGImageDestinationCreateWithData(data, type as CFString, 1, nil) else { continue }
            CGImageDestinationAddImage(dest, img, [kCGImageDestinationLossyCompressionQuality: 0.6] as CFDictionary)
            if CGImageDestinationFinalize(dest), data.length > 0 { return data as Data }
        }
        return nil
    }

    nonisolated private static func decode(_ data: Data) -> CGImage? {
        guard let src = CGImageSourceCreateWithData(data as CFData, nil) else { return nil }
        return CGImageSourceCreateImageAtIndex(src, 0, nil)
    }
}

/// At most `limit` callers between enter() and leave() at once. Last in,
/// first out: after a fast scroll the rows now on screen go before the ones
/// scrolled past. A caller cancelled while it waits gets false and must not
/// call leave().
actor Gate {
    private let limit: Int
    private var running = 0
    private var waiting: [(id: Int, go: CheckedContinuation<Bool, Never>)] = []
    private var nextID = 0

    init(limit: Int) { self.limit = limit }

    func enter() async -> Bool {
        if Task.isCancelled { return false }
        if running < limit { running += 1; return true }
        nextID += 1
        let id = nextID
        return await withTaskCancellationHandler {
            await withCheckedContinuation { waiting.append((id, $0)) }
        } onCancel: {
            Task { await self.drop(id) }
        }
    }

    private func drop(_ id: Int) {
        if let i = waiting.firstIndex(where: { $0.id == id }) { waiting.remove(at: i).go.resume(returning: false) }
    }

    func leave() {
        if waiting.isEmpty { running -= 1 } else { waiting.removeLast().go.resume(returning: true) }
    }
}
