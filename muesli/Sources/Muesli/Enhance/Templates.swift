import Foundation

struct NoteTemplate: Identifiable, Equatable {
    let id: String
    let name: String
    let icon: String
    /// Template-specific structure instructions appended to the base system prompt.
    let instructions: String

    static let all: [NoteTemplate] = [
        NoteTemplate(
            id: "auto",
            name: "Auto",
            icon: "wand.and.stars",
            instructions: """
            Structure: open with a 2–3 sentence **TL;DR**, then sections that follow the shape of the user's \
            rough notes (or a sensible thematic structure if the notes are sparse). \
            End with **## Action items** (markdown checkboxes, with owner and deadline when mentioned) \
            and **## Open questions** if there are any.
            """
        ),
        NoteTemplate(
            id: "one-on-one",
            name: "1:1",
            icon: "person.2",
            instructions: """
            This is a one-on-one. Structure: **TL;DR**, **What's on their mind**, **What's on my mind**, \
            **Feedback exchanged**, **Decisions**, **## Action items** (split "Mine" vs "Theirs"), \
            and **Topics for next time**.
            """
        ),
        NoteTemplate(
            id: "sales",
            name: "Sales / Discovery",
            icon: "dollarsign.circle",
            instructions: """
            This is a sales or discovery call. Structure: **TL;DR** (deal temperature in one line), \
            **About the prospect** (company, role, context), **Pain points** (verbatim quotes where strong), \
            **Requirements & success criteria**, **Budget / timeline / decision process** (mark anything \
            not discussed as "not discussed"), **Objections**, **## Action items**, and **Next step** \
            (the single agreed next step, with date if set).
            """
        ),
        NoteTemplate(
            id: "standup",
            name: "Standup / Sync",
            icon: "person.3",
            instructions: """
            This is a team sync. Structure: **TL;DR**, **Updates by person/topic** (compact bullets), \
            **Blockers**, **Decisions**, and **## Action items** with owners.
            """
        ),
        NoteTemplate(
            id: "interview",
            name: "Interview",
            icon: "questionmark.bubble",
            instructions: """
            This is an interview (job, user research, or podcast). Structure: **TL;DR** (overall read), \
            **Background**, **Highlights by theme** (use short verbatim quotes for the strongest moments), \
            **Red flags / concerns** (only if evidenced), and **## Follow-ups**.
            """
        ),
        NoteTemplate(
            id: "brainstorm",
            name: "Brainstorm",
            icon: "lightbulb",
            instructions: """
            This is a brainstorm. Structure: **TL;DR**, **Ideas** (grouped by theme, every distinct idea kept, \
            best ones bolded with a one-line why), **Ideas parked/rejected and why**, **Decisions**, \
            and **## Action items**.
            """
        ),
    ]

    static func byID(_ id: String) -> NoteTemplate {
        all.first { $0.id == id } ?? all[0]
    }
}
