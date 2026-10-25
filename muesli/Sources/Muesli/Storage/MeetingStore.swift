import Foundation
import SwiftUI

/// Owns every meeting on disk. Layout:
///
///     ~/Library/Application Support/Muesli/
///       models/                    whisper ggml models
///       meetings/<folder>/
///         meeting.json             source of truth
///         notes.md                 mirror of your rough notes
///         transcript.md            mirror of the transcript
///         enhanced.md              mirror of the AI-enhanced notes
///         mic.wav / system.wav     full-session audio (16 kHz mono)
///
/// The .md/.wav mirrors exist so your data is useful without Muesli.
@MainActor
final class MeetingStore: ObservableObject {
    @Published private(set) var meetings: [Meeting] = []

    let baseDir: URL
    let meetingsDir: URL

    init(baseDir: URL? = nil) {
        let root = baseDir ?? MeetingStore.defaultBaseDir()
        self.baseDir = root
        self.meetingsDir = root.appendingPathComponent("meetings", isDirectory: true)
        try? FileManager.default.createDirectory(at: meetingsDir, withIntermediateDirectories: true)
        load()
        seedWelcomeIfFirstRun()
    }

    nonisolated static func defaultBaseDir() -> URL {
        let appSupport = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return appSupport.appendingPathComponent("Muesli", isDirectory: true)
    }

    func meeting(_ id: UUID?) -> Meeting? {
        guard let id else { return nil }
        return meetings.first { $0.id == id }
    }

    func folder(for meeting: Meeting) -> URL {
        meetingsDir.appendingPathComponent(meeting.folderName, isDirectory: true)
    }

    // MARK: - Loading

    private func load() {
        let fm = FileManager.default
        guard let folders = try? fm.contentsOfDirectory(at: meetingsDir, includingPropertiesForKeys: nil) else { return }
        var loaded: [Meeting] = []
        for folder in folders where folder.hasDirectoryPath {
            let json = folder.appendingPathComponent("meeting.json")
            guard let data = try? Data(contentsOf: json) else { continue }
            if var m = try? JSONDecoder.muesli.decode(Meeting.self, from: data) {
                m.folderName = folder.lastPathComponent
                loaded.append(m)
            }
        }
        meetings = loaded.sorted { $0.createdAt > $1.createdAt }
    }

    // MARK: - Mutations

    @discardableResult
    func createMeeting(title: String? = nil, templateID: String = "auto") -> Meeting {
        let id = UUID()
        let now = Date()
        let meeting = Meeting(
            id: id,
            title: title ?? Meeting.defaultTitle(for: now),
            createdAt: now,
            templateID: templateID,
            folderName: Meeting.makeFolderName(for: now, id: id)
        )
        meetings.insert(meeting, at: 0)
        persist(meeting)
        return meeting
    }

    func update(_ meeting: Meeting) {
        guard let idx = meetings.firstIndex(where: { $0.id == meeting.id }) else { return }
        meetings[idx] = meeting
        persist(meeting)
    }

    func updateNotes(_ id: UUID, notes: String) {
        guard var m = meeting(id) else { return }
        m.notesMD = notes
        update(m)
    }

    func updateTitle(_ id: UUID, title: String) {
        guard var m = meeting(id), !title.trimmingCharacters(in: .whitespaces).isEmpty else { return }
        m.title = title
        update(m)
    }

    func updateTemplate(_ id: UUID, templateID: String) {
        guard var m = meeting(id) else { return }
        m.templateID = templateID
        update(m)
    }

    func setEnhanced(_ id: UUID, markdown: String) {
        guard var m = meeting(id) else { return }
        m.enhancedMD = markdown
        // Lift a "# Title" first line into the meeting title if the user never renamed it.
        if m.isDefaultTitle,
           let first = markdown.split(separator: "\n").first,
           first.hasPrefix("# ") {
            let lifted = first.dropFirst(2).trimmingCharacters(in: .whitespaces)
            if !lifted.isEmpty { m.title = lifted }
        }
        update(m)
    }

    func setDuration(_ id: UUID, seconds: Double) {
        guard var m = meeting(id) else { return }
        m.durationSeconds = seconds
        update(m)
    }

    func appendSegments(_ id: UUID, segments: [TranscriptSegment]) {
        guard var m = meeting(id), !segments.isEmpty else { return }
        m.transcript.append(contentsOf: segments)
        m.transcript.sort { $0.start < $1.start }
        update(m)
    }

    func clearTranscript(_ id: UUID) {
        guard var m = meeting(id) else { return }
        m.transcript = []
        update(m)
    }

    func appendChat(_ id: UUID, message: ChatMessage) {
        guard var m = meeting(id) else { return }
        m.chat.append(message)
        update(m)
    }

    func delete(_ meeting: Meeting) {
        meetings.removeAll { $0.id == meeting.id }
        let folder = folder(for: meeting)
        try? FileManager.default.trashItem(at: folder, resultingItemURL: nil)
    }

    // MARK: - Persistence

    private func persist(_ meeting: Meeting) {
        let folder = folder(for: meeting)
        let fm = FileManager.default
        try? fm.createDirectory(at: folder, withIntermediateDirectories: true)
        if let data = try? JSONEncoder.muesli.encode(meeting) {
            try? data.write(to: folder.appendingPathComponent("meeting.json"), options: .atomic)
        }
        // Plain-file mirrors.
        try? meeting.notesMD.write(to: folder.appendingPathComponent("notes.md"), atomically: true, encoding: .utf8)
        if let enhanced = meeting.enhancedMD {
            try? enhanced.write(to: folder.appendingPathComponent("enhanced.md"), atomically: true, encoding: .utf8)
        }
        if meeting.hasTranscript {
            let md = MeetingStore.transcriptMarkdown(meeting)
            try? md.write(to: folder.appendingPathComponent("transcript.md"), atomically: true, encoding: .utf8)
        }
    }

    nonisolated static func transcriptMarkdown(_ meeting: Meeting) -> String {
        var out = "# Transcript — \(meeting.title)\n\n"
        for group in meeting.transcript.coalesced() {
            out += "**[\(formatClock(group.start))] \(group.speaker.label):** \(group.text)\n\n"
        }
        return out
    }

    // MARK: - Welcome meeting

    private func seedWelcomeIfFirstRun() {
        let flag = baseDir.appendingPathComponent(".welcomed")
        guard !FileManager.default.fileExists(atPath: flag.path), meetings.isEmpty else { return }
        var m = createMeeting(title: "Welcome to Muesli 🥣")
        m.notesMD = WelcomeContent.notes
        m.transcript = WelcomeContent.transcript
        m.enhancedMD = WelcomeContent.enhanced
        m.durationSeconds = 94
        update(m)
        try? Data().write(to: flag)
    }
}

enum WelcomeContent {
    static let notes = """
    - muesli = open-source granola
    - type rough notes here during the call, fragments fine
    - whisper runs locally → transcript stays on this mac
    - hit ✨ Enhance after → claude/ollama merges notes + transcript
    """

    static let transcript: [TranscriptSegment] = [
        .init(speaker: .them, start: 2, end: 8, text: "The core idea: you take rough notes while you talk, and the app records who said what."),
        .init(speaker: .me, start: 9, end: 14, text: "Right — my mic is labeled Me, and everyone else comes through system audio as Them."),
        .init(speaker: .them, start: 15, end: 24, text: "Transcription is whisper.cpp running on your own machine, so nothing leaves the laptop unless you ask for enhancement."),
        .init(speaker: .me, start: 25, end: 33, text: "And when the call ends I press Enhance, and my fragments get rewritten into real notes using the transcript as the source of truth."),
        .init(speaker: .them, start: 34, end: 41, text: "Exactly. Action items, decisions, open questions — all pulled out automatically. Your rough notes decide the emphasis."),
    ]

    static let enhanced = """
    # Welcome to Muesli

    **TL;DR:** Muesli is an open-source, local-first meeting notepad. It captures your mic and your Mac's system audio (no bot joins the call), transcribes locally with Whisper, and then turns your rough notes into polished ones with AI.

    ## How a meeting works
    - Press **Start meeting** before (or during) a call — works with Zoom, Meet, Teams, anything that makes sound.
    - Type fragments in **Notes** while you talk. Don't slow down to write well.
    - Watch the **Transcript** tab fill in as you go — *Me* is your mic, *Them* is the other side.

    ## After the call
    - Press **✨ Enhance** — your notes get rewritten using the transcript as ground truth.
    - Use **Ask** to chat with the meeting ("what did we decide about pricing?").

    ## Action items
    - [ ] Open **Settings → Transcription** and confirm the Whisper model is downloaded
    - [ ] Add your Anthropic API key (or point Muesli at Ollama) in **Settings → AI**
    - [ ] Grant microphone + screen-recording permission when prompted

    ## Open questions
    - What should your first recorded meeting be?
    """
}

extension JSONEncoder {
    static var muesli: JSONEncoder {
        let e = JSONEncoder()
        e.dateEncodingStrategy = .iso8601
        e.outputFormatting = [.prettyPrinted, .sortedKeys]
        return e
    }
}

extension JSONDecoder {
    static var muesli: JSONDecoder {
        let d = JSONDecoder()
        d.dateDecodingStrategy = .iso8601
        return d
    }
}
