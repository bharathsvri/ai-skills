import Foundation

struct WhisperSegment: Equatable {
    let start: Double // seconds within the transcribed file
    let end: Double
    let text: String
}

enum WhisperError: LocalizedError {
    case binaryNotFound
    case modelNotFound
    case failed(String)
    case timedOut

    var errorDescription: String? {
        switch self {
        case .binaryNotFound:
            return "whisper-cli not found. Install it with `brew install whisper-cpp`, or set the path in Settings → Transcription."
        case .modelNotFound:
            return "No Whisper model downloaded. Get one in Settings → Transcription."
        case .failed(let detail):
            return "Transcription failed: \(detail)"
        case .timedOut:
            return "Transcription timed out."
        }
    }
}

/// Thin wrapper around the whisper.cpp CLI. Runs one file at a time,
/// reads the JSON it writes, and returns timed segments.
struct WhisperTranscriber {
    let binary: URL
    let model: URL
    let language: String

    init(settings: AppSettings) throws {
        guard let bin = settings.resolveWhisperBinary() else { throw WhisperError.binaryNotFound }
        guard let model = settings.modelURL else { throw WhisperError.modelNotFound }
        self.binary = bin
        self.model = model
        self.language = settings.language.isEmpty ? "en" : settings.language
    }

    /// `prompt` biases recognition with the tail of the previous chunk so
    /// sentences that straddle a chunk boundary come out right.
    func transcribe(wav: URL, prompt: String? = nil, timeout: Double = 240) async throws -> [WhisperSegment] {
        let outBase = wav.deletingPathExtension()
        var args = [
            "-m", model.path,
            "-f", wav.path,
            "-l", language,
            "-oj",
            "-of", outBase.path,
            "-np",
        ]
        if let prompt, !prompt.isEmpty {
            args += ["--prompt", String(prompt.suffix(200))]
        }

        let process = Process()
        process.executableURL = binary
        process.arguments = args
        let stderrPipe = Pipe()
        process.standardError = stderrPipe
        process.standardOutput = Pipe()

        let timedOutFlag = Atomic(false)
        try await withCheckedThrowingContinuation { (cont: CheckedContinuation<Void, Error>) in
            process.terminationHandler = { p in
                if timedOutFlag.value {
                    cont.resume(throwing: WhisperError.timedOut)
                } else if p.terminationStatus != 0 {
                    let errData = stderrPipe.fileHandleForReading.readDataToEndOfFile()
                    let msg = String(data: errData.suffix(400), encoding: .utf8) ?? "exit \(p.terminationStatus)"
                    cont.resume(throwing: WhisperError.failed(msg.trimmingCharacters(in: .whitespacesAndNewlines)))
                } else {
                    cont.resume()
                }
            }
            do {
                try process.run()
                DispatchQueue.global().asyncAfter(deadline: .now() + timeout) {
                    if process.isRunning {
                        timedOutFlag.value = true
                        process.terminate()
                    }
                }
            } catch {
                process.terminationHandler = nil
                cont.resume(throwing: error)
            }
        }

        let jsonURL = outBase.appendingPathExtension("json")
        defer { try? FileManager.default.removeItem(at: jsonURL) }
        guard let data = try? Data(contentsOf: jsonURL) else {
            throw WhisperError.failed("no JSON output produced")
        }
        return try Self.parse(json: data)
    }

    // MARK: - Output parsing

    struct WhisperJSON: Decodable {
        struct Item: Decodable {
            struct Offsets: Decodable {
                let from: Int
                let to: Int
            }
            let offsets: Offsets
            let text: String
        }
        let transcription: [Item]
    }

    static func parse(json data: Data) throws -> [WhisperSegment] {
        let decoded = try JSONDecoder().decode(WhisperJSON.self, from: data)
        return decoded.transcription.compactMap { item in
            let text = clean(item.text)
            guard !text.isEmpty else { return nil }
            return WhisperSegment(
                start: Double(item.offsets.from) / 1000.0,
                end: Double(item.offsets.to) / 1000.0,
                text: text
            )
        }
    }

    /// Strips whisper artifacts: bracketed sound tags and empty fragments.
    static func clean(_ raw: String) -> String {
        var t = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        // Whole-segment sound annotations like [BLANK_AUDIO], (music), [Silence], ♪♪
        if t.hasPrefix("[") && t.hasSuffix("]") { return "" }
        if t.hasPrefix("(") && t.hasSuffix(")") { return "" }
        if t.allSatisfy({ "♪♫ .".contains($0) }) { return "" }
        if t.count < 2 { return "" }
        // Common silence hallucinations.
        let phantoms: Set<String> = ["thank you.", "thanks for watching!", "thanks for watching.", "you", "the end."]
        if phantoms.contains(t.lowercased()) { return "" }
        t = t.replacingOccurrences(of: "  ", with: " ")
        return t
    }
}

/// Tiny lock-protected box (whisper timeout flag crosses threads).
final class Atomic<T>: @unchecked Sendable {
    fileprivate let lock = NSLock()
    fileprivate var _value: T
    init(_ value: T) { _value = value }
    var value: T {
        get { lock.lock(); defer { lock.unlock() }; return _value }
        set { lock.lock(); defer { lock.unlock() }; _value = newValue }
    }
}

extension Atomic where T == Int {
    /// Atomic increment-and-get — used for engine generation tokens.
    func next() -> Int {
        lock.lock()
        defer { lock.unlock() }
        _value += 1
        return _value
    }
}
