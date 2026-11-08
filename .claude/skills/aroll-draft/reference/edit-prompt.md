<instructions>
You are editing the word-level transcript of raw A-roll: one person talking to camera who often retries phrases, restarts sentences and leaves filler behind. Pick the best material and cut the rest, so the kept words make a clean first-cut edit.

Rules:
1. You may only remove words. Never add, change, translate or reorder a word.
2. Words are separated by single spaces and may carry punctuation or symbols.
3. To remove a word, wrap the whole token, punctuation included, in tildes: ~the~ ~chance~ ~to...~. Every removed word gets its own pair of tildes.
4. Reply with a JSON array of strings with exactly as many segments as the input, each holding exactly the same words in the same order. Only tildes may be added.
5. Conversational openers such as "Now," "So," or "Okay," are fine to keep: this is a casual talking-head video.
6. CRUCIAL, continuous flow: never build a hybrid sentence out of pieces of different attempts. When the speaker restarts a phrase, remove one complete attempt (almost always the earlier one) and keep the other complete attempt intact.
7. When a phrase is attempted several times, keep the LAST attempt unless it is clearly broken (trails off, missing words, abandoned). The speaker retried because the earlier takes were wrong. Retakes can span several segments; a restart often shows as the same opening words appearing again.
8. Remove dead material entirely: mic and sound checks, self-talk ("wait, let me do that again"), abandoned fragments, standalone fillers ("um," "uh,") and stutter repeats at the start of a phrase ("I I think" -> cut one "I").
9. A filler or stutter glued between two kept words with no pause around it ("and, uh, I", "the the") cannot be cut cleanly: there is no silence to cut on, so the cut is either undone later or clips the neighbouring words. Spend cuts on whole phrases, false starts and fillers that stand on their own.
10. Do not leave a lone word or two kept between two cuts unless it carries meaning. A kept scrap shorter than about a second plays as a flicker of two jump cuts.
11. Do not over-cut. Keep all substantive content, including tangents and jokes that work. You are cutting mistakes, not summarising. When unsure whether something is a retake or new information, keep it.
12. Read the kept text through at the end: it must read as natural, complete, continuous speech.
</instructions>

<examples>
Input:
```
[
"Okay, so this is the backpack I've been carrying every day for the last two months.",
"Is this thing on? Testing, one, two.",
" And honestly, it surprised me. I didn't I didn't",
"I didn't expect much from it, but it turned out to be the best bag I own.",
"So let me tell you about the straps, so first the straps,",
"First, the straps are padded all the way down, which matters if you walk a lot.",
"I walk about five kilometres.",
"I walk about five kilometres every morning with this on my back and",
" I walk about five kilometres every morning with it, and my shoulders never hurt.",
"Quick side note, the zipper pulls glow in the dark, which my kid loves.",
"Now, let's talk about the bottom.",
"The bottom is completely, completely sealed.",
"The bottom is fully waterproof, so you can set it down on wet grass without thinking."
]
```

Output:
```
[
"Okay, so this is the backpack I've been carrying every day for the last two months.",
"~Is~ ~this~ ~thing~ ~on?~ ~Testing,~ ~one,~ ~two.~",
" And honestly, it surprised me. ~I~ ~didn't~ ~I~ ~didn't~",
"I didn't expect much from it, but it turned out to be the best bag I own.",
"~So~ ~let~ ~me~ ~tell~ ~you~ ~about~ ~the~ ~straps,~ ~so~ ~first~ ~the~ ~straps,~",
"First, the straps are padded all the way down, which matters if you walk a lot.",
"~I~ ~walk~ ~about~ ~five~ ~kilometres.~",
"~I~ ~walk~ ~about~ ~five~ ~kilometres~ ~every~ ~morning~ ~with~ ~this~ ~on~ ~my~ ~back~ ~and~",
" I walk about five kilometres every morning with it, and my shoulders never hurt.",
"Quick side note, the zipper pulls glow in the dark, which my kid loves.",
"Now, let's talk about the bottom.",
"~The~ ~bottom~ ~is~ ~completely,~ ~completely~ ~sealed.~",
"The bottom is fully waterproof, so you can set it down on wet grass without thinking."
]
```

INCORRECT editing (a hybrid sentence):
Input: "The best part of this lamp is the base... The best thing is that it dims all the way down."
Wrong: "The best part of this lamp is the ~base...~ ~The~ ~best~ ~thing~ ~is~ ~that~ it dims all the way down."
That leaves "The best part of this lamp is the it dims all the way down": a sentence nobody said.
Correct: "~The~ ~best~ ~part~ ~of~ ~this~ ~lamp~ ~is~ ~the~ ~base...~ The best thing is that it dims all the way down."
</examples>

{{PREFERENCES}}{{LANGUAGE}}{{CONTEXT}}Here is the transcription you need to edit. Reply with ONLY the edited JSON array (no prose, no code fences):

<transcription>
{{TRANSCRIPTION}}
</transcription>
