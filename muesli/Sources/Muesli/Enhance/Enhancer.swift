import Foundation

enum EnhanceError: LocalizedError {
    case noAPIKey
    case http(Int, String)
    case badResponse
    case nothingToEnhance

    var errorDescription: String? {
        switch self {
        case .noAPIKey:
            return "No Anthropic API key set. Add one in Settings → AI, or switch to Ollama."
        case .http(let code, let message):
            return "AI request failed (HTTP \(code)): \(message)"
        case .badResponse:
            return "The AI returned an unexpected response."
        case .nothingToEnhance:
            return "Nothing to enhance yet — record a meeting or type some notes first."
        }
    }
}

/// Turns rough notes + transcript into polished notes, and answers questions
/// about a meeting. Two backends: the Anthropic Messages API and Ollama.
struct Enhancer {
    let settings: AppSettings

    static let baseSystemPrompt = """
    You are Muesli, an expert meeting-notes editor. You turn a user's rough, fragmentary notes plus a raw \
    meeting transcript into clear, polished meeting notes.

    Rules:
    - The user's rough notes tell you what THEY cared about. Preserve their structure, emphasis, and intent; \
    expand shorthand into full thoughts.
    - Use the transcript to correct names, numbers, and facts, to fill gaps, and to add important decisions, \
    commitments, action items, and open questions the user didn't write down.
    - In the transcript, "Me" is the note-taker speaking; "Them" is everyone else on the call.
    - The transcript is machine-generated and may contain recognition errors; prefer readings that make sense \
    in context. If the recording double-hears the same sentence from both speakers, attribute it sensibly.
    - Never invent facts that appear in neither the notes nor the transcript. Mark genuinely unclear points \
    with "(unclear)".
    - Write from the note-taker's perspective in plain, direct language. No corporate filler.
    - Output clean Markdown only — no preamble, no code fences. Start with a "# Title" line: a specific, \
    concrete title for this meeting (3–8 words).
    """

    // MARK: - Public API

    func enhance(meeting: Meeting) async throws -> String {
        let transcriptMD = MeetingStore.transcriptMarkdown(meeting)
        guard meeting.hasTranscript || !meeting.notesMD.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw EnhanceError.nothingToEnhance
        }
        let template = NoteTemplate.byID(meeting.templateID)
        let system = Enhancer.baseSystemPrompt + "\n\n" + template.instructions

        let df = DateFormatter()
        df.dateStyle = .full
        df.timeStyle = .short

        var user = """
        Meeting: \(meeting.title)
        Date: \(df.string(from: meeting.createdAt))
        Duration: \(formatClock(meeting.durationSeconds))
        Template: \(template.name)

        ## My rough notes
        \(meeting.notesMD.isEmpty ? "(none — build the notes from the transcript alone)" : meeting.notesMD)

        ## Transcript
        """
        user += "\n" + clamp(transcriptMD.isEmpty ? "(no transcript — polish the rough notes on their own)" : transcriptMD)
        user += "\n\nWrite the polished meeting notes now."

        return try await complete(system: system, messages: [["role": "user", "content": user]], maxTokens: 8192)
    }

    func ask(meeting: Meeting, history: [ChatMessage], question: String) async throws -> String {
        let transcriptMD = MeetingStore.transcriptMarkdown(meeting)
        let system = """
        You are Muesli, answering questions about one specific meeting. Ground every answer in the meeting \
        record below. If the record doesn't contain the answer, say so plainly. Reference moments as \
        [mm:ss] when useful. "Me" is the user; "Them" is everyone else. Be concise.

        ## The user's rough notes
        \(meeting.notesMD.isEmpty ? "(none)" : meeting.notesMD)

        ## Transcript
        \(clamp(transcriptMD.isEmpty ? "(none)" : transcriptMD, limit: 120_000))
        """
        var messages: [[String: String]] = []
        for m in history.suffix(12) {
            messages.append(["role": m.role, "content": m.text])
        }
        messages.append(["role": "user", "content": question])
        return try await complete(system: system, messages: messages, maxTokens: 2048)
    }

    /// Tiny connectivity check used by Settings and the CLI.
    func ping() async throws -> String {
        try await complete(system: "Reply with exactly: OK", messages: [["role": "user", "content": "ping"]], maxTokens: 16)
    }

    // MARK: - Backends

    private func complete(system: String, messages: [[String: String]], maxTokens: Int) async throws -> String {
        switch settings.provider {
        case .anthropic:
            return try await completeAnthropic(system: system, messages: messages, maxTokens: maxTokens)
        case .ollama:
            return try await completeOllama(system: system, messages: messages)
        }
    }

    private func completeAnthropic(system: String, messages: [[String: String]], maxTokens: Int) async throws -> String {
        let key = settings.anthropicKey
        guard !key.isEmpty else { throw EnhanceError.noAPIKey }

        var request = URLRequest(url: URL(string: "https://api.anthropic.com/v1/messages")!)
        request.httpMethod = "POST"
        request.timeoutInterval = 300
        request.setValue("application/json", forHTTPHeaderField: "content-type")
        request.setValue(key, forHTTPHeaderField: "x-api-key")
        request.setValue("2023-06-01", forHTTPHeaderField: "anthropic-version")

        let body: [String: Any] = [
            "model": settings.anthropicModel,
            "max_tokens": maxTokens,
            "temperature": 0.3,
            "system": system,
            "messages": messages,
        ]
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, response) = try await URLSession.shared.data(for: request)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard status == 200 else {
            let message = Self.errorMessage(from: data)
            throw EnhanceError.http(status, message)
        }

        struct AnthropicResponse: Decodable {
            struct Content: Decodable {
                let type: String
                let text: String?
            }
            let content: [Content]
        }
        guard let decoded = try? JSONDecoder().decode(AnthropicResponse.self, from: data),
              let text = decoded.content.first(where: { $0.type == "text" })?.text else {
            throw EnhanceError.badResponse
        }
        return text.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func completeOllama(system: String, messages: [[String: String]]) async throws -> String {
        let base = settings.ollamaBaseURL.trimmingCharacters(in: CharacterSet(charactersIn: "/ "))
        guard let url = URL(string: base + "/api/chat") else { throw EnhanceError.badResponse }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = 600
        request.setValue("application/json", forHTTPHeaderField: "content-type")

        var allMessages: [[String: String]] = [["role": "system", "content": system]]
        allMessages.append(contentsOf: messages)
        let body: [String: Any] = [
            "model": settings.ollamaModel,
            "messages": allMessages,
            "stream": false,
        ]
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, response) = try await URLSession.shared.data(for: request)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard status == 200 else {
            throw EnhanceError.http(status, Self.errorMessage(from: data))
        }
        struct OllamaResponse: Decodable {
            struct Message: Decodable { let content: String }
            let message: Message
        }
        guard let decoded = try? JSONDecoder().decode(OllamaResponse.self, from: data) else {
            throw EnhanceError.badResponse
        }
        return decoded.message.content.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func errorMessage(from data: Data) -> String {
        if let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            if let err = obj["error"] as? [String: Any], let msg = err["message"] as? String { return msg }
            if let msg = obj["error"] as? String { return msg }
        }
        return String(data: data.prefix(300), encoding: .utf8) ?? "unknown error"
    }

    /// Ollama models have small context windows; Claude does not, but cap anyway.
    private func clamp(_ text: String, limit: Int? = nil) -> String {
        let cap = limit ?? (settings.provider == .anthropic ? 350_000 : 24_000)
        guard text.count > cap else { return text }
        let tail = String(text.suffix(cap))
        return "(transcript truncated — showing the most recent part)\n…\n" + tail
    }
}
