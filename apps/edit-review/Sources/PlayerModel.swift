import AVFoundation
import Combine
import Foundation
import ImageIO

struct VideoInfo {
    var fps: Double
    var duration: Double
    /// Start label of the file's timecode track, or "00:00:00:00" if none.
    var startTimecode: String
}

/// AVPlayer wrapper: play/pause at a chosen speed, frame-accurate seeks, and
/// a published playhead in seconds.
@MainActor
final class PlayerModel: ObservableObject {
    let player = AVPlayer()
    @Published private(set) var currentSeconds: Double = 0
    @Published private(set) var isPlaying = false
    @Published private(set) var speed: Double = 1
    @Published private(set) var duration: Double = 0
    private(set) var fps: Double = 30
    /// Width / height of the picture, for laying out thumbnails before any is decoded.
    private(set) var aspect: Double = 16.0 / 9.0
    /// Audio peaks for the timeline, built in the background after open.
    let waveform = WaveformModel()
    /// Build missing caches (waveform, storyboard, cut thumbnails) without
    /// asking: true for a file on this Mac's disks, false on a network volume
    /// until buildCaches(). Every builder checks it through mayBuild().
    private var autoBuild = true
    /// A network file with a cache missing: the timeline offers a Build button.
    @Published private(set) var cachesDeferred = false
    /// The frames the clip strip wants (buildCutThumbs), kept for buildCaches().
    private var cutFrames: [Int] = []

    private var timeObserver: Any?
    /// True between the first drag event on the seek bar and the release.
    private(set) var isScrubbing = false
    private var imageGenerator: AVAssetImageGenerator?

    // Cut thumbnails: the first and last frame of every clip, frame-exact and
    // small, for the clip strip. Built once in the background when the cuts
    // load and kept in the MediaCache as `cutthumbs.bin`; until a frame is there
    // the strip shows the scrub storyboard's nearest image inside the clip.
    /// Bumped whenever new thumbnails (either kind) arrive, so the strip redraws.
    @Published private(set) var thumbsVersion = 0
    private var cutThumbs: [Int: Data] = [:]
    /// Longest side of a cut thumbnail in pixels: 2× a 72-pt strip at 16:9, with headroom.
    /// Kept in the cache's `step` field, so a change here rebuilds old caches.
    nonisolated private static let cutThumbPixels = 288.0
    private var cutThumbsURL: URL?
    private var cutThumbTask: Task<Void, Never>?
    private var currentAsset: AVAsset?
    /// Decoded images for the strip, newest last. Keys: frame index for exact
    /// thumbnails, -(bucket + 1) for storyboard ones.
    private var stripImages: [Int: CGImage] = [:]
    private var stripOrder: [Int] = []
    private var cancellables = Set<AnyCancellable>()

    // Chained seeking: AVPlayer drops an in-flight seek when another arrives,
    // so a fast drag that fires one per mouse event shows only a few of them.
    // Keep exactly one seek in flight and coalesce the rest into `chase`;
    // the newest target always lands.
    private struct SeekTarget { var time: CMTime; var tolerance: CMTime }
    private var chase: SeekTarget?
    private var seekInFlight = false
    /// Drag tolerance: nearest-ish frame is plenty while the pointer moves;
    /// HD decodes so fast that a tight window still keeps up, 4K gets a wider one.
    private var scrubTolerance = CMTime(seconds: 0.3, preferredTimescale: 600)

    // Storyboard: one small HEIC every `thumbStep` seconds, built in the
    // background right after open (coarse to fine, so the whole bar has
    // coverage within seconds) and kept in the MediaCache as `storyboard.bin`,
    // so the next open is instant. A network file waits for buildCaches().
    // Hover then decodes a ~5 KB image instead of asking AVAssetImageGenerator
    // for a frame, which costs a few hundred ms per call on a long file.
    private var thumbs: [Int: Data] = [:]
    nonisolated private static let thumbStep = 2.0
    private struct Storyboard: Codable { var size: Int; var mtime: Int; var step: Double; var frames: [Int: Data] }
    private var storyboardTask: Task<Void, Never>?
    private var storyboardURL: URL?
    private var storyboardDirty = false

    static let speeds: [Double] = [1, 1.5, 1.7, 2, 2.5, 3]

    /// "1×", "1.5×", "2×" — trailing ".0" dropped.
    var speedLabel: String {
        let s = speed == speed.rounded() ? String(Int(speed)) : String(speed)
        return s + "×"
    }

    init() {
        player.actionAtItemEnd = .pause
        NotificationCenter.default.publisher(for: .AVPlayerItemDidPlayToEndTime)
            .receive(on: RunLoop.main)
            .sink { [weak self] _ in self?.isPlaying = false }
            .store(in: &cancellables)
    }

    func load(url: URL) async throws -> VideoInfo {
        let asset = AVURLAsset(url: url)
        let (tracks, dur) = try await asset.load(.tracks, .duration)
        guard let video = tracks.first(where: { $0.mediaType == .video }) else {
            throw NSError(domain: "edit-review", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: "no video track in \(url.lastPathComponent)"])
        }
        let nominal = Double(try await video.load(.nominalFrameRate))
        fps = Self.snapFrameRate(nominal)
        duration = dur.seconds
        let size = (try? await video.load(.naturalSize)) ?? .zero
        let hd = size.width * size.height <= 2_200_000       // up to 1080p / 2K
        if size.width > 0, size.height > 0 { aspect = Double(size.width / size.height) }
        scrubTolerance = CMTime(seconds: hd ? 0.1 : 0.3, preferredTimescale: 600)
        let startTC = await Self.readTimecodeStart(asset: asset, tracks: tracks, fps: fps) ?? "00:00:00:00"

        let g = AVAssetImageGenerator(asset: asset)
        g.appliesPreferredTrackTransform = true
        g.maximumSize = CGSize(width: 384, height: 384)
        g.requestedTimeToleranceBefore = CMTime(seconds: 1, preferredTimescale: 600)   // nearest keyframe: cheap
        g.requestedTimeToleranceAfter = CMTime(seconds: 1, preferredTimescale: 600)
        imageGenerator = g
        storyboardTask?.cancel()
        chase = nil
        seekInFlight = false
        isScrubbing = false

        let item = AVPlayerItem(asset: asset)
        item.audioTimePitchAlgorithm = .timeDomain
        player.replaceCurrentItem(with: item)
        installObserver()
        currentSeconds = 0
        isPlaying = false
        autoBuild = MediaCache.isLocal(url)
        cachesDeferred = false
        fileStamp = Self.fileStamp(url)
        let cacheDir = MediaCache.dir(for: url)
        Task.detached(priority: .utility) { MediaCache.touch(cacheDir, video: url) }
        loadStoryboard(cacheDir: cacheDir)
        loadCutThumbs(cacheDir: cacheDir, asset: asset)
        if !waveform.load(cacheURL: cacheDir.appendingPathComponent("waveform.bin"), asset: asset,
                          duration: duration, stamp: fileStamp), mayBuild() {
            waveform.build()
        }
        return VideoInfo(fps: fps, duration: duration, startTimecode: startTC)
    }

    /// 23.976 / 29.97 / 59.94 come back from AVFoundation as 23.976025 etc.;
    /// pin them (and plain integer rates) to their canonical values.
    static func snapFrameRate(_ f: Double) -> Double {
        let known: [Double] = [23.976, 24, 25, 29.97, 30, 50, 59.94, 60, 100, 119.88, 120]
        if let k = known.first(where: { abs($0 - f) < 0.02 }) { return k }
        return f > 0 ? f : 30
    }

    /// First sample of the `tmcd`/`tc64` track → frame number → label.
    private static func readTimecodeStart(asset: AVAsset, tracks: [AVAssetTrack], fps: Double) async -> String? {
        guard let tc = tracks.first(where: { $0.mediaType == .timecode }) else { return nil }
        guard let fds = try? await tc.load(.formatDescriptions), let fd = fds.first,
              let reader = try? AVAssetReader(asset: asset) else { return nil }
        let out = AVAssetReaderTrackOutput(track: tc, outputSettings: nil)
        reader.add(out)
        guard reader.startReading(),
              let sb = out.copyNextSampleBuffer(),
              let block = CMSampleBufferGetDataBuffer(sb) else { reader.cancelReading(); return nil }
        defer { reader.cancelReading() }
        var length = 0
        var ptr: UnsafeMutablePointer<Int8>?
        guard CMBlockBufferGetDataPointer(block, atOffset: 0, lengthAtOffsetOut: nil,
                                          totalLengthOut: &length, dataPointerOut: &ptr) == noErr,
              let p = ptr else { return nil }
        let subtype = CMFormatDescriptionGetMediaSubType(fd)
        var frames: Int
        if subtype == kCMTimeCodeFormatType_TimeCode64, length >= 8 {
            frames = Int(Int64(bigEndian: UnsafeRawPointer(p).loadUnaligned(as: Int64.self)))
        } else if length >= 4 {
            frames = Int(Int32(bigEndian: UnsafeRawPointer(p).loadUnaligned(as: Int32.self)))
        } else {
            return nil
        }
        // A negative value marks an invalid/unset timecode.
        guard frames >= 0 else { return nil }
        let flags = CMTimeCodeFormatDescriptionGetTimeCodeFlags(fd)
        if flags & UInt32(kCMTimeCodeFlag_DropFrame) != 0 {
            return Timecode.dropFrameString(frames: frames, fps: fps)
        }
        return Timecode.string(frames: frames, fps: fps)
    }

    private func installObserver() {
        if let o = timeObserver { player.removeTimeObserver(o); timeObserver = nil }
        let interval = CMTime(value: 1, timescale: CMTimeScale(max(24, Int(fps.rounded()) * 2)))
        timeObserver = player.addPeriodicTimeObserver(forInterval: interval, queue: .main) { [weak self] t in
            guard t.isNumeric else { return }
            MainActor.assumeIsolated {
                guard let self, !self.isScrubbing else { return }
                self.currentSeconds = t.seconds
            }
        }
    }

    func play() {
        guard player.currentItem != nil else { return }
        if duration > 0, currentSeconds >= duration - 0.05 { seek(to: 0) }
        player.rate = Float(speed)
        isPlaying = true
    }

    func pause() {
        player.pause()
        isPlaying = false
        if let t = player.currentItem?.currentTime(), t.isNumeric { currentSeconds = t.seconds }
    }

    func seek(to seconds: Double) {
        let s = min(max(0, seconds), max(0, duration))
        currentSeconds = s
        enqueueSeek(SeekTarget(time: CMTime(seconds: s, preferredTimescale: 60000), tolerance: .zero))
    }

    func seek(by delta: Double) { seek(to: currentSeconds + delta) }

    /// Drag on the seek bar: tolerant seeks so the picture keeps up with the
    /// pointer; `endScrub` lands the exact frame when the drag ends.
    func scrub(to seconds: Double) {
        isScrubbing = true
        let s = min(max(0, seconds), max(0, duration))
        currentSeconds = s
        enqueueSeek(SeekTarget(time: CMTime(seconds: s, preferredTimescale: 60000), tolerance: scrubTolerance))
    }

    func endScrub(at seconds: Double) {
        isScrubbing = false
        seek(to: seconds)
    }

    private func enqueueSeek(_ target: SeekTarget) {
        chase = target
        pumpSeek()
    }

    private func pumpSeek() {
        guard !seekInFlight, let target = chase else { return }
        chase = nil
        seekInFlight = true
        player.seek(to: target.time, toleranceBefore: target.tolerance, toleranceAfter: target.tolerance) { [weak self] _ in
            Task { @MainActor [weak self] in
                guard let self else { return }
                self.seekInFlight = false
                self.pumpSeek()
            }
        }
    }

    // MARK: thumbnails

    /// Bucket index; the frame for bucket k is taken at k × thumbStep seconds.
    private static func thumbKey(_ seconds: Double, duration: Double) -> Int {
        Int((min(max(0, seconds), max(0, duration)) / thumbStep).rounded())
    }

    /// Storyboard frame for the second nearest `seconds`, if it is already
    /// built. Synchronous and cheap (a small JPEG decode), for hover tracking.
    func cachedThumbnail(at seconds: Double) -> CGImage? {
        thumbs[Self.thumbKey(seconds, duration: duration)].flatMap(Self.decode)
    }

    /// A small frame near `seconds` (storyboard buckets, cached) for the
    /// seek-bar hover preview. Never blocks the main thread; falls back to a
    /// one-off decode for a bucket the storyboard has not reached yet.
    func thumbnail(at seconds: Double) async -> CGImage? {
        let key = Self.thumbKey(seconds, duration: duration)
        if let c = thumbs[key] { return Self.decode(c) }
        guard let g = imageGenerator else { return nil }
        guard let result = try? await g.image(at: CMTime(seconds: Double(key) * Self.thumbStep, preferredTimescale: 600)) else { return nil }
        if thumbs[key] == nil, let d = Self.encode(result.image) { thumbs[key] = d; storyboardDirty = true }
        return result.image
    }

    /// HEIC (hardware encoder, about half the bytes of JPEG at this quality);
    /// JPEG if the machine cannot write HEIC.
    nonisolated private static func encode(_ img: CGImage) -> Data? {
        for type in ["public.heic", "public.jpeg"] {
            let data = NSMutableData()
            guard let dest = CGImageDestinationCreateWithData(data, type as CFString, 1, nil) else { continue }
            CGImageDestinationAddImage(dest, img, [kCGImageDestinationLossyCompressionQuality: 0.55] as CFDictionary)
            if CGImageDestinationFinalize(dest), data.length > 0 { return data as Data }
        }
        return nil
    }

    nonisolated private static func decode(_ data: Data) -> CGImage? {
        guard let src = CGImageSourceCreateWithData(data as CFData, nil) else { return nil }
        return CGImageSourceCreateImageAtIndex(src, 0, [kCGImageSourceShouldCache: false] as CFDictionary)
    }

    private static func fileStamp(_ url: URL) -> (size: Int, mtime: Int) {
        let attrs = (try? FileManager.default.attributesOfItem(atPath: url.path)) ?? [:]
        return ((attrs[.size] as? Int) ?? 0,
                Int((attrs[.modificationDate] as? Date)?.timeIntervalSince1970 ?? 0))
    }

    private var fileStamp = (size: 0, mtime: 0)

    /// Whether a missing cache may be built now. On a network file the answer
    /// is no until buildCaches(), and the timeline shows the Build button.
    private func mayBuild() -> Bool {
        if !autoBuild { cachesDeferred = true }
        return autoBuild
    }

    private func loadStoryboard(cacheDir: URL) {
        thumbs = [:]
        storyboardDirty = false
        storyboardURL = cacheDir.appendingPathComponent("storyboard.bin")
        if let saved = storyboardURL.flatMap({ MediaCache.load(Storyboard.self, from: $0) }),
           saved.size == fileStamp.size, saved.mtime == fileStamp.mtime, saved.step == Self.thumbStep {
            thumbs = saved.frames
        }
        buildStoryboard()
    }

    private func buildStoryboard() {
        storyboardTask?.cancel()
        let total = Int((duration / Self.thumbStep).rounded())
        let missing = (0...max(total, 0)).filter { thumbs[$0] == nil }
        guard !missing.isEmpty, let g = imageGenerator, mayBuild() else { return }
        // Coarse passes first: every 16th bucket, then the 8th offsets, 4, 2, 1.
        var order: [Int] = []
        var seen = Set<Int>()
        for step in [16, 8, 4, 2, 1] {
            for k in stride(from: 0, through: total, by: step) where !seen.contains(k) && thumbs[k] == nil {
                order.append(k); seen.insert(k)
            }
        }
        storyboardTask = Task.detached(priority: .utility) { [weak self] in
            var batch: [Int: Data] = [:]
            var lastFlush = Date()
            func flush() async {
                guard !batch.isEmpty else { return }
                let b = batch; batch = [:]
                let me = self
                await MainActor.run { me?.absorbThumbs(b) }
            }
            for start in stride(from: 0, to: order.count, by: 64) {
                if Task.isCancelled { break }
                let keys = Array(order[start..<min(start + 64, order.count)])
                let times = keys.map { CMTime(seconds: Double($0) * Self.thumbStep, preferredTimescale: 600) }
                var i = 0
                for await r in g.images(for: times) {
                    if Task.isCancelled { break }
                    if let img = try? r.image, let d = Self.encode(img) { batch[keys[i]] = d }
                    i += 1
                    if Date().timeIntervalSince(lastFlush) > 0.5 { await flush(); lastFlush = Date() }
                }
                if Task.isCancelled { break }
            }
            await flush()
            let me = self
            await MainActor.run { me?.saveStoryboard() }
        }
    }

    private func absorbThumbs(_ b: [Int: Data]) {
        for (k, v) in b where thumbs[k] == nil { thumbs[k] = v }
        storyboardDirty = true
        thumbsVersion += 1
    }

    private func saveStoryboard() {
        guard storyboardDirty, let url = storyboardURL else { return }
        storyboardDirty = false
        MediaCache.save(Storyboard(size: fileStamp.size, mtime: fileStamp.mtime, step: Self.thumbStep, frames: thumbs), to: url)
    }

    /// The Build button: make the caches a network file skipped on open.
    func buildCaches() {
        autoBuild = true
        cachesDeferred = false
        waveform.build()
        buildStoryboard()
        buildCutThumbs(frames: cutFrames)
    }

    // MARK: cut thumbnails

    private func loadCutThumbs(cacheDir: URL, asset: AVAsset) {
        cutThumbTask?.cancel()
        currentAsset = asset
        cutThumbs = [:]
        cutFrames = []
        stripImages = [:]
        stripOrder = []
        cutThumbsURL = cacheDir.appendingPathComponent("cutthumbs.bin")
        if let saved = cutThumbsURL.flatMap({ MediaCache.load(Storyboard.self, from: $0) }),
           saved.size == fileStamp.size, saved.mtime == fileStamp.mtime, saved.step == Self.cutThumbPixels {
            cutThumbs = saved.frames
        }
    }

    /// Make sure there is a thumbnail for each of `frames` (in that order of
    /// priority); frames no cut needs any more are dropped from the cache.
    func buildCutThumbs(frames: [Int]) {
        cutThumbTask?.cancel()
        guard let asset = currentAsset else { return }
        cutFrames = frames
        let wanted = Set(frames)
        let kept = cutThumbs.filter { wanted.contains($0.key) }
        var dirty = kept.count != cutThumbs.count
        cutThumbs = kept
        var seen = Set<Int>()
        let missing = frames.filter { cutThumbs[$0] == nil && seen.insert($0).inserted }
        thumbsVersion += 1
        guard !missing.isEmpty else { if dirty { saveCutThumbs() }; return }
        guard mayBuild() else { return }
        dirty = true
        let g = AVAssetImageGenerator(asset: asset)
        g.appliesPreferredTrackTransform = true
        g.maximumSize = CGSize(width: Self.cutThumbPixels, height: Self.cutThumbPixels)
        g.requestedTimeToleranceBefore = .zero
        g.requestedTimeToleranceAfter = .zero
        let f = max(fps, 1)
        cutThumbTask = Task.detached(priority: .utility) { [weak self] in
            var batch: [Int: Data] = [:]
            var lastFlush = Date()
            func flush() async {
                guard !batch.isEmpty else { return }
                let b = batch; batch = [:]
                let me = self
                await MainActor.run { me?.absorbCutThumbs(b) }
            }
            for start in stride(from: 0, to: missing.count, by: 32) {
                if Task.isCancelled { break }
                let keys = missing[start..<min(start + 32, missing.count)]
                // The middle of the frame: its first instant can round onto the one before.
                let times = keys.map { CMTime(seconds: (Double($0) + 0.5) / f, preferredTimescale: 60000) }
                for await r in g.images(for: times) {
                    if Task.isCancelled { break }
                    let key = Int((r.requestedTime.seconds * f).rounded(.down))
                    if let img = try? r.image, let d = Self.encode(img) { batch[key] = d }
                    if Date().timeIntervalSince(lastFlush) > 0.4 { await flush(); lastFlush = Date() }
                }
            }
            await flush()
            let me = self
            if !Task.isCancelled { await MainActor.run { me?.saveCutThumbs() } }
        }
    }

    private func absorbCutThumbs(_ b: [Int: Data]) {
        for (k, v) in b { cutThumbs[k] = v }
        thumbsVersion += 1
    }

    private func saveCutThumbs() {
        guard let url = cutThumbsURL, !cutThumbs.isEmpty else { return }
        MediaCache.save(Storyboard(size: fileStamp.size, mtime: fileStamp.mtime, step: Self.cutThumbPixels, frames: cutThumbs), to: url)
    }

    /// The strip's picture for one end of a clip: the exact frame if it has been
    /// made, else the scrub storyboard's image nearest that end but INSIDE
    /// [start, end) — a neighbour's frame would name the wrong clip — else nil.
    func stripThumb(frame: Int, start: Double, end: Double, atEnd: Bool) -> CGImage? {
        if let d = cutThumbs[frame] { return stripImage(key: frame, data: d) }
        let first = Int((start / Self.thumbStep).rounded(.up))
        let last = Int((end / Self.thumbStep).rounded(.up)) - 1
        guard first <= last else { return nil }
        let bucket = atEnd ? last : first
        guard let d = thumbs[bucket] else { return nil }
        return stripImage(key: -(bucket + 1), data: d)
    }

    /// A filmstrip picture for the middle of a clip: the scrub storyboard's
    /// image nearest `seconds`, from a bucket that lies inside [start, end) and,
    /// when the clip is long enough to allow it, half a second clear of both
    /// ends (the storyboard takes the nearest keyframe, which near a cut can
    /// belong to the neighbour). nil when no bucket qualifies or it is not built yet.
    func filmstripThumb(near seconds: Double, start: Double, end: Double) -> CGImage? {
        let step = Self.thumbStep
        var lo = Int(((start + 0.5) / step).rounded(.up)), hi = Int(((end - 0.5) / step).rounded(.up)) - 1
        if lo > hi { lo = Int((start / step).rounded(.up)); hi = Int((end / step).rounded(.up)) - 1 }
        guard lo <= hi else { return nil }
        let bucket = min(max(Int((seconds / step).rounded()), lo), hi)
        guard let d = thumbs[bucket] else { return nil }
        return stripImage(key: -(bucket + 1), data: d)
    }

    private func stripImage(key: Int, data: Data) -> CGImage? {
        if let c = stripImages[key] { return c }
        guard let img = Self.decode(data) else { return nil }
        stripImages[key] = img
        stripOrder.append(key)
        if stripOrder.count > 96 { stripImages[stripOrder.removeFirst()] = nil }   // a screenful is ~35
        return img
    }

    /// One step up the speed list (-1: down), wrapping round at either end.
    func cycleSpeed(_ step: Int = 1) {
        let n = Self.speeds.count
        let i = Self.speeds.firstIndex(of: speed) ?? 0
        speed = Self.speeds[(i + step % n + n) % n]
        if isPlaying { player.rate = Float(speed) }
    }
}
