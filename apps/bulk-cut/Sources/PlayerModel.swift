import AVFoundation
import Combine
import Foundation

/// What the clip list shows under a name, read from the file's header.
struct VideoInfo: Equatable, Sendable {
    var duration: Double
    /// Exact rate: 24000/1001 for "23.976" and so on (see knownRate).
    var fps: Double
    var width: Int
    var height: Int
    var codec: String

    /// The size as shown once turned `turns` quarter turns.
    func size(turns: Int) -> CGSize { Picture.turned(CGSize(width: width, height: height), turns: turns) }

    var fpsLabel: String {
        let r = (fps * 1000).rounded() / 1000
        return r == r.rounded() ? String(Int(r)) : String(format: "%.3f", r).replacingOccurrences(of: "0+$", with: "", options: .regularExpression)
    }
}

/// AVPlayer wrapper for the clip on screen: play / pause at a speed, chained
/// frame-accurate seeks, a published playhead in seconds, and the waveform.
@MainActor
final class PlayerModel: ObservableObject {
    let player = AVPlayer()
    @Published private(set) var currentSeconds: Double = 0
    @Published private(set) var isPlaying = false
    @Published private(set) var speed: Double = 1
    @Published private(set) var duration: Double = 0
    /// The file on screen; nil while none is loaded or one is loading.
    @Published private(set) var loadedURL: URL?
    private(set) var fps: Double = 30
    /// Where the picture starts (see firstFrameTime(of:)); the playhead stays at or after it.
    private(set) var firstFrame: Double = 0
    /// Audio peaks for the timeline, built in the background after load.
    let waveform = WaveformModel()
    /// A network file whose waveform was not built on load: the timeline offers a button.
    @Published private(set) var waveformDeferred = false

    private var timeObserver: Any?
    /// Sections-only playback (AppModel.syncPlayback): the stretches to play,
    /// sorted and merged. Playing out of one jumps to the next; out of the
    /// last it stops there, or with `loop` goes back to the first. Empty: the
    /// whole file plays (and `loop` loops it). Only an end crossed while
    /// playing jumps, so a playhead put in the grey by hand plays the grey.
    @Published private(set) var sections: [ClosedRange<Double>] = []
    private(set) var loop = false
    /// Focused playback (AppModel.focus): `sections` are in the order they
    /// play, not by time, and the end of each one goes to `onSectionEnd`,
    /// which picks what plays next, in this file or in another.
    private(set) var ordered = false
    var onSectionEnd: (@MainActor (ClosedRange<Double>) -> Void)?
    /// Stopped at the end of the last section: play starts over at the first.
    private(set) var atSectionsEnd = false
    private var boundaryObserver: Any?
    /// True between the first drag event on the timeline and the release.
    private(set) var isScrubbing = false
    /// Bumped by every load / unload; a load that finds it changed gave way to a newer one.
    private var loadToken = 0
    private var cancellables = Set<AnyCancellable>()

    // Chained seeking: AVPlayer drops an in-flight seek when another arrives,
    // so key repeat or a fast drag would show only a few of them. Keep exactly
    // one seek in flight and coalesce the rest into `chase`; the newest lands.
    private struct SeekTarget { var time: CMTime; var tolerance: CMTime }
    private var chase: SeekTarget?
    private var seekInFlight = false
    private var scrubTolerance = CMTime(seconds: 0.1, preferredTimescale: 600)

    /// TAB / ⇧TAB step through these, wrapping at either end (as in edit-review).
    static let speeds: [Double] = [1, 1.5, 1.7, 2, 2.5, 3]

    var speedLabel: String {
        (speed == speed.rounded() ? String(Int(speed)) : String(speed)) + "×"
    }

    init() {
        player.actionAtItemEnd = .pause
        NotificationCenter.default.publisher(for: .AVPlayerItemDidPlayToEndTime)
            .receive(on: RunLoop.main)
            .sink { [weak self] n in
                guard let self, (n.object as? AVPlayerItem) === self.player.currentItem else { return }
                // A focused section running to the end of the file has no boundary of its own.
                if self.ordered, self.isPlaying, let next = self.onSectionEnd,
                   let r = self.sections.first(where: { $0.upperBound >= self.lastFrameTime }) {
                    next(r)
                    return
                }
                if self.loop, self.isPlaying {
                    self.seek(to: self.sections.first?.lowerBound ?? 0)
                    self.player.rate = Float(self.speed)
                    return
                }
                self.isPlaying = false
            }
            .store(in: &cancellables)
    }

    /// Read a file's header: duration, rate, picture size, codec.
    nonisolated static func probe(_ url: URL) async throws -> VideoInfo {
        try await probe(AVURLAsset(url: url)).info
    }

    nonisolated private static func probe(_ asset: AVURLAsset) async throws -> (info: VideoInfo, tracks: [AVAssetTrack]) {
        let (tracks, dur) = try await asset.load(.tracks, .duration)
        guard let video = tracks.first(where: { $0.mediaType == .video }) else {
            throw NSError(domain: "bulk-cut", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: "no video track in \(asset.url.lastPathComponent)"])
        }
        let (nominal, size, transform, fds) = try await video.load(.nominalFrameRate, .naturalSize,
                                                                   .preferredTransform, .formatDescriptions)
        let shown = size.applying(transform)
        let codec = fds.first.map { codecName(CMFormatDescriptionGetMediaSubType($0)) } ?? "?"
        // A variable-rate phone file reports an average (23.405); its shortest
        // frame gives the rate it was shot at.
        var fps = knownRate(Double(nominal))
        if fps == nil, let minDur = try? await video.load(.minFrameDuration), minDur.isNumeric, minDur.seconds > 0 {
            fps = knownRate(1 / minDur.seconds)
        }
        return (VideoInfo(duration: dur.seconds, fps: fps ?? (nominal > 0 ? Double(nominal) : 30),
                          width: Int(abs(shown.width).rounded()), height: Int(abs(shown.height).rounded()),
                          codec: codec), tracks)
    }

    nonisolated private static func codecName(_ t: FourCharCode) -> String {
        let s = String(bytes: [UInt8(t >> 24 & 255), UInt8(t >> 16 & 255), UInt8(t >> 8 & 255), UInt8(t & 255)],
                       encoding: .ascii) ?? "?"
        switch s {
        case "hvc1", "hev1": return "HEVC"
        case "avc1", "avc3": return "H.264"
        case "apcn", "apch", "apcs", "apco", "ap4h", "ap4x": return "ProRes"
        default: return s.trimmingCharacters(in: .whitespaces)
        }
    }

    /// A common rate within 0.02 of `f`, with the "23.976" family as exact
    /// NTSC rationals (frame boundaries then land on whole units of the
    /// 600 000 timescale the export uses); nil for anything else.
    nonisolated static func knownRate(_ f: Double) -> Double? {
        let known: [Double] = [24000.0 / 1001, 24, 25, 30000.0 / 1001, 30, 50, 60000.0 / 1001, 60,
                               100, 120000.0 / 1001, 120]
        return known.first { abs($0 - f) < 0.02 }
    }

    func load(url: URL) async throws -> VideoInfo {
        loadToken += 1
        let token = loadToken
        loadedURL = nil
        let asset = AVURLAsset(url: url, options: [AVURLAssetPreferPreciseDurationAndTimingKey: true])
        let (info, tracks) = try await Self.probe(asset)
        let first = await Self.firstFrameTime(of: tracks)
        guard token == loadToken else { throw CancellationError() }

        fps = info.fps
        firstFrame = first
        duration = info.duration
        scrubTolerance = CMTime(seconds: info.width * info.height <= 2_200_000 ? 0.1 : 0.3, preferredTimescale: 600)
        chase = nil
        seekInFlight = false
        isScrubbing = false
        let item = AVPlayerItem(asset: asset)
        item.audioTimePitchAlgorithm = .timeDomain
        player.replaceCurrentItem(with: item)
        installObserver()
        clearSections()
        currentSeconds = 0
        isPlaying = false
        if first > 0 { seek(to: first) }
        loadedURL = url

        let cacheDir = MediaCache.dir(for: url)
        Task.detached(priority: .utility) { MediaCache.touch(cacheDir, video: url) }
        let stamp = Self.fileStamp(url)
        waveformDeferred = false
        if !waveform.load(cacheURL: cacheDir.appendingPathComponent("waveform.bin"), asset: asset,
                          duration: duration, stamp: stamp) {
            if MediaCache.isLocal(url) { waveform.build() } else { waveformDeferred = true }
        }
        return info
    }

    /// Nothing on screen — before a file under the player is trashed or replaced.
    func unload() {
        loadToken += 1
        player.pause()
        player.replaceCurrentItem(with: nil)
        clearSections()
        loadedURL = nil
        isPlaying = false
        duration = 0
        firstFrame = 0
        currentSeconds = 0
        waveformDeferred = false
        waveform.reset()
    }

    func buildWaveform() {
        waveformDeferred = false
        waveform.build()
    }

    /// A cut file's edit list can open the video with an empty edit — a frame
    /// or two with no picture while the audio runs — and the player, paused
    /// there, shows black. The first real frame starts where it ends.
    nonisolated private static func firstFrameTime(of tracks: [AVAssetTrack]) async -> Double {
        guard let video = tracks.first(where: { $0.mediaType == .video }),
              let segments = try? await video.load(.segments),
              let first = segments.first(where: { !$0.isEmpty }) else { return 0 }
        let t = first.timeMapping.target.start.seconds
        return t.isFinite && t > 0 ? t : 0
    }

    private static func fileStamp(_ url: URL) -> (size: Int, mtime: Int) {
        let attrs = (try? FileManager.default.attributesOfItem(atPath: url.path)) ?? [:]
        return ((attrs[.size] as? Int) ?? 0,
                Int((attrs[.modificationDate] as? Date)?.timeIntervalSince1970 ?? 0))
    }

    private func installObserver() {
        if let o = timeObserver { player.removeTimeObserver(o); timeObserver = nil }
        let interval = CMTime(value: 1, timescale: CMTimeScale(max(24, Int(fps.rounded()) * 2)))
        timeObserver = player.addPeriodicTimeObserver(forInterval: interval, queue: .main) { [weak self] t in
            guard t.isNumeric else { return }
            MainActor.assumeIsolated {
                guard let self, !self.isScrubbing, !self.seekInFlight, self.chase == nil else { return }
                self.currentSeconds = t.seconds
            }
        }
    }

    // MARK: sections

    func setPlayback(sections s: [ClosedRange<Double>], loop l: Bool, ordered o: Bool = false) {
        loop = l
        ordered = o
        guard s != sections else { return }
        sections = s
        if s.isEmpty { atSectionsEnd = false }
        installBoundaries()
    }

    private func clearSections() {
        if let o = boundaryObserver { player.removeTimeObserver(o); boundaryObserver = nil }
        sections = []
        ordered = false
        atSectionsEnd = false
    }

    /// One boundary per section end; one at the end of the file is the
    /// item's own end (init).
    private func installBoundaries() {
        if let o = boundaryObserver { player.removeTimeObserver(o); boundaryObserver = nil }
        let ends = sections.map(\.upperBound).filter { $0 < lastFrameTime }
        guard player.currentItem != nil, !ends.isEmpty else { return }
        let times = ends.map { NSValue(time: CMTime(seconds: $0, preferredTimescale: 600_000)) }
        boundaryObserver = player.addBoundaryTimeObserver(forTimes: times, queue: .main) { [weak self] in
            MainActor.assumeIsolated { self?.sectionEnded() }
        }
    }

    private func sectionEnded() {
        guard isPlaying, !isScrubbing, let last = sections.last else { return }
        let t = player.currentTime().seconds
        guard t.isFinite else { return }
        if ordered, let next = onSectionEnd {
            // The one that ended: of those begun before now, the one whose end is nearest.
            if let r = sections.filter({ $0.lowerBound < t }).min(by: { abs($0.upperBound - t) < abs($1.upperBound - t) }) {
                next(r)
            }
            return
        }
        if let next = sections.first(where: { $0.lowerBound > t }) {
            seek(to: next.lowerBound)                   // still playing: it plays on from there
        } else if loop, let first = sections.first {
            seek(to: first.lowerBound)
        } else {
            stop(atEndOf: last)
        }
    }

    /// Stop on the last kept frame of `r`: play then starts over at the first section.
    func stop(atEndOf r: ClosedRange<Double>) {
        pause()
        seek(to: r.upperBound - 0.5 / max(fps, 1))
        atSectionsEnd = true
    }

    // MARK: transport

    func play() {
        guard player.currentItem != nil, loadedURL != nil else { return }
        if atSectionsEnd || (duration > 0 && currentSeconds >= lastFrameTime - 0.01) {
            seek(to: sections.first?.lowerBound ?? 0)
        }
        player.rate = Float(speed)
        isPlaying = true
    }

    func pause() {
        player.pause()
        isPlaying = false
        if let t = player.currentItem?.currentTime(), t.isNumeric, !seekInFlight, chase == nil {
            currentSeconds = t.seconds
        }
    }

    /// The middle of the last frame: seeking to the exact duration shows nothing on some files.
    private var lastFrameTime: Double { max(0, duration - 0.5 / max(fps, 1)) }

    func seek(to seconds: Double) {
        let s = min(max(firstFrame, seconds), lastFrameTime)
        currentSeconds = s
        atSectionsEnd = false
        enqueueSeek(SeekTarget(time: CMTime(seconds: s, preferredTimescale: 600_000), tolerance: .zero))
    }

    func seek(by delta: Double) { seek(to: currentSeconds + delta) }

    /// Drag on the timeline: tolerant seeks so the picture keeps up with the
    /// pointer; `endScrub` lands the exact frame when the drag ends.
    func scrub(to seconds: Double) {
        isScrubbing = true
        let s = min(max(firstFrame, seconds), lastFrameTime)
        currentSeconds = s
        atSectionsEnd = false
        enqueueSeek(SeekTarget(time: CMTime(seconds: s, preferredTimescale: 600_000), tolerance: scrubTolerance))
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

    // MARK: frames

    /// Index of the frame on screen at `t` (constant-rate; a variable-rate
    /// phone file lands within a frame).
    func frameIndex(_ t: Double) -> Int { max(0, Int((t * fps + 1e-6).rounded(.down))) }
    /// Where the frame on screen at `t` starts: an in point.
    func frameStart(_ t: Double) -> Double { Double(frameIndex(t)) / fps }
    /// Where the frame on screen at `t` ends: an out point that keeps it.
    func frameEnd(_ t: Double) -> Double { min(duration, Double(frameIndex(t) + 1) / fps) }
    /// The nearest frame boundary, for dragged range edges.
    func nearestBoundary(_ t: Double) -> Double { min(duration, max(0, (t * fps).rounded() / fps)) }

    /// Pause and move `n` frames, landing mid-frame so the frame is unambiguous.
    func step(frames n: Int) {
        if isPlaying { pause() }
        seek(to: (Double(frameIndex(currentSeconds) + n) + 0.5) / fps)
    }

    /// Show the frame that starts at boundary `t` (or, `before`, the one ending there).
    func show(boundary t: Double, before: Bool) {
        scrub(to: t + (before ? -0.5 : 0.5) / fps)
    }

    func cycleSpeed(_ step: Int = 1) {
        let n = Self.speeds.count
        let i = Self.speeds.firstIndex(of: speed) ?? 0
        speed = Self.speeds[((i + step) % n + n) % n]
        if isPlaying { player.rate = Float(speed) }
    }

    func timecode(_ t: Double) -> String { Timecode.string(seconds: t, fps: fps) }
}
