import AppKit
import SwiftUI

/// Read-only NSTextView showing the transcript: the current word is
/// highlighted and kept in view while playing; a click on a word (or a
/// paragraph's timecode) seeks there. Find hits (⌘F) are painted under it.
struct TranscriptView: NSViewRepresentable {
    let transcript: Transcript?
    let currentIndex: Int?
    let fontSize: CGFloat
    var foundRanges: [NSRange] = []
    var currentFound: Int?
    let onSeek: (Double) -> Void

    static let spoken = NSColor.systemYellow.withAlphaComponent(0.55)
    static let hit = NSColor.systemOrange.withAlphaComponent(0.3)
    static let currentHit = NSColor.systemOrange.withAlphaComponent(0.75)

    final class Coordinator: NSObject, NSTextViewDelegate {
        var parent: TranscriptView
        weak var textView: NSTextView?
        var shownTranscript: Transcript?
        var shownSize: CGFloat = 0
        var highlighted: NSRange?
        var paintedHits: [NSRange] = []
        var paintedCurrent: Int?
        var scrolledHit: NSRange?

        init(_ parent: TranscriptView) { self.parent = parent }

        func textView(_ textView: NSTextView, clickedOnLink link: Any, at charIndex: Int) -> Bool {
            guard let url = link as? URL, let s = parent.transcript?.seconds(for: url) else { return false }
            parent.onSeek(s)
            return true
        }

        /// Do not fight the reader: no autoscroll while the pointer is over the text.
        var mouseInside: Bool {
            guard let tv = textView, let sv = tv.enclosingScrollView, let win = tv.window else { return false }
            let p = sv.convert(win.mouseLocationOutsideOfEventStream, from: nil)
            return sv.bounds.contains(p)
        }
    }

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeNSView(context: Context) -> NSScrollView {
        let sv = NSTextView.scrollableTextView()
        let tv = sv.documentView as! NSTextView
        tv.isEditable = false
        tv.isSelectable = true
        tv.drawsBackground = false
        tv.textContainerInset = NSSize(width: 10, height: 10)
        tv.linkTextAttributes = [:]          // words are links, but look like words
        tv.delegate = context.coordinator
        tv.isAutomaticLinkDetectionEnabled = false
        sv.drawsBackground = false
        sv.hasVerticalScroller = true
        context.coordinator.textView = tv
        return sv
    }

    func updateNSView(_ sv: NSScrollView, context: Context) {
        let co = context.coordinator
        co.parent = self
        guard let tv = sv.documentView as? NSTextView, let storage = tv.textStorage else { return }

        if co.shownTranscript !== transcript || co.shownSize != fontSize {
            co.shownTranscript = transcript
            co.shownSize = fontSize
            co.highlighted = nil
            co.paintedHits = []
            co.paintedCurrent = nil
            co.scrolledHit = nil
            storage.setAttributedString(transcript?.attributed(size: fontSize) ?? NSAttributedString())
        }
        guard let t = transcript else { return }
        let range = currentIndex.map { t.words[$0].range }
        let hitsChanged = foundRanges != co.paintedHits || currentFound != co.paintedCurrent
        guard hitsChanged || range != co.highlighted else { return }
        let len = storage.length
        func hitColor(_ i: Int) -> NSColor { i == currentFound ? Self.currentHit : Self.hit }
        storage.beginEditing()
        if let old = co.highlighted {
            storage.removeAttribute(.backgroundColor, range: old)
            storage.addAttribute(.foregroundColor, value: NSColor.labelColor, range: old)
            if !hitsChanged {
                // The word that stopped being spoken may sit inside a find hit.
                for (i, r) in foundRanges.enumerated() where NSIntersectionRange(r, old).length > 0 {
                    storage.addAttribute(.backgroundColor, value: hitColor(i), range: NSIntersectionRange(r, old))
                }
            }
        }
        if hitsChanged {
            for r in co.paintedHits where NSMaxRange(r) <= len { storage.removeAttribute(.backgroundColor, range: r) }
            for (i, r) in foundRanges.enumerated() where NSMaxRange(r) <= len {
                storage.addAttribute(.backgroundColor, value: hitColor(i), range: r)
            }
        }
        if let new = range {
            storage.addAttribute(.backgroundColor, value: Self.spoken, range: new)
            storage.addAttribute(.foregroundColor, value: NSColor.black, range: new)
        }
        storage.endEditing()
        // The current hit's text, not its index: while typing, hit 0 of one
        // query is not hit 0 of the next.
        let currentHit = currentFound.flatMap { foundRanges.indices.contains($0) ? foundRanges[$0] : nil }
        co.highlighted = range
        co.paintedHits = foundRanges
        co.paintedCurrent = currentFound
        if let hit = currentHit, hit != co.scrolledHit {
            co.scrolledHit = hit
            tv.scrollRangeToVisible(hit)                // asked for: scroll even under the pointer
        } else if let new = range, !co.mouseInside {
            tv.scrollRangeToVisible(new)
        }
    }
}
