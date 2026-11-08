import Foundation

/// ⌘F in the transcript. Words are compared blind to case, accents,
/// punctuation and the spaces between them ("14 inch" finds "14-inch",
/// "set up" finds "setup"), number words as digits ("five" finds "5"); a match starts at the start of a word and its
/// last word may be partial, so "the co" already finds "the cow is cool".
///
/// Exact hits win. Only when there are none does it fall back to a typo-
/// tolerant pass over whole words (first letter right, then one edit per 5
/// letters of the query, at least 1 from 4 letters, at most 3), which covers
/// a transcription engine's near-misses ("gray" / "grey", "recieve" / "receive").
struct TranscriptSearch {
    /// Every word's letters and digits, run together.
    private let chars: [UInt16]
    /// For each entry of `chars`, the transcript word it came from.
    private let wordOfChar: [Int]
    /// Where each word starts in `chars`; nil for a word with no letters ("—").
    private let wordStart: [Int?]

    struct Result {
        /// Word index ranges, in time order, never overlapping.
        var matches: [ClosedRange<Int>] = []
        /// No exact hit: these are near-misses.
        var fuzzy = false
    }

    /// Queries with fewer letters and digits than this find nothing: one
    /// letter would paint the whole transcript. A lone digit is the exception
    /// ("5", and "five", which folds to it).
    static let minLength = 2

    static func searchable(_ query: String) -> Bool {
        let n = query.unicodeScalars.filter { CharacterSet.alphanumerics.contains($0) }.count
        return n >= minLength || (n == 1 && query.unicodeScalars.contains { CharacterSet.decimalDigits.contains($0) })
    }

    init(words: [String]) {
        var chars: [UInt16] = [], wordIndex: [Int] = [], starts: [Int?] = []
        for (i, w) in words.enumerated() {
            let n = Self.normalize(w)
            starts.append(n.isEmpty ? nil : chars.count)
            chars.append(contentsOf: n)
            wordIndex.append(contentsOf: repeatElement(i, count: n.count))
        }
        self.chars = chars
        self.wordOfChar = wordIndex
        self.wordStart = starts
    }

    /// Per space-separated token: letters and digits only, and a number word
    /// as its digits (an engine may write "five" one time, "5" the next).
    static func normalize(_ s: String) -> [UInt16] {
        let folded = s.folding(options: [.caseInsensitive, .diacriticInsensitive], locale: nil)
        var out: [UInt16] = []
        for token in folded.split(whereSeparator: \.isWhitespace) {
            let t = String(token.unicodeScalars.filter { CharacterSet.alphanumerics.contains($0) })
            out.append(contentsOf: (numbers[t] ?? t).utf16)
        }
        return out
    }

    private static let numbers: [String: String] = Dictionary(uniqueKeysWithValues: [
        "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
        "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen",
    ].enumerated().map { ($1, String($0)) })

    func find(_ query: String) -> Result {
        let q = Self.normalize(query)
        guard Self.searchable(query), !q.isEmpty else { return Result() }
        let exact = scan { start in
            guard start + q.count <= chars.count else { return nil }
            for k in 0..<q.count where chars[start + k] != q[k] { return nil }
            return start + q.count - 1
        }
        if !exact.isEmpty { return Result(matches: exact, fuzzy: false) }
        let budget = q.count < 4 ? 0 : min(max(q.count / 5, 1), 3)
        guard budget > 0 else { return Result() }
        return Result(matches: scan { fuzzyEnd(q, at: $0, budget: budget) }, fuzzy: true)
    }

    /// Tries every word start in order; `end` returns the last char of a hit
    /// there. A hit's words are skipped before trying the next start.
    private func scan(_ end: (Int) -> Int?) -> [ClosedRange<Int>] {
        var out: [ClosedRange<Int>] = []
        var w = 0
        while w < wordStart.count {
            if let s = wordStart[w], let e = end(s) {
                let last = wordOfChar[e]
                out.append(w...last)
                w = last + 1
            } else {
                w += 1
            }
        }
        return out
    }

    /// Levenshtein of `q` against the text from `start`, the text free to stop
    /// at the end of any word: the end of the closest one within `budget`
    /// edits (ties go to the length nearest the query's), or nil. Whole words
    /// only: with a free end, "cow" would be one edit from "corners".
    private func fuzzyEnd(_ q: [UInt16], at start: Int, budget: Int) -> Int? {
        guard chars[start] == q[0] else { return nil }
        let width = min(q.count + budget, chars.count - start)
        guard width > 0 else { return nil }
        // row[j]: edits to turn q[0..<i] into text[start..<start+j]
        var row = Array(0...width)
        var next = row
        for i in 1...q.count {
            next[0] = i
            var best = next[0]
            for j in 1...width {
                let sub = row[j - 1] + (q[i - 1] == chars[start + j - 1] ? 0 : 1)
                next[j] = min(sub, row[j] + 1, next[j - 1] + 1)
                best = min(best, next[j])
            }
            if best > budget { return nil }
            swap(&row, &next)
        }
        var pick: Int?
        for j in 1...width where row[j] <= budget
            && (start + j == chars.count || wordOfChar[start + j] != wordOfChar[start + j - 1]) {
            if let p = pick {
                if row[j] < row[p] || (row[j] == row[p] && abs(j - q.count) < abs(p - q.count)) { pick = j }
            } else {
                pick = j
            }
        }
        return pick.map { start + $0 - 1 }
    }
}
