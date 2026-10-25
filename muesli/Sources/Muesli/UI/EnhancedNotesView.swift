import SwiftUI

struct EnhancedNotesView: View {
    @EnvironmentObject private var store: MeetingStore
    @EnvironmentObject private var settings: AppSettings
    let meetingID: UUID
    let enhancing: Bool
    let onEnhance: () -> Void

    private var meeting: Meeting? { store.meeting(meetingID) }

    var body: some View {
        if enhancing {
            VStack(spacing: 12) {
                ProgressView()
                Text("Blending your notes with the transcript…")
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if let md = meeting?.enhancedMD {
            ScrollView {
                MarkdownView(markdown: md)
                    .padding(20)
                    .frame(maxWidth: 760, alignment: .leading)
                    .frame(maxWidth: .infinity)
            }
        } else {
            VStack(spacing: 12) {
                Image(systemName: "sparkles")
                    .font(.system(size: 34))
                    .foregroundStyle(Color.oat)
                Text("Turn your rough notes into polished ones")
                    .font(.title3.weight(.semibold))
                Text("Muesli merges what you typed with what was actually said —\ndecisions, action items, and details you didn't have time to write.")
                    .multilineTextAlignment(.center)
                    .foregroundStyle(.secondary)
                Button(action: onEnhance) {
                    Label(settings.hasAIConfigured ? "Enhance notes" : "Set up AI to enhance", systemImage: "sparkles")
                        .padding(.horizontal, 6)
                }
                .buttonStyle(.borderedProminent)
                .tint(.oat)
                .disabled(!(meeting?.hasTranscript ?? false) && (meeting?.notesMD.isEmpty ?? true))
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .padding()
        }
    }
}

/// Small, dependency-free Markdown renderer: block structure by hand,
/// inline styling via AttributedString.
struct MarkdownView: View {
    let markdown: String

    private enum Block: Identifiable {
        case heading(Int, String)
        case bullet(String, checked: Bool?)
        case numbered(Int, String)
        case quote(String)
        case rule
        case paragraph(String)

        var id: UUID { UUID() }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            ForEach(parse()) { block in
                render(block)
            }
        }
        .textSelection(.enabled)
    }

    private func parse() -> [Block] {
        var blocks: [Block] = []
        for rawLine in markdown.components(separatedBy: "\n") {
            let line = rawLine.trimmingCharacters(in: .whitespaces)
            if line.isEmpty { continue }
            if line == "---" || line == "***" {
                blocks.append(.rule)
            } else if line.hasPrefix("### ") {
                blocks.append(.heading(3, String(line.dropFirst(4))))
            } else if line.hasPrefix("## ") {
                blocks.append(.heading(2, String(line.dropFirst(3))))
            } else if line.hasPrefix("# ") {
                blocks.append(.heading(1, String(line.dropFirst(2))))
            } else if line.hasPrefix("- [ ] ") || line.hasPrefix("* [ ] ") {
                blocks.append(.bullet(String(line.dropFirst(6)), checked: false))
            } else if line.hasPrefix("- [x] ") || line.hasPrefix("* [x] ") {
                blocks.append(.bullet(String(line.dropFirst(6)), checked: true))
            } else if line.hasPrefix("- ") || line.hasPrefix("* ") {
                blocks.append(.bullet(String(line.dropFirst(2)), checked: nil))
            } else if line.hasPrefix("> ") {
                blocks.append(.quote(String(line.dropFirst(2))))
            } else if let (n, rest) = MarkdownView.numberedPrefix(line) {
                blocks.append(.numbered(n, rest))
            } else {
                blocks.append(.paragraph(line))
            }
        }
        return blocks
    }

    @ViewBuilder
    private func render(_ block: Block) -> some View {
        switch block {
        case .heading(let level, let text):
            styled(text)
                .font(level == 1 ? .title.weight(.bold) : level == 2 ? .title2.weight(.semibold) : .headline)
                .padding(.top, level == 1 ? 2 : 8)
        case .bullet(let text, let checked):
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                if let checked {
                    Image(systemName: checked ? "checkmark.square" : "square")
                        .foregroundStyle(checked ? Color.secondary : Color.oat)
                } else {
                    Text("•").foregroundStyle(Color.oat)
                }
                styled(text)
            }
            .padding(.leading, 4)
        case .numbered(let n, let text):
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text("\(n).")
                    .foregroundStyle(.secondary)
                    .monospacedDigit()
                styled(text)
            }
            .padding(.leading, 4)
        case .quote(let text):
            HStack(spacing: 10) {
                RoundedRectangle(cornerRadius: 2)
                    .fill(Color.oat.opacity(0.6))
                    .frame(width: 3)
                styled(text)
                    .foregroundStyle(.secondary)
                    .italic()
            }
        case .rule:
            Divider()
        case .paragraph(let text):
            styled(text)
        }
    }

    /// "3. item" → (3, "item"); nil when the line isn't a numbered-list item.
    static func numberedPrefix(_ line: String) -> (Int, String)? {
        guard let dot = line.firstIndex(of: ".") else { return nil }
        let head = line[line.startIndex..<dot]
        guard !head.isEmpty, head.count <= 3, head.allSatisfy(\.isNumber), let n = Int(head) else { return nil }
        let afterDot = line.index(after: dot)
        guard afterDot < line.endIndex, line[afterDot] == " " else { return nil }
        let rest = line[line.index(after: afterDot)...].trimmingCharacters(in: .whitespaces)
        guard !rest.isEmpty else { return nil }
        return (n, rest)
    }

    private func styled(_ text: String) -> Text {
        if let attributed = try? AttributedString(
            markdown: text,
            options: AttributedString.MarkdownParsingOptions(interpretedSyntax: .inlineOnlyPreservingWhitespace)
        ) {
            return Text(attributed)
        }
        return Text(text)
    }
}
