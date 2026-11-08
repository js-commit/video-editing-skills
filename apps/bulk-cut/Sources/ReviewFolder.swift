import SwiftUI

/// A review folder: a tool staged copies of (or links to) footage here with a
/// `bulkcut.json` in `"mode": "review"` (Manifest.swift) and proposed ranges:
/// teal sequence clips and purple picks. The user corrects them (drag the
/// edges, add their own, remove the wrong ones, type a better description)
/// and every change is written to `bulkcut-review.json` for the tool to read
/// back. Nothing in the folder is ever trashed or trimmed: Apply becomes the
/// manifest's `send` action (a command the tool named), or a plain Done.
struct ReviewFolder: Equatable {
    let title: String
    let send: Manifest.Send?
    /// The sequences whose clips are the teal ranges.
    let sequences: [Manifest.Sequence]
    let legend: Manifest.Legend
    /// What the tool wrote about each proposal, by file key: the description
    /// filed unless the user types their own (DescriptionBox); kind "library"
    /// is a clip the library already holds (an orange stretch), read-only.
    let descriptions: [String: [Description]]

    struct Description: Equatable {
        let start: Double
        let end: Double
        let kind: String
        /// "" for a library clip nobody has described yet.
        let text: String
        /// Who wrote it: "salvage picker".
        let by: String
        /// A library clip's name.
        var clip: String?
    }

    typealias Sequence = Manifest.Sequence
    typealias Beat = Manifest.Beat

    static func == (a: ReviewFolder, b: ReviewFolder) -> Bool {
        a.title == b.title && a.send == b.send && a.sequences == b.sequences && a.descriptions == b.descriptions
    }

    /// The review folder `manifest` describes, or nil when it is not one.
    init?(_ manifest: Manifest?, folder: URL) {
        guard let m = manifest, m.isReview else { return nil }
        title = m.title ?? folder.lastPathComponent
        send = m.send
        sequences = m.sequences
        legend = m.legend
        var d: [String: [Description]] = [:]
        for (file, e) in m.files {
            var list: [Description] = e.proposals.compactMap { p in
                guard let k = p.kind, let t = p.text else { return nil }
                return Description(start: p.start, end: p.end, kind: k, text: t, by: p.by ?? "agent")
            }
            list += e.library.map { Description(start: $0.start, end: $0.end, kind: "library", text: $0.text,
                                                by: $0.by, clip: $0.clip) }
            if !list.isEmpty { d[file] = list.sorted { $0.start < $1.start } }
        }
        descriptions = d
    }

    /// A file's descriptions, by its path under the folder or its name.
    private func list(_ file: String) -> [Description] {
        descriptions[file] ?? descriptions[(file as NSString).lastPathComponent] ?? []
    }

    /// The library clip of `file` under `t` (an orange stretch).
    func libraryClip(_ file: String, at t: Double) -> Description? {
        list(file).first { $0.kind == "library" && $0.start <= t && t < $0.end }
    }

    /// The tool's description for range `r` of `file`: a teal range's beats
    /// (two the user joined: both, in order); any other range, the pick it
    /// shares at least half of the shorter of the two with. nil for one of the
    /// user's own.
    func agentDescription(_ r: KeepRange, file: String) -> (text: String, by: String)? {
        let all = list(file)
        let overlap = { (d: Description) in min(r.end, d.end) - max(r.start, d.start) }
        if r.kind == "beat" {
            let beats = all.filter { $0.kind == "beat" && overlap($0) > 0 }
            guard let first = beats.first else { return nil }
            return (beats.map(\.text).joined(separator: " "), first.by)
        }
        let pick = all.filter { $0.kind == "pick" && overlap($0) >= 0.5 * min(r.length, $0.end - $0.start) }
            .max { overlap($0) < overlap($1) }
        return pick.map { ($0.text, $0.by) }
    }
}

/// The send, run as a child process with its output streamed line by line.
@MainActor
final class SendRun: ObservableObject {
    @Published private(set) var lines: [String] = []
    @Published private(set) var running = false
    @Published private(set) var exit: Int32?
    private var partial = ""

    func start(_ command: [String]) {
        guard !running, let exe = command.first else { return }
        lines = []
        exit = nil
        running = true
        let p = Process()
        p.executableURL = URL(fileURLWithPath: exe)
        p.arguments = Array(command.dropFirst())
        var env = ProcessInfo.processInfo.environment
        // An app opened from Finder gets a bare PATH; add the usual places
        // command-line tools (ffmpeg, python3) are installed.
        env["PATH"] = (env["PATH"] ?? "/usr/bin:/bin:/usr/sbin:/sbin") + ":/opt/homebrew/bin:/usr/local/bin"
        env["PYTHONUNBUFFERED"] = "1"
        p.environment = env
        let pipe = Pipe()
        p.standardOutput = pipe
        p.standardError = pipe
        let reader = pipe.fileHandleForReading
        reader.readabilityHandler = { [weak self] h in
            let data = h.availableData
            guard !data.isEmpty, let text = String(data: data, encoding: .utf8) else { return }
            Task { @MainActor in self?.append(text) }
        }
        p.terminationHandler = { [weak self] proc in
            let status = proc.terminationStatus
            Task { @MainActor in
                reader.readabilityHandler = nil
                if let rest = try? reader.readToEnd(), let text = String(data: rest, encoding: .utf8) { self?.append(text) }
                self?.finish(status)
            }
        }
        DebugLog.write("Send: \(command.joined(separator: " "))")
        do {
            try p.run()
        } catch {
            append("Couldn't start it: \(error.localizedDescription)\n")
            finish(-1)
        }
    }

    private func append(_ text: String) {
        partial += text
        var parts = partial.components(separatedBy: "\n")
        partial = parts.removeLast()
        lines += parts
    }

    private func finish(_ status: Int32) {
        if !partial.isEmpty { lines.append(partial); partial = "" }
        exit = status
        running = false
        DebugLog.write("Send finished, exit \(status)")
    }
}

/// A review folder's Apply sheet: what the review holds, sequence by
/// sequence, and exactly what the send will run, before anything runs.
struct SendSheet: View {
    @ObservedObject var model: AppModel
    @StateObject private var run = SendRun()
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        let s = model.sendSummary
        let seqs = model.sendSequences
        let total = s.beats + s.picks + s.mine
        let review = model.reviewFolder
        let legend = review?.legend ?? Manifest.Legend()
        VStack(alignment: .leading, spacing: 14) {
            Label(review?.send?.label ?? "Review done", systemImage: "tray.and.arrow.up.fill")
                .font(.title2.bold())
            if let t = review?.title { Text(t).foregroundStyle(.secondary) }

            VStack(alignment: .leading, spacing: 8) {
                Text("What the review keeps").font(.headline)
                Grid(alignment: .leading, horizontalSpacing: 10, verticalSpacing: 6) {
                    ForEach(Array(seqs.enumerated()), id: \.offset) { _, q in
                        row(KeepRange(start: 0, end: 1, kind: "beat").tint, q.title,
                            "\(q.clips) clip\(q.clips == 1 ? "" : "s"), \(String(format: "%.1f", q.seconds)) s"
                            + (q.removed > 0 ? " (\(q.removed) you removed left out)" : ""))
                    }
                    row(KeepRange(start: 0, end: 1, kind: "pick").tint, "\(s.picks) \(legend.pick)",
                        "with the tool's description, or yours where you typed one")
                    row(KeepRange(start: 0, end: 1).tint, "\(s.mine) \(legend.mine)",
                        "with your description if you typed one")
                    row(.gray.opacity(0.5), "\(s.nothing) file\(s.nothing == 1 ? "" : "s") with nothing kept", "left out")
                }
            }

            VStack(alignment: .leading, spacing: 4) {
                Text("What happens").font(.headline)
                let steps = review?.send?.steps ?? []
                if steps.isEmpty {
                    step(1, "Your review is saved in \(Manifest.reviewFileName) in this folder (it is after every change).")
                    if review?.send == nil {
                        step(2, "Nothing runs from here: go back to Claude (or the tool that made this folder) and say you are done.")
                    } else {
                        step(2, "Then the command below runs.")
                    }
                } else {
                    ForEach(Array(steps.enumerated()), id: \.offset) { i, t in step(i + 1, t) }
                }
                step((steps.isEmpty ? 2 : steps.count) + 1, "Nothing in this folder is deleted or trimmed.")
            }
            .font(.callout)

            if let cmd = review?.send?.command {
                Text(cmd.map { $0.contains(" ") ? "\"\($0)\"" : $0 }.joined(separator: " "))
                    .font(.system(size: 11, design: .monospaced)).foregroundStyle(.secondary)
                    .textSelection(.enabled).lineLimit(3).truncationMode(.middle)
                    .help("The command Send runs (from \(Manifest.fileName))")
            }

            if !run.lines.isEmpty {
                ScrollViewReader { proxy in
                    ScrollView {
                        VStack(alignment: .leading, spacing: 1) {
                            ForEach(Array(run.lines.enumerated()), id: \.offset) { i, line in
                                Text(line).font(.system(size: 11, design: .monospaced)).textSelection(.enabled).id(i)
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .frame(height: 200)
                    .padding(6)
                    .background(Color.black.opacity(0.25), in: RoundedRectangle(cornerRadius: 6))
                    .onChange(of: run.lines.count) { _, n in proxy.scrollTo(n - 1, anchor: .bottom) }
                }
            }
            if let code = run.exit {
                Label(code == 0 ? "Done." : "It stopped (exit \(code)). Nothing was deleted; the log above says where.",
                      systemImage: code == 0 ? "checkmark.circle.fill" : "xmark.octagon.fill")
                    .foregroundStyle(code == 0 ? .green : .red)
            }
            HStack {
                Text(String(format: "%.0f s kept in all", s.seconds)).font(.callout).foregroundStyle(.secondary)
                Spacer()
                Button(run.exit == nil ? "Cancel" : "Close") { dismiss() }
                    .keyboardShortcut(.cancelAction)
                    .disabled(run.running)
                if run.exit == nil {
                    if let send = review?.send {
                        Button {
                            model.saveNow()
                            run.start(send.command)
                        } label: {
                            if run.running {
                                Label { Text("Running…") } icon: { ProgressView().controlSize(.small) }
                            } else {
                                Text("\(send.label) (\(total) clip\(total == 1 ? "" : "s"))")
                            }
                        }
                        .keyboardShortcut(.defaultAction)
                        .disabled(run.running)
                    } else {
                        Button("Done") {
                            model.saveNow()
                            model.flash("Review saved: tell Claude you are done")
                            dismiss()
                        }
                        .keyboardShortcut(.defaultAction)
                    }
                }
            }
        }
        .padding(22)
        .frame(width: 660)
        .interactiveDismissDisabled(run.running)
    }

    private func row(_ color: Color, _ what: String, _ note: String) -> some View {
        GridRow {
            RoundedRectangle(cornerRadius: 3).fill(color).frame(width: 18, height: 10)
            Text(what).font(.system(size: 13, weight: .semibold))
            Text(note).font(.system(size: 12)).foregroundStyle(.secondary)
        }
    }

    private func step(_ n: Int, _ text: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 6) {
            Text("\(n).").foregroundStyle(.secondary)
            Text(text).fixedSize(horizontal: false, vertical: true)
        }
    }
}

/// What the colours mean, above the timeline of a review folder; with a
/// focus, what is lit.
struct ReviewLegend: View {
    let legend: Manifest.Legend
    /// The focus's title; nil for everything.
    var focus: String?
    /// The focus key.
    var key = "F"
    var sendLabel: String?

    var body: some View {
        HStack(spacing: 14) {
            swatch(.orange.opacity(0.6), legend.library)
            swatch(KeepRange(start: 0, end: 1, kind: "beat").tint, legend.beat)
            swatch(KeepRange(start: 0, end: 1, kind: "pick").tint, legend.pick)
            swatch(KeepRange(start: 0, end: 1).tint, legend.mine)
            swatch(.black.opacity(0.3), "grey: not kept")
            Spacer()
            if let focus {
                Text("Focus: \(focus). The rest is dimmed and skipped (\(key)).")
                    .foregroundStyle(.secondary).lineLimit(1).truncationMode(.middle)
            } else {
                Text("Drag an edge to change a range. \(sendLabel ?? "Done") (top right) when finished.")
                    .foregroundStyle(.secondary)
            }
        }
        .font(.system(size: 11))
    }

    private func swatch(_ color: Color, _ text: String) -> some View {
        HStack(spacing: 5) {
            RoundedRectangle(cornerRadius: 2).fill(color).frame(width: 14, height: 8)
            Text(text)
        }
    }
}
