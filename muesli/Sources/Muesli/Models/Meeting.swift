import Foundation

/// Who said a given transcript segment.
/// "me" comes from the microphone stream, "them" from system audio (everyone else on the call).
enum Speaker: String, Codable {
    case me
    case them

    var label: String {
        switch self {
        case .me: return "Me"
        case .them: return "Them"
        }
    }
}

struct TranscriptSegment: Identifiable, Codable, Equatable {
    var id: UUID = UUID()
    var speaker: Speaker
    /// Seconds from the start of the meeting.
    var start: Double
    var end: Double
    var text: String
}

struct ChatMessage: Identifiable, Codable, Equatable {
    var id: UUID = UUID()
    var role: String // "user" | "assistant"
    var text: String
    var date: Date = Date()
}

struct Meeting: Identifiable, Codable, Equatable {
    var id: UUID = UUID()
    var title: String
    var createdAt: Date = Date()
    var durationSeconds: Double = 0
    var templateID: String = "auto"
    var notesMD: String = ""
    var enhancedMD: String?
    var transcript: [TranscriptSegment] = []
    var chat: [ChatMessage] = []
    /// Folder name inside the meetings directory. Stable for the meeting's lifetime.
    var folderName: String

    var hasTranscript: Bool { !transcript.isEmpty }

    var isDefaultTitle: Bool { title.hasPrefix("Meeting · ") }

    static func defaultTitle(for date: Date = Date()) -> String {
        let f = DateFormatter()
        f.dateFormat = "h:mm a"
        return "Meeting · \(f.string(from: date))"
    }

    static func makeFolderName(for date: Date = Date(), id: UUID) -> String {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd-HHmmss"
        return "\(f.string(from: date))-\(id.uuidString.prefix(8))"
    }
}

extension Array where Element == TranscriptSegment {
    /// Groups consecutive segments by the same speaker into readable paragraphs.
    func coalesced(maxGap: Double = 6, maxSpan: Double = 45) -> [(id: UUID, speaker: Speaker, start: Double, text: String)] {
        var groups: [(id: UUID, speaker: Speaker, start: Double, end: Double, text: String)] = []
        for seg in self.sorted(by: { $0.start < $1.start }) {
            let t = seg.text.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !t.isEmpty else { continue }
            if var last = groups.last,
               last.speaker == seg.speaker,
               seg.start - last.end <= maxGap,
               seg.end - last.start <= maxSpan {
                last.text += " " + t
                last.end = Swift.max(last.end, seg.end)
                groups[groups.count - 1] = last
            } else {
                groups.append((seg.id, seg.speaker, seg.start, seg.end, t))
            }
        }
        return groups.map { ($0.id, $0.speaker, $0.start, $0.text) }
    }
}

func formatClock(_ seconds: Double) -> String {
    let s = Int(seconds.rounded())
    if s >= 3600 {
        return String(format: "%d:%02d:%02d", s / 3600, (s % 3600) / 60, s % 60)
    }
    return String(format: "%d:%02d", s / 60, s % 60)
}
