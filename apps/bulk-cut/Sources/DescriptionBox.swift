import SwiftUI

/// A review folder's description box, under the clip's name and facts: the
/// description of the range under the playhead, and who wrote it. A proposed
/// range's text is the tool's (bulkcut.json); the user's own ranges have none
/// until they type one; an orange stretch, a clip the library already holds,
/// shows the library's description, read-only. Typing replaces a range's
/// description, so the user can add context and see how well each clip is
/// described. Clicking in pauses playback; Return saves (one undo step), Esc
/// drops the change; the tool's text stays under the user's, to compare, with
/// a button to put it back.
struct DescriptionBox: View {
    @ObservedObject var model: AppModel
    @ObservedObject var player: PlayerModel
    let clip: Clip
    let review: ReviewFolder

    var body: some View {
        let ranges = RangeOps.settle(model.edit(clip).ranges)
        let i = Self.current(ranges, at: player.currentSeconds)
        VStack(alignment: .leading, spacing: 5) {
            if let i {
                let r = ranges[i]
                let agent = review.agentDescription(r, file: clip.key)
                HStack(spacing: 8) {
                    Text("\(i + 1)")
                        .font(.system(size: 11, weight: .bold, design: .rounded)).foregroundStyle(.black)
                        .frame(width: 16, height: 15)
                        .background(r.tint, in: RoundedRectangle(cornerRadius: 3))
                    Text(kindTitle(r)).font(.system(size: 12, weight: .semibold))
                    Text("\(Format.clock(r.start))–\(Format.clock(r.end)) · \(String(format: "%.1f", r.length)) s")
                        .font(.system(size: 11, design: .monospaced)).foregroundStyle(.secondary)
                    Spacer()
                    if r.note != nil {
                        noteBadge("you", color: .orange).help("You typed this description. The review keeps it as yours.")
                    } else if let agent {
                        noteBadge(agent.by, color: .purple).help("Written by the \(agent.by). Click the text to edit it.")
                    } else {
                        noteBadge("no description yet", color: .gray)
                            .help("Type one to keep yours with the range; otherwise the tool may describe it later.")
                    }
                }
                // A fresh editor per range and per saved text: switching range
                // (or ⌘Z) shows that range's text, and a half-typed edit is
                // saved to the range it was typed against.
                NoteEditor(text: r.note ?? agent?.text ?? "", agent: agent?.text,
                           placeholder: "No description yet. Type one here (optional).",
                           onBegin: { player.pause() },
                           onCommit: { model.setNote($0, clip: clip, span: r.start...r.end) })
                    .id("\(clip.key)|\(i)|\(r.start)|\(r.note ?? "")")
                if r.note != nil, let a = agent?.text {
                    HStack(alignment: .firstTextBaseline, spacing: 6) {
                        Text("\(agent?.by ?? "agent") wrote:").font(.system(size: 11, weight: .semibold)).foregroundStyle(.secondary)
                            .fixedSize()
                        Text(a).font(.system(size: 11)).foregroundStyle(.secondary).textSelection(.enabled)
                            .lineLimit(2).truncationMode(.tail)
                            .help(a)
                        Spacer(minLength: 4)
                        Button("Put it back") { model.setNote(nil, clip: clip, span: r.start...r.end) }
                            .buttonStyle(.borderless).controlSize(.small)
                            .help("Drop your text: the range keeps the tool's description again (⌘Z undoes)")
                    }
                }
            } else if let lib = review.libraryClip(clip.key, at: player.currentSeconds) {
                // An orange stretch: already a library clip.
                HStack(spacing: 8) {
                    Text(review.legend.library.capitalizedFirst).font(.system(size: 12, weight: .semibold)).foregroundStyle(.orange)
                    Text("\(Format.clock(lib.start))–\(Format.clock(lib.end)) · \(String(format: "%.1f", lib.end - lib.start)) s")
                        .font(.system(size: 11, design: .monospaced)).foregroundStyle(.secondary)
                    if let c = lib.clip {
                        Text(c).font(.system(size: 11)).foregroundStyle(.secondary).lineLimit(1).truncationMode(.middle)
                            .textSelection(.enabled)
                    }
                    Spacer()
                    noteBadge(lib.text.isEmpty ? "no description yet" : lib.by, color: lib.text.isEmpty ? .gray : .orange)
                        .help("Already in the library: a clip was cut from this stretch before. Its description "
                              + "is the library's; the review doesn't touch it.")
                }
                Text(lib.text.isEmpty ? "No description yet." : lib.text)
                    .font(.system(size: 13))
                    .foregroundStyle(lib.text.isEmpty ? Color.secondary : Color.primary.opacity(0.85))
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, minHeight: 34, alignment: .topLeading)
                    .padding(.horizontal, 8).padding(.vertical, 6)
                    .background(Color.orange.opacity(0.06), in: RoundedRectangle(cornerRadius: 6))
            } else {
                HStack(spacing: 8) {
                    Text(ranges.isEmpty ? "Nothing kept in this file: nothing to describe."
                                        : "Grey here: not kept. Play into a coloured range to see its description.")
                        .font(.system(size: 12)).foregroundStyle(.secondary)
                    Spacer()
                    if !ranges.isEmpty {
                        let typed = ranges.count { $0.note != nil }
                        Text("\(ranges.count) range\(ranges.count == 1 ? "" : "s")"
                             + (typed > 0 ? ", \(typed) described by you" : ""))
                            .font(.system(size: 11)).foregroundStyle(.secondary)
                    }
                }
                .frame(minHeight: 20)
            }
        }
        .padding(.horizontal, 12).padding(.vertical, 7)
    }

    /// "Proposed", "Sequence clip · beat 5", "Your range".
    private func kindTitle(_ r: KeepRange) -> String {
        switch r.kind {
        case "pick": return review.legend.pick.capitalizedFirst
        case "beat":
            let beat = r.label?.split(separator: ":").first.map(String.init)
            return "Sequence clip" + (beat.map { " · \($0)" } ?? "")
        default: return "Your range"
        }
    }

    /// The settled range under the playhead; one that just ended (focused
    /// playback stops on its last frame) counts too.
    static func current(_ ranges: [KeepRange], at t: Double) -> Int? {
        if let i = ranges.firstIndex(where: { RangeOps.contains($0, t) }) { return i }
        return ranges.lastIndex { $0.start <= t && t <= $0.end + 0.1 }
    }
}

/// The text field: saves on Return or when it loses focus (clicking away,
/// another range), reverts on Esc. Return leaves the field so the keys work
/// again; ⌥Return is a new line.
private struct NoteEditor: View {
    let text: String
    let agent: String?
    let placeholder: String
    let onBegin: () -> Void
    let onCommit: (String?) -> Void
    @State private var draft = ""
    @State private var loaded = false
    /// What the last commit saved: Return commits, and the editor it
    /// replaces commits again on its way out.
    @State private var saved: String?
    @FocusState private var focused: Bool

    var body: some View {
        TextField(placeholder, text: $draft, axis: .vertical)
            .textFieldStyle(.plain)
            .font(.system(size: 13))
            .lineLimit(2...6)
            .frame(minHeight: 34, alignment: .topLeading)
            .focused($focused)
            .padding(.horizontal, 8).padding(.vertical, 6)
            .background(Color.primary.opacity(focused ? 0.08 : 0.04), in: RoundedRectangle(cornerRadius: 6))
            .overlay(RoundedRectangle(cornerRadius: 6).stroke(focused ? Color.accentColor : .clear, lineWidth: 1))
            .help("Click to edit: Return saves it as yours, Esc cancels, ⌥Return adds a line.")
            .onAppear { if !loaded { draft = text; loaded = true } }
            .onSubmit { focused = false }
            .onExitCommand { draft = text; focused = false }
            .onChange(of: focused) { _, now in
                if now { onBegin() } else { commit() }
            }
            .onDisappear { commit() }
    }

    /// The user's text as the range's note; the agent's own text (or nothing) puts
    /// the agent's back. Nothing when it did not change.
    private func commit() {
        let t = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard loaded, t != (saved ?? text.trimmingCharacters(in: .whitespacesAndNewlines)) else { return }
        saved = t
        onCommit(t.isEmpty || t == agent?.trimmingCharacters(in: .whitespacesAndNewlines) ? nil : t)
    }
}
