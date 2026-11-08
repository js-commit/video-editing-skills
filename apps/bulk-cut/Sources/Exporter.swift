import AVFoundation
import Foundation
import os

/// One clip to cut down, turn or zoom: its settled ranges and the file each
/// one becomes.
struct CropJob: Identifiable {
    let clip: Clip
    /// One over the whole clip when only the picture changes.
    let ranges: [KeepRange]
    let outputs: [URL]
    /// Quarter turns clockwise: the track's display matrix changes; the
    /// samples are copied as they are.
    var turns = 0
    /// The part of the picture kept (in the turned frame); the video is then re-encoded.
    var zoom: ZoomRect?
    /// The zoom's size in pixels, for the sheet.
    var zoomSize: CGSize?
    /// The source's codec ("HEVC"), which a zoom re-encodes to.
    var codec = ""
    /// No time crop: the whole file is copied (a clone, on APFS), not exported.
    var whole = false
    /// What a piece's name gets: `_cropped`, or `_rotated` when it is only turned.
    var suffix = "_cropped"
    var id: URL { clip.url }
}

/// One photo to turn or crop, and the file it becomes.
struct PhotoJob: Identifiable {
    let clip: Clip
    let output: URL
    /// Quarter turns clockwise.
    var turns = 0
    /// The part kept, in the turned frame; the photo is then re-encoded.
    var crop: ZoomRect?
    /// The crop's size in pixels, for the sheet.
    var cropSize: CGSize?
    var format = ""
    /// Only the orientation tag changes.
    var lossless = false
    /// `_rotated`, or `_cropped`.
    var suffix = "_rotated"
    var id: URL { clip.url }
}

/// Everything Apply will do, worked out up front so the sheet can show it.
struct ApplyPlan {
    var trash: [Clip] = []
    var crops: [CropJob] = []
    var photos: [PhotoJob] = []
    var overwrite = false
    /// Files (to delete, or to replace with overwrite on) on a volume with
    /// no Trash, an SMB share: deleted outright.
    var noTrash: Set<URL> = []
    /// Those volumes' names, for the sheet.
    var noTrashVolumes: [String] = []

    var isEmpty: Bool { trash.isEmpty && crops.isEmpty && photos.isEmpty }
    var permanentDeletes: [Clip] { trash.filter { noTrash.contains($0.url) } }
    /// Originals replaced outright.
    var permanentReplaces: Int {
        crops.count { noTrash.contains($0.clip.url) } + photos.count { noTrash.contains($0.clip.url) }
    }
    var outputCount: Int { crops.reduce(0) { $0 + $1.outputs.count } + photos.count }
    var trashBytes: Int64 { trash.reduce(0) { $0 + $1.size } }
}

struct ApplyResult {
    var trashed: [String] = []
    /// Deleted outright: no Trash on their volume.
    var deleted: [String] = []
    var written: [String] = []
    /// The files written for each source file, by its URL.
    var outputs: [URL: [URL]] = [:]
    /// Clips fully dealt with (by Clip.key): their staged edits are dropped.
    var done: Set<String> = []
    var failures: [(name: String, why: String)] = []
}

/// Apply: staged deletes go to the Trash; crops are passthrough exports —
/// the compressed samples are copied, never decoded, so codec, bitrate,
/// colour and quality are the source's and a piece is about its share of the
/// source's size. The movie's edit list starts and ends each piece on the
/// exact frame (the samples back to the previous keyframe ride along unseen,
/// as with QuickTime Player's Trim or `ffmpeg -c copy`). A quarter turn is a
/// change to the track header (TrackHeaders), so it is lossless too. Only a
/// zoom re-encodes: compressed video can't be cropped without decoding it.
/// Photos: see Photos.write.
///
/// An SMB share has no Trash. There a delete is permanent, and an original
/// that is overwritten is set aside under a hidden name until the new files
/// are in, then deleted.
enum Exporter {
    static func plan(clips: [Clip], edits: [String: ClipEdit], infos: [URL: VideoInfo], photoInfos: [URL: PhotoInfo],
                     overwrite: Bool) -> ApplyPlan {
        var plan = ApplyPlan(overwrite: overwrite)
        // The names in each folder an output goes to, taken as they are handed out.
        var takenIn: [URL: Set<String>] = [:]
        func free(_ name: String, ext: String, in folder: URL) -> URL {
            var taken = takenIn[folder] ?? existingNames(in: folder)
            defer { takenIn[folder] = taken }
            return freeName(name, ext: ext, in: folder, taken: &taken)
        }
        for clip in clips {
            guard let e = edits[clip.key] else { continue }
            if e.deleted { plan.trash.append(clip); continue }
            let folder = clip.url.deletingLastPathComponent()
            let stem = clip.url.deletingPathExtension().lastPathComponent
            let ext = clip.url.pathExtension
            if clip.isPhoto {
                guard let info = photoInfos[clip.url], info.editable else { continue }
                let area = e.zoom?.pixels(in: info.size(turns: e.turns), even: false)
                guard e.turns != 0 || area != nil else { continue }
                let suffix = area == nil ? "_rotated" : "_cropped"
                plan.photos.append(PhotoJob(clip: clip, output: overwrite ? clip.url : free(stem + suffix, ext: ext, in: folder),
                                            turns: e.turns, crop: area == nil ? nil : e.zoom, cropSize: area?.size,
                                            format: info.format, lossless: area == nil && info.losslessTurn, suffix: suffix))
                continue
            }
            guard let info = infos[clip.url] else { continue }
            let settled = RangeOps.settle(e.ranges)
            let whole = settled.isEmpty || RangeOps.isWhole(settled, duration: info.duration, slack: 0.5 / max(info.fps, 1))
            let area = e.zoom?.pixels(in: info.size(turns: e.turns))
            guard !whole || e.turns != 0 || area != nil else { continue }
            let r = whole ? [KeepRange(start: 0, end: info.duration)] : settled
            let suffix = whole && area == nil ? "_rotated" : "_cropped"
            var outs: [URL] = []
            if overwrite, r.count == 1 {
                outs = [clip.url]
            } else {
                let base = overwrite ? stem : stem + suffix
                for i in r.indices {
                    outs.append(free(r.count == 1 ? base : "\(base)_\(i + 1)", ext: ext, in: folder))
                }
            }
            plan.crops.append(CropJob(clip: clip, ranges: r, outputs: outs, turns: e.turns,
                                      zoom: area == nil ? nil : e.zoom, zoomSize: area?.size, codec: info.codec,
                                      whole: whole, suffix: suffix))
        }
        let gone = plan.trash.map(\.url) + (overwrite ? plan.crops.map(\.clip.url) + plan.photos.map(\.clip.url) : [])
        for u in gone where !Volumes.hasTrash(u) {
            plan.noTrash.insert(u)
            let name = Volumes.name(u)
            if !plan.noTrashVolumes.contains(name) { plan.noTrashVolumes.append(name) }
        }
        return plan
    }

    private static func existingNames(in folder: URL) -> Set<String> {
        Set(((try? FileManager.default.contentsOfDirectory(atPath: folder.path)) ?? []).map { $0.lowercased() })
    }

    /// `name.ext`, or `name-2.ext`, `name-3.ext`… when that is taken.
    private static func freeName(_ name: String, ext: String, in folder: URL, taken: inout Set<String>) -> URL {
        var candidate = "\(name).\(ext)"
        var n = 2
        while taken.contains(candidate.lowercased()) { candidate = "\(name)-\(n).\(ext)"; n += 1 }
        taken.insert(candidate.lowercased())
        return folder.appendingPathComponent(candidate)
    }

    /// Do it. `progress(text, done, total)` is called before each step;
    /// `fraction` with how far a long step (a re-encode) has got.
    static func run(_ plan: ApplyPlan, progress: @MainActor (String, Int, Int) -> Void,
                    fraction: @escaping @MainActor (Double) -> Void = { _ in }) async -> ApplyResult {
        let fm = FileManager.default
        var res = ApplyResult()
        let total = plan.trash.count + plan.outputCount
        var step = 0

        for clip in plan.trash {
            let permanent = plan.noTrash.contains(clip.url)
            await progress(permanent ? "Deleting \(clip.key)" : "Moving \(clip.key) to the Trash", step, total)
            do {
                if permanent {
                    try fm.removeItem(at: clip.url)
                    res.deleted.append(clip.name)
                } else {
                    try fm.trashItem(at: clip.url, resultingItemURL: nil)
                    res.trashed.append(clip.name)
                }
                res.done.insert(clip.key)
            } catch {
                res.failures.append((clip.key, (permanent ? "not deleted: " : "not moved to the Trash: ") + error.localizedDescription))
            }
            step += 1
        }

        for job in plan.crops {
            let src = job.clip.url
            let folder = src.deletingLastPathComponent()
            let type = fileType(for: src)
            var temps: [URL] = []
            var failure: String?
            for (i, r) in job.ranges.enumerated() {
                let verb = job.zoom != nil ? "Zooming (re-encoding)" : job.whole ? "Rotating" : "Cropping"
                await progress("\(verb) \(job.clip.key) → \(job.outputs[i].lastPathComponent)", step, total)
                let tmp = folder.appendingPathComponent(".bulkcut-\(UUID().uuidString).\(src.pathExtension)")
                do {
                    if let zoom = job.zoom {
                        try await reencode(src, range: job.whole ? nil : r, turns: job.turns, zoom: zoom,
                                           to: tmp, as: type, fraction: fraction)
                    } else if job.whole {
                        // Only turned: a copy of the whole file (gyro and timecode tracks too).
                        try fm.copyItem(at: src, to: tmp)
                        try await turn(tmp, by: job.turns)
                    } else {
                        try await export(src, range: r, to: tmp, as: type)
                        if job.turns != 0 { try await turn(tmp, by: job.turns) }
                    }
                    temps.append(tmp)
                } catch {
                    failure = error.localizedDescription
                    try? fm.removeItem(at: tmp)
                    break
                }
                step += 1
            }
            if let failure {
                temps.forEach { try? fm.removeItem(at: $0) }
                res.failures.append((job.clip.key, "not cropped: \(failure)"))
                continue
            }
            place(temps, as: job.outputs, for: job.clip, suffix: job.suffix, overwrite: plan.overwrite,
                  noTrash: plan.noTrash.contains(src), into: &res)
        }

        for job in plan.photos {
            let src = job.clip.url
            let verb = job.crop != nil ? "Cropping" : "Rotating"
            await progress("\(verb) \(job.clip.key) → \(job.output.lastPathComponent)", step, total)
            let tmp = src.deletingLastPathComponent().appendingPathComponent(".bulkcut-\(UUID().uuidString).\(src.pathExtension)")
            do {
                try await Task.detached(priority: .userInitiated) {
                    try Photos.write(src, turns: job.turns, crop: job.crop, to: tmp)
                }.value
            } catch {
                try? fm.removeItem(at: tmp)
                res.failures.append((job.clip.key, "not \(job.crop != nil ? "cropped" : "rotated"): \(error.localizedDescription)"))
                step += 1
                continue
            }
            step += 1
            place([tmp], as: [job.output], for: job.clip, suffix: job.suffix, overwrite: plan.overwrite,
                  noTrash: plan.noTrash.contains(src), into: &res)
        }
        await progress("Done", total, total)
        return res
    }

    /// Put finished temp files where they go. With `overwrite`, the original
    /// goes to the Trash first and they take its place; with no Trash
    /// there, it is set aside under a hidden name, and deleted once they are
    /// all in (or put back if one fails).
    private static func place(_ temps: [URL], as planned: [URL], for clip: Clip, suffix: String, overwrite: Bool,
                              noTrash: Bool, into res: inout ApplyResult) {
        let fm = FileManager.default
        let src = clip.url
        let folder = src.deletingLastPathComponent()
        var outputs = planned
        var aside: URL?
        if overwrite {
            do {
                if noTrash {
                    let a = folder.appendingPathComponent(".bulkcut-old-\(UUID().uuidString).\(src.pathExtension)")
                    try fm.moveItem(at: src, to: a)
                    aside = a
                } else {
                    try fm.trashItem(at: src, resultingItemURL: nil)
                }
            } catch {
                // The original stays: the new files go beside it under
                // _cropped / _rotated names instead.
                var taken = existingNames(in: folder)
                let base = src.deletingPathExtension().lastPathComponent + suffix
                outputs = temps.indices.map { i in
                    freeName(temps.count == 1 ? base : "\(base)_\(i + 1)",
                             ext: src.pathExtension, in: folder, taken: &taken)
                }
                res.failures.append((clip.key, "original kept, not \(noTrash ? "replaced" : "moved to the Trash") (\(error.localizedDescription)); new files saved beside it"))
            }
        }
        var written: [URL] = []
        for (tmp, out) in zip(temps, outputs) {
            do {
                try fm.moveItem(at: tmp, to: out)
                // Same dates as the source, so the new files sort where it did.
                try? fm.setAttributes([.creationDate: clip.created, .modificationDate: clip.modified],
                                      ofItemAtPath: out.path)
                res.written.append(out.lastPathComponent)
                written.append(out)
            } catch {
                try? fm.removeItem(at: tmp)
                res.failures.append((clip.key, "\(out.lastPathComponent) not saved: \(error.localizedDescription)"))
            }
        }
        res.outputs[src] = written
        if let aside {
            if written.count == temps.count {
                do { try fm.removeItem(at: aside) } catch {
                    res.failures.append((clip.key, "the old copy is still there as the hidden file \(aside.lastPathComponent): \(error.localizedDescription)"))
                }
            } else if !fm.fileExists(atPath: src.path), (try? fm.moveItem(at: aside, to: src)) != nil {
                // Back where it was.
            } else {
                res.failures.append((clip.key, "the original is kept as the hidden file \(aside.lastPathComponent)"))
            }
        }
        if written.count == temps.count { res.done.insert(clip.key) }
    }

    /// The source's own container, so a .MP4 stays an .MP4.
    static func fileType(for url: URL) -> AVFileType {
        switch url.pathExtension.lowercased() {
        case "mp4": .mp4
        case "m4v": .m4v
        default: .mov
        }
    }

    static func time(_ s: Double) -> CMTime { CMTime(seconds: s, preferredTimescale: 600_000) }

    /// One passthrough export of [start, end), checked by reading the result back.
    static func export(_ src: URL, range r: KeepRange, to dst: URL, as type: AVFileType) async throws {
        let asset = AVURLAsset(url: src, options: [AVURLAssetPreferPreciseDurationAndTimingKey: true])
        guard let s = AVAssetExportSession(asset: asset, presetName: AVAssetExportPresetPassthrough) else {
            throw NSError(domain: "bulk-cut", code: 2, userInfo: [NSLocalizedDescriptionKey: "no passthrough export for this file"])
        }
        s.timeRange = CMTimeRange(start: time(r.start), end: time(r.end))
        s.metadata = (try? await asset.load(.metadata)) ?? []
        try await s.export(to: dst, as: type)
        let got = try await AVURLAsset(url: dst).load(.duration).seconds
        guard abs(got - r.length) < 0.25 else {
            throw NSError(domain: "bulk-cut", code: 3, userInfo: [NSLocalizedDescriptionKey:
                String(format: "the piece came out %.2f s long, expected %.2f s", got, r.length)])
        }
    }

    /// Turn a written file `k` quarter turns clockwise in its track header,
    /// checked by reading it back.
    static func turn(_ url: URL, by k: Int) async throws {
        guard let before = try await AVURLAsset(url: url).loadTracks(withMediaType: .video).first else {
            throw NSError(domain: "bulk-cut", code: 4, userInfo: [NSLocalizedDescriptionKey: "no video track to turn"])
        }
        let (size, t) = try await before.load(.naturalSize, .preferredTransform)
        let want = t.concatenating(TrackHeaders.quarterTurns(k, of: size, under: t))
        try TrackHeaders.turn(url, by: k)
        let got = try await AVURLAsset(url: url).loadTracks(withMediaType: .video).first?.load(.preferredTransform)
        guard let got, [got.a - want.a, got.b - want.b, got.c - want.c, got.d - want.d, got.tx - want.tx, got.ty - want.ty]
            .allSatisfy({ abs($0) < 0.01 }) else {
            throw NSError(domain: "bulk-cut", code: 6, userInfo: [NSLocalizedDescriptionKey: "the turned file reads back unturned"])
        }
    }

    /// A zoom: the picture (turned, if staged) cropped to the area and
    /// re-encoded at the highest quality in the source's own codec family —
    /// HEVC (an HDR clip stays HDR), ProRes, or H.264 for anything else.
    /// The preset decides the audio too (the ProRes ones write LPCM). Checked
    /// by reading the result back.
    static func reencode(_ src: URL, range r: KeepRange?, turns: Int, zoom: ZoomRect, to dst: URL,
                         as type: AVFileType, fraction: @escaping @MainActor (Double) -> Void) async throws {
        let asset = AVURLAsset(url: src, options: [AVURLAssetPreferPreciseDurationAndTimingKey: true])
        guard let track = try await asset.loadTracks(withMediaType: .video).first else {
            throw NSError(domain: "bulk-cut", code: 4, userInfo: [NSLocalizedDescriptionKey: "no video track"])
        }
        let (natural, transform, fds) = try await track.load(.naturalSize, .preferredTransform, .formatDescriptions)
        let duration = try await asset.load(.duration)
        // Stored frame → the frame as shown, corner at the origin; turned;
        // then the area's corner to the origin.
        let shown = CGRect(origin: .zero, size: natural).applying(transform)
        var t = transform.concatenating(CGAffineTransform(translationX: -shown.minX, y: -shown.minY))
        t = t.concatenating(TrackHeaders.quarterTurns(turns, of: natural, under: t))
        guard let area = zoom.pixels(in: Picture.turned(shown.size, turns: turns)) else {
            throw NSError(domain: "bulk-cut", code: 7, userInfo: [NSLocalizedDescriptionKey: "the zoom covers the whole frame"])
        }
        t = t.concatenating(CGAffineTransform(translationX: -area.minX, y: -area.minY))

        let composition = try await AVMutableVideoComposition.videoComposition(withPropertiesOf: asset)
        composition.renderSize = area.size
        let layer = AVMutableVideoCompositionLayerInstruction(assetTrack: track)
        layer.setTransform(t, at: .zero)
        let instruction = AVMutableVideoCompositionInstruction()
        instruction.timeRange = CMTimeRange(start: .zero, duration: duration)
        instruction.layerInstructions = [layer]
        composition.instructions = [instruction]

        let preset = reencodePreset(fds.first.map { CMFormatDescriptionGetMediaSubType($0) })
        guard await AVAssetExportSession.compatibility(ofExportPreset: preset, with: asset, outputFileType: type),
              let s = AVAssetExportSession(asset: asset, presetName: preset) else {
            throw NSError(domain: "bulk-cut", code: 2, userInfo: [NSLocalizedDescriptionKey:
                "no \(preset.replacingOccurrences(of: "AVAssetExportPreset", with: "")) export to .\(src.pathExtension) for this file"])
        }
        s.videoComposition = composition
        if let r { s.timeRange = CMTimeRange(start: time(r.start), end: time(r.end)) }
        s.metadata = (try? await asset.load(.metadata)) ?? []
        let watch = Task {
            for await state in s.states(updateInterval: 0.5) {
                if case .exporting(let p) = state { await fraction(p.fractionCompleted) }
            }
        }
        defer { watch.cancel() }
        try await s.export(to: dst, as: type)

        let out = AVURLAsset(url: dst)
        let want = r?.length ?? duration.seconds
        let got = try await out.load(.duration).seconds
        guard abs(got - want) < 0.25 else {
            throw NSError(domain: "bulk-cut", code: 3, userInfo: [NSLocalizedDescriptionKey:
                String(format: "the zoomed piece came out %.2f s long, expected %.2f s", got, want)])
        }
        let size = try await out.loadTracks(withMediaType: .video).first?.load(.naturalSize)
        guard size == area.size else {
            throw NSError(domain: "bulk-cut", code: 3, userInfo: [NSLocalizedDescriptionKey:
                "the zoomed piece came out \(size.map { "\(Int($0.width))×\(Int($0.height))" } ?? "with no video"), expected \(Int(area.width))×\(Int(area.height))"])
        }
    }

    /// The highest-quality preset in the codec family of a `codec` FourCC.
    static func reencodePreset(_ codec: FourCharCode?) -> String {
        let name = codec.map { c in String(bytes: (0..<4).map { UInt8(c >> (24 - 8 * $0) & 255) }, encoding: .ascii) ?? "" } ?? ""
        switch name {
        case "hvc1", "hev1": return AVAssetExportPresetHEVCHighestQuality
        case "ap4h", "ap4x": return AVAssetExportPresetAppleProRes4444LPCM
        case "apcn", "apch", "apcs", "apco": return AVAssetExportPresetAppleProRes422LPCM
        default: return AVAssetExportPresetHighestQuality
        }
    }

    /// What a zoom re-encodes a `codec` clip (VideoInfo.codec) to, for the sheet.
    static func reencodeName(_ codec: String) -> String {
        switch codec {
        case "HEVC", "ProRes": codec
        default: "H.264"
        }
    }
}

/// Which volumes have a Trash. This Mac's own disks do; a network share is
/// asked once (an SMB share has none: Finder deletes there "immediately").
/// Only looked up, never created.
enum Volumes {
    private static let known = OSAllocatedUnfairLock(initialState: [URL: Bool]())

    private static func volume(_ url: URL) -> URL {
        (try? url.resourceValues(forKeys: [.volumeURLKey]).volume) ?? url.deletingLastPathComponent()
    }

    static func hasTrash(_ url: URL) -> Bool {
        let v = volume(url)
        if let k = known.withLock({ $0[v] }) { return k }
        let has = MediaCache.isLocal(v)
            || (try? FileManager.default.url(for: .trashDirectory, in: .userDomainMask, appropriateFor: v, create: false)) != nil
        known.withLock { $0[v] = has }
        return has
    }

    static func name(_ url: URL) -> String {
        (try? volume(url).resourceValues(forKeys: [.volumeNameKey]).volumeName) ?? volume(url).lastPathComponent
    }
}
