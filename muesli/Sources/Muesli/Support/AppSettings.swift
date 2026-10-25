import Foundation
import SwiftUI

enum AIProvider: String, CaseIterable, Identifiable {
    case anthropic
    case ollama
    var id: String { rawValue }
    var label: String {
        switch self {
        case .anthropic: return "Claude (Anthropic API)"
        case .ollama: return "Ollama (fully local)"
        }
    }
}

/// Central app configuration. Everything lives in UserDefaults except the API key,
/// which is kept in the macOS Keychain.
final class AppSettings: ObservableObject {
    private let d = UserDefaults.standard

    @Published var provider: AIProvider { didSet { d.set(provider.rawValue, forKey: "provider") } }
    @Published var anthropicModel: String { didSet { d.set(anthropicModel, forKey: "anthropicModel") } }
    @Published var ollamaBaseURL: String { didSet { d.set(ollamaBaseURL, forKey: "ollamaBaseURL") } }
    @Published var ollamaModel: String { didSet { d.set(ollamaModel, forKey: "ollamaModel") } }
    @Published var whisperPathOverride: String { didSet { d.set(whisperPathOverride, forKey: "whisperPathOverride") } }
    @Published var modelFileName: String { didSet { d.set(modelFileName, forKey: "modelFileName") } }
    @Published var language: String { didSet { d.set(language, forKey: "language") } }
    @Published var echoCancellation: Bool {
        didSet {
            d.set(echoCancellation, forKey: "echoCancellation")
            // User touched the toggle → allow a fresh probe on the next recording.
            if vpKnownBad { vpKnownBad = false }
        }
    }
    /// Set when the voice-processing unit stalled, errored, or went silent on
    /// this machine; future recordings skip the probe until the user retries.
    @Published var vpKnownBad: Bool { didSet { d.set(vpKnownBad, forKey: "vpKnownBad") } }
    @Published var captureSystemAudio: Bool { didSet { d.set(captureSystemAudio, forKey: "captureSystemAudio") } }
    @Published var chunkSeconds: Double { didSet { d.set(chunkSeconds, forKey: "chunkSeconds") } }

    init() {
        provider = AIProvider(rawValue: d.string(forKey: "provider") ?? "") ?? .anthropic
        anthropicModel = d.string(forKey: "anthropicModel") ?? "claude-sonnet-5"
        ollamaBaseURL = d.string(forKey: "ollamaBaseURL") ?? "http://localhost:11434"
        ollamaModel = d.string(forKey: "ollamaModel") ?? "llama3.1"
        whisperPathOverride = d.string(forKey: "whisperPathOverride") ?? ""
        modelFileName = d.string(forKey: "modelFileName") ?? "ggml-base.en.bin"
        language = d.string(forKey: "language") ?? "en"
        echoCancellation = d.object(forKey: "echoCancellation") == nil ? true : d.bool(forKey: "echoCancellation")
        vpKnownBad = d.bool(forKey: "vpKnownBad")
        captureSystemAudio = d.object(forKey: "captureSystemAudio") == nil ? true : d.bool(forKey: "captureSystemAudio")
        chunkSeconds = d.object(forKey: "chunkSeconds") == nil ? 20 : d.double(forKey: "chunkSeconds")
    }

    // MARK: - API key (Keychain)

    var anthropicKey: String {
        get { KeychainHelper.read(account: "anthropic-api-key") ?? "" }
        set {
            if newValue.isEmpty {
                KeychainHelper.delete(account: "anthropic-api-key")
            } else {
                KeychainHelper.save(account: "anthropic-api-key", value: newValue)
            }
            objectWillChange.send()
        }
    }

    var hasAIConfigured: Bool {
        switch provider {
        case .anthropic: return !anthropicKey.isEmpty
        case .ollama: return true
        }
    }

    // MARK: - Whisper resolution

    var modelsDir: URL {
        MeetingStore.defaultBaseDir().appendingPathComponent("models", isDirectory: true)
    }

    var modelURL: URL? {
        let url = modelsDir.appendingPathComponent(modelFileName)
        return FileManager.default.fileExists(atPath: url.path) ? url : nil
    }

    static let whisperCandidates = [
        "/opt/homebrew/bin/whisper-cli",
        "/usr/local/bin/whisper-cli",
        "/opt/homebrew/bin/whisper-cpp",
        "/usr/local/bin/whisper-cpp",
    ]

    func resolveWhisperBinary() -> URL? {
        let fm = FileManager.default
        let override = whisperPathOverride.trimmingCharacters(in: .whitespaces)
        if !override.isEmpty {
            let expanded = (override as NSString).expandingTildeInPath
            return fm.isExecutableFile(atPath: expanded) ? URL(fileURLWithPath: expanded) : nil
        }
        for path in AppSettings.whisperCandidates where fm.isExecutableFile(atPath: path) {
            return URL(fileURLWithPath: path)
        }
        return nil
    }
}
