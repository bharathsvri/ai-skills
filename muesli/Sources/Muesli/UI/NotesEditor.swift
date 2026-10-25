import SwiftUI

/// The rough-notes pad. Local draft state so typing stays smooth while the
/// transcript updates behind it; saves debounced.
struct NotesEditor: View {
    @EnvironmentObject private var store: MeetingStore
    let meetingID: UUID

    @State private var draft = ""
    @State private var loaded = false
    @State private var saveTask: Task<Void, Never>?

    var body: some View {
        ZStack(alignment: .topLeading) {
            TextEditor(text: $draft)
                .font(.system(size: 14))
                .lineSpacing(3)
                .scrollContentBackground(.hidden)
                .padding(.horizontal, 12)
                .padding(.vertical, 10)

            if draft.isEmpty {
                Text("Type rough notes while you talk — fragments are fine.\nMuesli polishes them with the transcript when you hit ✨ Enhance.")
                    .foregroundStyle(.tertiary)
                    .font(.system(size: 14))
                    .padding(.horizontal, 17)
                    .padding(.vertical, 18)
                    .allowsHitTesting(false)
            }
        }
        .background(Color(nsColor: .textBackgroundColor))
        .onAppear {
            if !loaded {
                draft = store.meeting(meetingID)?.notesMD ?? ""
                loaded = true
            }
        }
        .onChange(of: draft) { _, newValue in
            guard loaded else { return }
            saveTask?.cancel()
            saveTask = Task {
                try? await Task.sleep(nanoseconds: 700_000_000)
                guard !Task.isCancelled else { return }
                store.updateNotes(meetingID, notes: newValue)
            }
        }
        .onDisappear {
            saveTask?.cancel()
            store.updateNotes(meetingID, notes: draft)
        }
    }
}
