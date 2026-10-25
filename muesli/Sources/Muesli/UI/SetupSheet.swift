import SwiftUI
import AVFoundation

struct SetupStatus {
    let micGranted: Bool
    let micUndetermined: Bool
    let screenGranted: Bool
    let whisperFound: Bool
    let modelFound: Bool
    let aiReady: Bool

    /// Items that block recording + local transcription entirely.
    var hasBlockers: Bool { !micGranted || !whisperFound || !modelFound }

    static func current(settings: AppSettings) -> SetupStatus {
        SetupStatus(
            micGranted: Permissions.micStatus == .authorized,
            micUndetermined: Permissions.micStatus == .notDetermined,
            screenGranted: Permissions.screenCaptureGranted,
            whisperFound: settings.resolveWhisperBinary() != nil,
            modelFound: settings.modelURL != nil,
            aiReady: settings.hasAIConfigured
        )
    }
}

/// First-run checklist. Everything Muesli needs, with one button per item.
struct SetupSheet: View {
    @EnvironmentObject private var settings: AppSettings
    @Environment(\.dismiss) private var dismiss
    @StateObject private var downloader = ModelDownloader()
    @State private var status: SetupStatus?
    @State private var refreshTimer: Timer?

    private let recommendedModel = WhisperModelInfo.catalog[1] // base.en

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 12) {
                Text("🥣").font(.system(size: 40))
                VStack(alignment: .leading, spacing: 2) {
                    Text("Set up Muesli").font(.title2.weight(.semibold))
                    Text("Local-first meeting notes. Five quick things:")
                        .foregroundStyle(.secondary)
                }
            }
            .padding(.bottom, 16)

            if let s = status {
                VStack(spacing: 10) {
                    SetupRow(
                        done: s.micGranted,
                        title: "Microphone",
                        detail: "Your side of the conversation (labeled “Me”).",
                        actionLabel: s.micUndetermined ? "Grant" : "Open Settings"
                    ) {
                        if s.micUndetermined {
                            Task { _ = await Permissions.ensureMicAccess(); refresh() }
                        } else {
                            Permissions.openMicSettings()
                        }
                    }
                    SetupRow(
                        done: s.screenGranted,
                        title: "System audio (Screen & System Audio Recording)",
                        detail: "Everyone else on the call (labeled “Them”) — captured from your Mac's own audio, no bot joins. macOS puts this under Screen Recording; after enabling, relaunch Muesli.",
                        actionLabel: "Enable"
                    ) {
                        if !Permissions.requestScreenCapture() {
                            Permissions.openScreenCaptureSettings()
                        }
                        refresh()
                    }
                    SetupRow(
                        done: s.whisperFound,
                        title: "Whisper engine",
                        detail: s.whisperFound
                            ? "Found \(settings.resolveWhisperBinary()?.path ?? "")"
                            : "Install with Homebrew:  brew install whisper-cpp",
                        actionLabel: "Copy command"
                    ) {
                        NSPasteboard.general.clearContents()
                        NSPasteboard.general.setString("brew install whisper-cpp", forType: .string)
                    }
                    SetupRow(
                        done: s.modelFound,
                        title: "Speech model",
                        detail: downloader.downloading != nil
                            ? "Downloading… \(Int(downloader.progress * 100))%"
                            : (s.modelFound ? settings.modelFileName : "\(recommendedModel.label) · \(recommendedModel.sizeMB) MB, one-time download"),
                        actionLabel: downloader.downloading != nil ? "Downloading…" : "Download"
                    ) {
                        downloader.download(recommendedModel, to: settings.modelsDir)
                    }
                    SetupRow(
                        done: s.aiReady,
                        title: "AI for enhancement (optional)",
                        detail: "Claude API key or a local Ollama — only needed for ✨ Enhance and Ask. Recording and transcription are fully local.",
                        actionLabel: "Open AI Settings"
                    ) {
                        openAISettings()
                    }
                }
            }

            if let err = downloader.error {
                Label(err, systemImage: "exclamationmark.triangle")
                    .font(.caption)
                    .foregroundStyle(.orange)
                    .padding(.top, 8)
            }

            HStack {
                Text("Audio, transcripts, and notes never leave this Mac unless you enhance with a cloud model.")
                    .font(.caption)
                    .foregroundStyle(.tertiary)
                Spacer()
                Button("Done") { dismiss() }
                    .buttonStyle(.borderedProminent)
                    .tint(.oat)
                    .keyboardShortcut(.defaultAction)
            }
            .padding(.top, 16)
        }
        .padding(24)
        .frame(width: 560)
        .onAppear {
            refresh()
            refreshTimer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { _ in
                Task { @MainActor in refresh() }
            }
        }
        .onDisappear {
            refreshTimer?.invalidate()
            refreshTimer = nil
        }
    }

    private func refresh() {
        status = SetupStatus.current(settings: settings)
    }

    private func openAISettings() {
        if #available(macOS 14.0, *) {
            NSApp.sendAction(Selector(("showSettingsWindow:")), to: nil, from: nil)
        } else {
            NSApp.sendAction(Selector(("showPreferencesWindow:")), to: nil, from: nil)
        }
    }
}

struct SetupRow: View {
    let done: Bool
    let title: String
    let detail: String
    let actionLabel: String
    let action: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: done ? "checkmark.circle.fill" : "circle")
                .font(.title3)
                .foregroundStyle(done ? Color.green : Color.secondary)
                .padding(.top, 1)
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.body.weight(.medium))
                Text(detail)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer()
            if !done {
                Button(actionLabel, action: action)
                    .controlSize(.small)
            }
        }
        .padding(10)
        .background(Color.primary.opacity(0.04), in: RoundedRectangle(cornerRadius: 8))
    }
}
