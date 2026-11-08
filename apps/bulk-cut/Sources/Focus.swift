import SwiftUI

/// What a review folder's list shows and sections-only plays: every coloured
/// range, one sequence end to end in beat order across its takes (to review
/// it the way it will play), or just the picks.
enum Focus: Hashable {
    case everything
    /// Manifest.Sequence.name.
    case sequence(String)
    case picks
}

/// One stretch focused playback plays: a file (Clip.key) and its range.
struct FocusStep: Equatable {
    let key: String
    var range: ClosedRange<Double>
}

/// A file as the focus reads it: its key, its name (what the manifest's
/// sequences call it) and its ranges (none when it keeps nothing).
struct FocusFile {
    let key: String
    let name: String
    let ranges: [KeepRange]
}

extension ReviewFolder {
    /// What F steps through and the menu lists, in that order.
    var focuses: [Focus] { [.everything] + sequences.map { .sequence($0.name) } + [.picks] }

    func title(_ f: Focus) -> String {
        switch f {
        case .everything: "Everything"
        case .picks: "Picks only"
        case .sequence(let n): sequences.first { $0.name == n }?.title ?? n
        }
    }

    private func sequence(_ f: Focus) -> Sequence? {
        guard case .sequence(let n) = f else { return nil }
        return sequences.first { $0.name == n }
    }

    /// The sequence a teal range belongs to: the one its proposal named, or
    /// else the sequence whose beat in that file it overlaps most.
    func sequence(of r: KeepRange, file: String) -> String? {
        guard r.kind == "beat" else { return nil }
        if let s = r.sequence { return s }
        var best: (name: String, overlap: Double)?
        for q in sequences {
            for b in q.beats where b.file == file {
                let o = min(r.end, b.end) - max(r.start, b.start)
                if o > 0, o > best?.overlap ?? 0 { best = (q.name, o) }
            }
        }
        return best?.name
    }

    /// Does range `r` of `file` belong to the focus?
    func contains(_ f: Focus, _ r: KeepRange, file: String) -> Bool {
        switch f {
        case .everything: true
        case .picks: r.kind == "pick"
        case .sequence(let n): sequence(of: r, file: file) == n
        }
    }

    /// Where a range of `file` plays in `seq`: at the first of its beats in
    /// that file it overlaps (two beats the user joined play as one clip,
    /// where the first did), else at the nearest.
    private static func position(_ r: KeepRange, file: String, in seq: Sequence) -> Int {
        let mine = seq.beats.indices.filter { seq.beats[$0].file == file }
        let overlap = { (b: Beat) in min(r.end, b.end) - max(r.start, b.start) }
        if let i = mine.first(where: { overlap(seq.beats[$0]) > 0 }) { return i }
        return mine.max { overlap(seq.beats[$0]) < overlap(seq.beats[$1]) } ?? seq.beats.count     // minus the gap
    }

    /// What focused sections-only playback plays, in order: a sequence's
    /// ranges in beat order, file after file, or every pick in list order.
    /// Stretches of one file that play back to back are one step.
    func plan(_ f: Focus, files: [FocusFile]) -> [FocusStep] {
        if f == .everything { return [] }
        let seq = sequence(f)
        if case .sequence = f, seq == nil { return [] }
        var steps: [(beat: Int, file: Int, step: FocusStep)] = []
        for (k, file) in files.enumerated() {
            for r in RangeOps.tidy(file.ranges) where r.open == nil && contains(f, r, file: file.name) {
                steps.append((seq.map { Self.position(r, file: file.name, in: $0) } ?? 0, k,
                              FocusStep(key: file.key, range: r.start...r.end)))
            }
        }
        steps.sort { ($0.beat, $0.file, $0.step.range.lowerBound) < ($1.beat, $1.file, $1.step.range.lowerBound) }
        var out: [FocusStep] = []
        for s in steps.map(\.step) {
            if let last = out.last, last.key == s.key, s.range.lowerBound >= last.range.upperBound - RangeOps.eps,
               s.range.lowerBound - last.range.upperBound < 0.1 {
                out[out.count - 1].range = last.range.lowerBound...s.range.upperBound
            } else {
                out.append(s)
            }
        }
        return out
    }

    /// The focus's files, in the order it plays them (Clip.keys): a
    /// sequence's by its first beat in each (one whose beats the user removed
    /// stays, so they can put one back), then any other holding its ranges;
    /// the files with picks, in list order.
    func files(_ f: Focus, _ files: [FocusFile]) -> [String] {
        switch f {
        case .everything:
            return files.map(\.key)
        case .picks:
            return files.filter { $0.ranges.contains { $0.kind == "pick" } }.map(\.key)
        case .sequence:
            guard let seq = sequence(f) else { return [] }
            var out: [String] = []
            for b in seq.beats {
                if let file = files.first(where: { $0.name == b.file }), !out.contains(file.key) { out.append(file.key) }
            }
            for s in plan(f, files: files) where !out.contains(s.key) { out.append(s.key) }
            return out
        }
    }

    /// What a row in the focused list says: "beats 1–2, 4 · 1 removed",
    /// "3 picks". The beats are the sequence's in that file still under one
    /// of its ranges (what the review keeps).
    func note(_ f: Focus, _ file: FocusFile) -> String? {
        switch f {
        case .everything:
            return nil
        case .picks:
            let n = RangeOps.tidy(file.ranges).count { $0.kind == "pick" }
            return n == 0 ? "no picks left" : "\(n) pick\(n == 1 ? "" : "s")"
        case .sequence:
            guard let seq = sequence(f) else { return nil }
            let mine = RangeOps.tidy(file.ranges).filter { contains(f, $0, file: file.name) }
            var kept: [Int] = [], removed = 0
            for (i, b) in seq.beats.enumerated() where b.file == file.name {
                if mine.contains(where: { min($0.end, b.end) - max($0.start, b.start) > 0 }) { kept.append(i + 1) } else { removed += 1 }
            }
            let what = kept.isEmpty ? (mine.isEmpty ? "no beats left" : "\(mine.count) clip\(mine.count == 1 ? "" : "s"), moved off its beats")
                                    : "beat\(kept.count == 1 ? "" : "s") " + Self.runs(kept)
            return what + (removed > 0 && !kept.isEmpty ? " · \(removed) removed" : "")
        }
    }

    /// [1, 2, 3, 7] → "1–3, 7".
    static func runs(_ n: [Int]) -> String {
        var parts: [String] = []
        var i = 0
        while i < n.count {
            var j = i
            while j + 1 < n.count, n[j + 1] == n[j] + 1 { j += 1 }
            parts.append(j > i ? "\(n[i])–\(n[j])" : "\(n[i])")
            i = j + 1
        }
        return parts.joined(separator: ", ")
    }
}

/// The focus chip beside Sections only and Loop in a review folder: a menu
/// of Everything, each sequence and Picks only (F / ⇧F step through them).
struct FocusMenu: View {
    @ObservedObject var model: AppModel

    var body: some View {
        if let s = model.reviewFolder {
            let color: Color = switch model.focus {
            case .everything: .gray
            case .sequence: KeepRange(start: 0, end: 1, kind: "beat").tint
            case .picks: KeepRange(start: 0, end: 1, kind: "pick").tint
            }
            Menu {
                item(s, .everything)
                Divider()
                ForEach(s.sequences, id: \.name) { q in item(s, .sequence(q.name)) }
                if !s.sequences.isEmpty { Divider() }
                item(s, .picks)
            } label: {
                Text(model.focus == .everything ? "Everything" : s.title(model.focus))
            }
            .menuStyle(.borderlessButton)
            .controlSize(.small)
            .fixedSize()
            .padding(.horizontal, 7).padding(.vertical, 1)
            .background(color.opacity(0.22), in: Capsule())
            .help("Review one sequence at a time: the list shows only its files, in the order it plays, and sections "
                  + "only plays only its clips, in beat order, file after file. The other ranges stay, dimmed, and "
                  + "can still be edited. Picks only does the same for the purple ranges. "
                  + "(\(model.keymap.label(.focusNext)) / \(model.keymap.label(.focusPrev)))")
        }
    }

    private func item(_ s: ReviewFolder, _ f: Focus) -> some View {
        Toggle(menuTitle(s, f), isOn: Binding(get: { model.focus == f }, set: { if $0 { model.setFocus(f) } }))
    }

    private func menuTitle(_ s: ReviewFolder, _ f: Focus) -> String {
        guard case .sequence(let n) = f, let q = s.sequences.first(where: { $0.name == n }) else {
            return f == .everything ? "Everything (every coloured range)" : "Picks only"
        }
        let files = Set(q.beats.map(\.file)).count
        return "\(q.title)  (\(q.beats.count) beats, \(files) file\(files == 1 ? "" : "s"))"
    }
}
