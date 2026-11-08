import AVFoundation
import Foundation

/// Audio peaks for the timeline: one 0…1 value per `bucket` seconds of the
/// file's first audio track (max |sample| across channels). Built in the
/// background right after open — the bar fills in left to right — and kept
/// in the MediaCache as `waveform.bin`, so the next open is instant. A file on
/// a network volume waits for `build()` (the "Build" button under the video).
@MainActor
final class WaveformModel: ObservableObject {
    /// Peaks so far, 0…1, bucket k covers [k × bucket, (k+1) × bucket) seconds.
    @Published private(set) var peaks: [Float] = []
    /// True while the analysis is still running (the tail of `peaks` is growing).
    @Published private(set) var building = false
    nonisolated static let bucket = 0.01     // 10 ms → 100 columns per second

    private struct Cache: Codable { var size: Int; var mtime: Int; var bucket: Double; var peaks: Data }
    private var task: Task<Void, Never>?
    nonisolated private static func log(_ m: String) {
        FileHandle.standardError.write(("edit-review: waveform: " + m + "\n").data(using: .utf8)!)
    }
    /// Routine progress, only with EDIT_REVIEW_DEBUG set (failures always go to log).
    nonisolated private static let verbose = ProcessInfo.processInfo.environment["EDIT_REVIEW_DEBUG"] != nil
    nonisolated private static func trace(_ m: String) { if verbose { log(m) } }
    private var cacheURL: URL?
    /// What `build()` reads, set by a load() that missed the cache.
    private var source: (asset: AVAsset, duration: Double, size: Int, mtime: Int)?

    /// Read the cached peaks for a file with this size / mtime `stamp`; false
    /// on a miss, which `build()` then fills.
    func load(cacheURL: URL, asset: AVAsset, duration: Double, stamp: (size: Int, mtime: Int)) -> Bool {
        task?.cancel()
        peaks = []
        building = false
        source = nil
        self.cacheURL = cacheURL
        if let saved = MediaCache.load(Cache.self, from: cacheURL),
           saved.size == stamp.size, saved.mtime == stamp.mtime, saved.bucket == Self.bucket {
            peaks = saved.peaks.withUnsafeBytes { Array($0.bindMemory(to: Float.self)) }
            Self.trace("cache hit, \(peaks.count) buckets")
            return true
        }
        source = (asset, duration, stamp.size, stamp.mtime)
        return false
    }

    func build() {
        guard let src = source, !building else { return }
        let (asset, duration, size, mtime) = (src.asset, src.duration, src.size, src.mtime)
        building = true
        Self.trace("building, \(Int((duration / Self.bucket).rounded(.up))) buckets")
        let total = Int((duration / Self.bucket).rounded(.up))
        task = Task.detached(priority: .utility) { [weak self] in
            var pending: [Float] = []
            var lastFlush = Date()
            func flush() async {
                guard !pending.isEmpty else { return }
                let p = pending; pending = []
                let me = self
                await MainActor.run { me?.absorb(p) }
            }
            let ok = await Self.analyze(asset: asset, total: total) { chunk in
                pending.append(contentsOf: chunk)
                if Date().timeIntervalSince(lastFlush) > 0.4 { await flush(); lastFlush = Date() }
                return !Task.isCancelled
            }
            await flush()
            let me = self
            await MainActor.run { me?.finish(complete: ok, size: size, mtime: mtime) }
        }
    }

    private func absorb(_ chunk: [Float]) {
        peaks.append(contentsOf: chunk)
    }

    private func finish(complete: Bool, size: Int, mtime: Int) {
        building = false
        Self.trace("finished complete=\(complete) buckets=\(peaks.count)")
        guard complete, !peaks.isEmpty, let url = cacheURL else { return }
        source = nil
        // Normalise so a quiet file still shows a readable shape.
        let top = peaks.max() ?? 1
        if top > 0, top < 0.9 { let g = 0.9 / top; peaks = peaks.map { min(1, $0 * g) } }
        MediaCache.save(Cache(size: size, mtime: mtime, bucket: Self.bucket,
                              peaks: peaks.withUnsafeBufferPointer { Data(buffer: $0) }), to: url)
    }

    /// Decode the first audio track to 16-bit PCM and fold it into buckets.
    /// `emit` gets each finished run of buckets; returning false stops the read.
    /// Returns true when the whole track was read.
    nonisolated private static func analyze(asset: AVAsset, total: Int,
                                            emit: ([Float]) async -> Bool) async -> Bool {
        guard let tracks = try? await asset.loadTracks(withMediaType: .audio), let track = tracks.first,
              let reader = try? AVAssetReader(asset: asset) else { log("no audio track / reader"); return false }
        let settings: [String: Any] = [
            AVFormatIDKey: kAudioFormatLinearPCM,
            AVLinearPCMBitDepthKey: 16,
            AVLinearPCMIsFloatKey: false,
            AVLinearPCMIsBigEndianKey: false,
            AVLinearPCMIsNonInterleaved: false,
        ]
        let out = AVAssetReaderTrackOutput(track: track, outputSettings: settings)
        out.alwaysCopiesSampleData = false
        reader.add(out)
        guard reader.startReading() else { log("startReading failed: \(String(describing: reader.error))"); return false }
        trace("reading")
        defer { if reader.status == .reading { reader.cancelReading() } }

        var done: [Float] = []           // finished buckets not yet emitted
        var cur: Int32 = 0               // running max |sample| of the open bucket
        var curIndex = 0                 // bucket index of the open one
        var samplesInBucket = 0
        var samplesPerBucket = 0
        var channels = 1
        var raw: [Int16] = []

        while let sb = out.copyNextSampleBuffer() {
            if samplesPerBucket == 0, let fd = CMSampleBufferGetFormatDescription(sb),
               let asbd = CMAudioFormatDescriptionGetStreamBasicDescription(fd)?.pointee {
                channels = max(1, Int(asbd.mChannelsPerFrame))
                samplesPerBucket = max(1, Int((asbd.mSampleRate * bucket).rounded()))
                // The first buffer's timestamp places the open bucket.
                let t = CMSampleBufferGetPresentationTimeStamp(sb)
                if t.isNumeric, t.seconds > 0 {
                    curIndex = Int(t.seconds / bucket)
                    done.append(contentsOf: [Float](repeating: 0, count: curIndex))
                }
            }
            guard let block = CMSampleBufferGetDataBuffer(sb) else { continue }
            var length = 0
            var ptr: UnsafeMutablePointer<Int8>?
            guard CMBlockBufferGetDataPointer(block, atOffset: 0, lengthAtOffsetOut: nil,
                                              totalLengthOut: &length, dataPointerOut: &ptr) == noErr,
                  let p = ptr else { continue }
            let n = length / 2
            // Copy: the block may not be contiguous / aligned for a direct Int16 view.
            if raw.count < n { raw = [Int16](repeating: 0, count: n) }
            raw.withUnsafeMutableBytes { dst in
                dst.copyMemory(from: UnsafeRawBufferPointer(start: p, count: n * 2))
            }
            var i = 0
            let frames = n / channels
            for _ in 0..<frames {
                var m: Int32 = 0
                for c in 0..<channels {
                    let v = Int32(raw[i + c])
                    let a = v < 0 ? -v : v
                    if a > m { m = a }
                }
                i += channels
                if m > cur { cur = m }
                samplesInBucket += 1
                if samplesInBucket >= samplesPerBucket {
                    done.append(Float(cur) / 32768)
                    cur = 0; samplesInBucket = 0; curIndex += 1
                }
            }
            if done.count >= 200 {
                let chunk = done; done = []
                if await !emit(chunk) { return false }
            }
        }
        if samplesInBucket > 0 { done.append(Float(cur) / 32768) }
        // Pad to the file length so the last columns are not blank.
        let have = curIndex + (samplesInBucket > 0 ? 1 : 0)
        if total > have { done.append(contentsOf: [Float](repeating: 0, count: total - have)) }
        if !done.isEmpty, await !emit(done) { return false }
        if reader.status == .failed { log("read failed: \(String(describing: reader.error))") }
        else { trace("read done status=\(reader.status.rawValue)") }
        return reader.status != .failed
    }
}
