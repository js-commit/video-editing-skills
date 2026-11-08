import SwiftUI

/// ⌘⏎: everything staged, listed before anything happens, then done in one go.
struct ApplySheet: View {
    @ObservedObject var model: AppModel
    /// Sticky: the last choice is the default next time.
    @AppStorage("overwriteOriginals") private var overwrite = false
    @State private var stage: Stage = .review
    @State private var progressText = ""
    @State private var progress = 0.0
    /// How far the step under way has got (a re-encode reports it), and how many steps there are.
    @State private var stepFraction = 0.0
    @State private var steps = 1
    @State private var result: ApplyResult?
    @Environment(\.dismiss) private var dismiss

    private enum Stage { case review, running, done }

    /// After a ⌘S Apply with problems, it opens on them.
    init(model: AppModel) {
        self.model = model
        if let r = model.saveResult {
            _stage = State(initialValue: .done)
            _result = State(initialValue: r)
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            switch stage {
            case .review: review(model.plan(overwrite: overwrite))
            case .running: running
            case .done: done
            }
        }
        .padding(20)
        .frame(width: 700)
        .frame(minHeight: 240, maxHeight: 760)
        .interactiveDismissDisabled(stage == .running)
        .onDisappear { model.saveResult = nil }
    }

    // MARK: review

    @ViewBuilder
    private func review(_ plan: ApplyPlan) -> some View {
        Text("Apply staged changes").font(.title2.weight(.semibold))
        if plan.isEmpty {
            Text("Nothing to do: the crops left cover their whole clips.").foregroundStyle(.secondary)
        }
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                let toTrash = plan.trash.filter { !plan.noTrash.contains($0.url) }
                let toDelete = plan.permanentDeletes
                if !toTrash.isEmpty {
                    section("Move to the Trash — \(toTrash.count) files, \(Format.bytes(toTrash.reduce(0) { $0 + $1.size }))",
                            icon: "trash", color: .red) {
                        ForEach(toTrash) { c in fileRow(c) }
                    }
                }
                if !toDelete.isEmpty {
                    section("Delete permanently — \(toDelete.count) files, \(Format.bytes(toDelete.reduce(0) { $0 + $1.size })); "
                            + "\(plan.noTrashVolumes.joined(separator: ", ")) has no Trash",
                            icon: "trash.slash", color: .red) {
                        ForEach(toDelete) { c in fileRow(c) }
                    }
                }
                if !plan.crops.isEmpty {
                    section("\(cropTitle(plan)) — \(plan.crops.count) clips into \(plan.outputCount) files",
                            icon: "scissors", color: .orange) {
                        ForEach(plan.crops) { job in cropRow(job) }
                    }
                }
                if !plan.photos.isEmpty {
                    section("\(photoTitle(plan)) — \(plan.photos.count) photo\(plan.photos.count == 1 ? "" : "s")",
                            icon: "photo", color: .orange) {
                        ForEach(plan.photos) { job in photoRow(job) }
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        Divider()
        Toggle("Overwrite originals", isOn: $overwrite)
        if plan.permanentReplaces > 0 {
            Label("\(plan.permanentReplaces) original\(plan.permanentReplaces == 1 ? " is" : "s are") on \(plan.noTrashVolumes.joined(separator: ", ")), "
                  + "which has no Trash: replaced outright, not kept in the Trash.", systemImage: "exclamationmark.triangle.fill")
                .font(.system(size: 12)).foregroundStyle(.orange)
        }
        Text(overwrite
             ? "A cropped or rotated original goes to the Trash. One piece takes its name; several become name_1, name_2, …"
             : "Crops are saved next to the original as name_cropped (name_cropped_1, _2, … for several pieces), rotations as name_rotated. The original stays.")
            .font(.system(size: 12)).foregroundStyle(.secondary)
        Text((plan.crops.isEmpty ? "" : "Crops and rotations copy the video as is, without re-encoding: same codec, bitrate and quality. ")
             + (plan.crops.contains { $0.zoom != nil }
                ? "A zoom has to re-encode the video: the highest quality in the clip's own codec (HEVC stays HEVC, HDR stays HDR). "
                : "")
             + (plan.photos.isEmpty ? "" : "Rotating a JPEG, HEIC or TIFF only changes its orientation tag; a crop (or rotating "
                + "another format) redraws the photo: PNG losslessly, JPEG and HEIC at 95% quality, keeping its metadata. ")
             + "Trashed files can be put back from the Trash. ⌘S applies with these settings, without this sheet.")
            .font(.system(size: 12)).foregroundStyle(.secondary)
        HStack {
            Spacer()
            Button("Cancel") { DebugLog.write("Apply cancelled"); dismiss() }.keyboardShortcut(.cancelAction)
            Button("Apply") { run(plan) }
                .keyboardShortcut(.defaultAction)
                .disabled(plan.isEmpty)
        }
    }

    private func fileRow(_ c: Clip) -> some View {
        HStack {
            Text(c.key)
            Spacer()
            Text(Format.bytes(c.size)).foregroundStyle(.secondary)
        }
        .font(.system(size: 12))
    }

    private func cropRow(_ job: CropJob) -> some View {
        let fps = model.infos[job.clip.url]?.fps ?? 30
        let tc = { (t: Double) in Timecode.string(seconds: t, fps: fps) }
        return VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 8) {
                Text(job.clip.key).font(.system(size: 12, weight: .semibold))
                if let p = pictureNote(job) { Text(p).font(.system(size: 11)).foregroundStyle(.orange) }
            }
            ForEach(Array(job.ranges.enumerated()), id: \.offset) { i, r in
                HStack(spacing: 6) {
                    // The out point is shown as the last kept frame, as a timeline would.
                    Text("\(tc(r.start)) – \(tc(max(r.start, r.end - 0.5 / fps)))")
                        .font(.system(size: 11, design: .monospaced))
                    Text("(\(Format.duration(r.length)))").font(.system(size: 11)).foregroundStyle(.secondary)
                    Image(systemName: "arrow.right").font(.system(size: 9)).foregroundStyle(.secondary)
                    Text(job.outputs[i].lastPathComponent + (job.outputs[i] == job.clip.url ? "  (replaces it)" : ""))
                        .font(.system(size: 11))
                }
            }
        }
    }

    private func photoRow(_ job: PhotoJob) -> some View {
        var parts: [String] = []
        if job.turns != 0 { parts.append("rotated \(AppModel.turnLabel(job.turns))") }
        if let s = job.cropSize { parts.append("cropped to \(Int(s.width))×\(Int(s.height))") }
        parts.append(job.lossless ? "orientation tag only" : "re-encoded as \(job.format)")
        return HStack(spacing: 6) {
            Text(job.clip.key).font(.system(size: 12, weight: .semibold))
            Text(parts.joined(separator: " · ")).font(.system(size: 11)).foregroundStyle(.orange)
            Image(systemName: "arrow.right").font(.system(size: 9)).foregroundStyle(.secondary)
            Text(job.output.lastPathComponent + (job.output == job.clip.url ? "  (replaces it)" : ""))
                .font(.system(size: 11))
        }
    }

    private func photoTitle(_ plan: ApplyPlan) -> String {
        var kinds: [String] = []
        if plan.photos.contains(where: { $0.turns != 0 }) { kinds.append("Rotate") }
        if plan.photos.contains(where: { $0.crop != nil }) { kinds.append("Crop") }
        return kinds.joined(separator: " / ")
    }

    /// "Crop", "Crop / Rotate / Zoom": what the section does.
    private func cropTitle(_ plan: ApplyPlan) -> String {
        var kinds: [String] = []
        if plan.crops.contains(where: { !$0.whole }) { kinds.append("Crop") }
        if plan.crops.contains(where: { $0.turns != 0 }) { kinds.append("Rotate") }
        if plan.crops.contains(where: { $0.zoom != nil }) { kinds.append("Zoom") }
        return kinds.joined(separator: " / ")
    }

    /// "turned 90° right · zoomed to 1920×1080, re-encoded as HEVC".
    private func pictureNote(_ job: CropJob) -> String? {
        var parts: [String] = []
        if job.turns != 0 { parts.append("turned \(AppModel.turnLabel(job.turns))") }
        if let s = job.zoomSize {
            parts.append("zoomed to \(Int(s.width))×\(Int(s.height)), re-encoded as \(Exporter.reencodeName(job.codec))")
        }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    private func section<C: View>(_ title: String, icon: String, color: Color,
                                  @ViewBuilder content: () -> C) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Label(title, systemImage: icon).font(.system(size: 13, weight: .semibold)).foregroundStyle(color)
            VStack(alignment: .leading, spacing: 6) { content() }.padding(.leading, 22)
        }
    }

    // MARK: running / done

    private var running: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Applying…").font(.title2.weight(.semibold))
            ProgressView(value: min(1, progress + stepFraction / Double(max(steps, 1))))
            Text(progressText).font(.system(size: 12)).foregroundStyle(.secondary).lineLimit(1).truncationMode(.middle)
        }
    }

    @ViewBuilder
    private var done: some View {
        let r = result ?? ApplyResult()
        Text(r.failures.isEmpty ? "Done" : "Done, with problems").font(.title2.weight(.semibold))
        Text("\(r.trashed.count) moved to the Trash" + (r.deleted.isEmpty ? "" : " · \(r.deleted.count) deleted")
             + " · \(r.written.count) files written")
            .foregroundStyle(.secondary)
        if !r.failures.isEmpty {
            ScrollView {
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(Array(r.failures.enumerated()), id: \.offset) { _, f in
                        Text("\(f.name): \(f.why)").font(.system(size: 12)).foregroundStyle(.red)
                            .textSelection(.enabled)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(maxHeight: 260)
            Text("Their edits are still staged.").font(.system(size: 12)).foregroundStyle(.secondary)
        }
        HStack {
            Spacer()
            Button("Close") { dismiss() }.keyboardShortcut(.defaultAction)
        }
    }

    private func run(_ plan: ApplyPlan) {
        stage = .running
        Task {
            let r = await model.apply(plan, progress: { text, i, n in
                progressText = text
                progress = n > 0 ? Double(i) / Double(n) : 1
                steps = n
                stepFraction = 0
            }, fraction: { f in stepFraction = f })
            result = r
            stage = .done
            model.flash("Applied: \(r.trashed.count) trashed" + (r.deleted.isEmpty ? "" : ", \(r.deleted.count) deleted")
                        + ", \(r.written.count) files written"
                        + (r.failures.isEmpty ? "" : ", \(r.failures.count) problems"))
        }
    }
}
