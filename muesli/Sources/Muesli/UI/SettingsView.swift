import SwiftUI

struct SettingsView: View {
    var body: some View {
        TabView {
            AISettingsTab()
                .tabItem { Label("AI", systemImage: "sparkles") }
            TranscriptionSettingsTab()
                .tabItem { Label("Transcription", systemImage: "waveform") }
            RecordingSettingsTab()
                .tabItem { Label("Recording", systemImage: "record.circle") }
        }
        .frame(width: 520)
        .padding(.bottom, 4)
    }
}

// MARK: - AI

struct AISettingsTab: View {
    @EnvironmentObject private var settings: AppSettings
    @State private var keyDraft = ""
    @State private var keyLoaded = false
    @State private var testResult: String?
    @State private var testing = false

    private let claudeModels = ["claude-sonnet-5", "claude-opus-5", "claude-haiku-4-5-20251001"]

    var body: some View {
        Form {
            Picker("Provider", selection: $settings.provider) {
                ForEach(AIProvider.allCases) { p in
                    Text(p.label).tag(p)
                }
            }
            .pickerStyle(.radioGroup)

            if settings.provider == .anthropic {
                SecureField("Anthropic API key", text: $keyDraft, prompt: Text("sk-ant-…"))
                    .onSubmit(saveKey)
                HStack {
                    Button("Save key", action: saveKey)
                        .disabled(keyDraft == settings.anthropicKey)
                    Text(settings.anthropicKey.isEmpty ? "No key stored" : "Key stored in your macOS Keychain")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Picker("Model", selection: $settings.anthropicModel) {
                    ForEach(claudeModels, id: \.self) { Text($0).tag($0) }
                    if !claudeModels.contains(settings.anthropicModel) {
                        Text(settings.anthropicModel).tag(settings.anthropicModel)
                    }
                }
            } else {
                TextField("Ollama URL", text: $settings.ollamaBaseURL)
                TextField("Ollama model", text: $settings.ollamaModel, prompt: Text("llama3.1"))
                Text("Requires the Ollama app running with the model pulled. Fully local — nothing leaves your Mac.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            HStack {
                Button {
                    test()
                } label: {
                    if testing { ProgressView().controlSize(.small) } else { Text("Test connection") }
                }
                .disabled(testing)
                if let testResult {
                    Text(testResult)
                        .font(.caption)
                        .foregroundStyle(testResult.hasPrefix("✓") ? Color.green : Color.orange)
                }
            }
        }
        .padding(20)
        .onAppear {
            if !keyLoaded {
                keyDraft = settings.anthropicKey
                keyLoaded = true
            }
        }
    }

    private func saveKey() {
        settings.anthropicKey = keyDraft.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func test() {
        testing = true
        testResult = nil
        Task {
            defer { testing = false }
            do {
                _ = try await Enhancer(settings: settings).ping()
                testResult = "✓ Connected"
            } catch {
                testResult = error.localizedDescription
            }
        }
    }
}

// MARK: - Transcription

struct TranscriptionSettingsTab: View {
    @EnvironmentObject private var settings: AppSettings
    @StateObject private var downloader = ModelDownloader()

    var body: some View {
        Form {
            LabeledContent("Whisper engine") {
                VStack(alignment: .trailing, spacing: 4) {
                    if let bin = settings.resolveWhisperBinary() {
                        Text(bin.path).font(.caption).foregroundStyle(.green)
                    } else {
                        Text("Not found — brew install whisper-cpp")
                            .font(.caption)
                            .foregroundStyle(.orange)
                    }
                }
            }
            TextField("Custom whisper-cli path (optional)", text: $settings.whisperPathOverride, prompt: Text("/opt/homebrew/bin/whisper-cli"))

            Divider()

            ForEach(WhisperModelInfo.catalog) { model in
                HStack {
                    VStack(alignment: .leading, spacing: 1) {
                        Text(model.label)
                        Text("\(model.sizeMB) MB").font(.caption).foregroundStyle(.secondary)
                    }
                    Spacer()
                    if ModelDownloader.isDownloaded(model, in: settings.modelsDir) {
                        if settings.modelFileName == model.id {
                            Label("Active", systemImage: "checkmark.circle.fill")
                                .foregroundStyle(Color.oat)
                                .labelStyle(.titleAndIcon)
                        } else {
                            Button("Use") { settings.modelFileName = model.id }
                        }
                    } else if downloader.downloading == model.id {
                        ProgressView(value: downloader.progress)
                            .frame(width: 90)
                    } else {
                        Button("Download") {
                            downloader.download(model, to: settings.modelsDir)
                        }
                        .disabled(downloader.downloading != nil)
                    }
                }
            }
            if let err = downloader.error {
                Text(err).font(.caption).foregroundStyle(.orange)
            }

            Divider()

            TextField("Language", text: $settings.language, prompt: Text("en, or auto"))
            Text("Use an English-only model with \"en\", or Large v3 Turbo with \"auto\" for other languages.")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding(20)
    }
}

// MARK: - Recording

struct RecordingSettingsTab: View {
    @EnvironmentObject private var settings: AppSettings

    var body: some View {
        Form {
            Toggle("Capture system audio (the other side of calls)", isOn: $settings.captureSystemAudio)
            Toggle("Echo cancellation on the mic (experimental)", isOn: $settings.echoCancellation)
            Text("Keeps call audio played through speakers out of your \"Me\" stream. Recording always starts on the raw mic instantly; echo cancellation is probed in the background and only used if it proves healthy. Headphones make it unnecessary.")
                .font(.caption)
                .foregroundStyle(.secondary)
            if settings.vpKnownBad {
                Label("Echo cancellation failed on this Mac and is being skipped. Toggle it off and on to retry.", systemImage: "exclamationmark.triangle")
                    .font(.caption)
                    .foregroundStyle(.orange)
            }

            Divider()

            LabeledContent("Transcription chunk") {
                VStack(alignment: .trailing) {
                    Slider(value: $settings.chunkSeconds, in: 15...30, step: 1) {
                        Text("Chunk length")
                    }
                    .frame(width: 200)
                    Text("\(Int(settings.chunkSeconds)) seconds — shorter = snappier live transcript, longer = better accuracy")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            Divider()

            LabeledContent("Your data") {
                Button("Open data folder") {
                    NSWorkspace.shared.activateFileViewerSelecting([MeetingStore.defaultBaseDir()])
                }
            }
            Text("Every meeting is a plain folder: meeting.json, notes.md, transcript.md, enhanced.md, mic.wav, system.wav.")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding(20)
    }
}
