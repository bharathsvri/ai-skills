import SwiftUI

/// Chat with one meeting: answers grounded in the transcript + notes.
struct AskView: View {
    @EnvironmentObject private var store: MeetingStore
    @EnvironmentObject private var settings: AppSettings
    let meetingID: UUID

    @State private var question = ""
    @State private var thinking = false
    @State private var errorText: String?
    @FocusState private var fieldFocused: Bool

    private var meeting: Meeting? { store.meeting(meetingID) }

    var body: some View {
        VStack(spacing: 0) {
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 12) {
                        if meeting?.chat.isEmpty ?? true {
                            VStack(spacing: 8) {
                                Image(systemName: "bubble.left.and.text.bubble.right")
                                    .font(.system(size: 30))
                                    .foregroundStyle(.tertiary)
                                Text("Ask anything about this meeting.")
                                    .foregroundStyle(.secondary)
                                Text("“What did we decide?” · “List every number mentioned” · “Draft a follow-up email”")
                                    .font(.caption)
                                    .foregroundStyle(.tertiary)
                            }
                            .frame(maxWidth: .infinity)
                            .padding(.top, 60)
                        }
                        ForEach(meeting?.chat ?? []) { message in
                            ChatBubble(message: message)
                                .id(message.id)
                        }
                        if thinking {
                            HStack(spacing: 8) {
                                ProgressView().controlSize(.small)
                                Text("Reading the meeting…").foregroundStyle(.secondary).font(.callout)
                            }
                            .id("thinking")
                        }
                        if let errorText {
                            Label(errorText, systemImage: "exclamationmark.triangle")
                                .font(.callout)
                                .foregroundStyle(.orange)
                        }
                    }
                    .padding(16)
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
                .onChange(of: meeting?.chat.count ?? 0) { _, _ in
                    if let last = meeting?.chat.last?.id {
                        withAnimation { proxy.scrollTo(last, anchor: .bottom) }
                    }
                }
            }

            Divider()
            HStack(spacing: 8) {
                TextField(settings.hasAIConfigured ? "Ask about this meeting…" : "Add an AI provider in Settings first…",
                          text: $question)
                    .textFieldStyle(.roundedBorder)
                    .focused($fieldFocused)
                    .onSubmit(send)
                    .disabled(!settings.hasAIConfigured || thinking)
                Button(action: send) {
                    Image(systemName: "arrow.up.circle.fill")
                        .font(.title2)
                        .foregroundStyle(question.isEmpty ? Color.secondary : Color.oat)
                }
                .buttonStyle(.plain)
                .disabled(question.isEmpty || thinking || !settings.hasAIConfigured)
            }
            .padding(10)
        }
    }

    private func send() {
        let q = question.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !q.isEmpty, !thinking, let meeting else { return }
        question = ""
        errorText = nil
        store.appendChat(meetingID, message: ChatMessage(role: "user", text: q))
        thinking = true
        Task {
            defer { thinking = false }
            do {
                let history = store.meeting(meetingID)?.chat.dropLast().map { $0 } ?? []
                let answer = try await Enhancer(settings: settings).ask(
                    meeting: meeting,
                    history: Array(history),
                    question: q
                )
                store.appendChat(meetingID, message: ChatMessage(role: "assistant", text: answer))
            } catch {
                errorText = error.localizedDescription
            }
            fieldFocused = true
        }
    }
}

struct ChatBubble: View {
    let message: ChatMessage

    var body: some View {
        if message.role == "user" {
            HStack {
                Spacer(minLength: 60)
                Text(message.text)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
                    .background(Color.oat.opacity(0.18), in: RoundedRectangle(cornerRadius: 12))
                    .textSelection(.enabled)
            }
        } else {
            MarkdownView(markdown: message.text)
                .padding(.trailing, 40)
        }
    }
}
