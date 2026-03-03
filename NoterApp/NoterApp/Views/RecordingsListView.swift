import SwiftUI

struct RecordingsListView: View {
    @ObservedObject var store = RecordingStore.shared
    @ObservedObject var recorder = AudioRecorderService.shared
    @State private var searchText = ""
    @State private var uploadingID: UUID?
    @State private var showError = false
    @State private var errorMessage = ""

    var filteredRecordings: [Recording] {
        if searchText.isEmpty { return store.recordings }
        return store.recordings.filter {
            $0.displayTitle.localizedCaseInsensitiveContains(searchText)
        }
    }

    var body: some View {
        NavigationStack {
            Group {
                if recorder.isRecording {
                    ActiveRecordingView()
                } else if store.recordings.isEmpty {
                    ContentUnavailableView(
                        "Aucun enregistrement",
                        systemImage: "waveform",
                        description: Text("Les enregistrements d'appels apparaîtront ici.\nConfigurez les Shortcuts iOS pour démarrer automatiquement.")
                    )
                } else {
                    List {
                        ForEach(filteredRecordings) { rec in
                            NavigationLink(destination: RecordingDetailView(recording: rec)) {
                                RecordingRow(recording: rec, isUploading: uploadingID == rec.id)
                            }
                            .swipeActions(edge: .trailing) {
                                if !rec.isSent {
                                    Button {
                                        Task { await upload(rec) }
                                    } label: {
                                        Label("Envoyer", systemImage: "arrow.up.circle")
                                    }
                                    .tint(.blue)
                                }
                            }
                            .swipeActions(edge: .leading) {
                                Button(role: .destructive) {
                                    store.delete(rec.id)
                                } label: {
                                    Label("Supprimer", systemImage: "trash")
                                }
                            }
                        }
                    }
                    .searchable(text: $searchText, prompt: "Rechercher")
                    .refreshable { store.load() }
                }
            }
            .navigationTitle("Noter")
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    NavigationLink(destination: SettingsView()) {
                        Image(systemName: "gear")
                    }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    if !recorder.isRecording {
                        Button {
                            recorder.startRecording()
                        } label: {
                            Image(systemName: "record.circle")
                                .foregroundColor(.red)
                        }
                    }
                }
            }
            .alert("Erreur", isPresented: $showError) {
                Button("OK") {}
            } message: {
                Text(errorMessage)
            }
        }
    }

    private func upload(_ rec: Recording) async {
        uploadingID = rec.id
        do {
            _ = try await NoterAPIService.shared.uploadRecording(rec)
            store.markSent(rec.id)
        } catch {
            errorMessage = error.localizedDescription
            showError = true
        }
        uploadingID = nil
    }
}

struct RecordingRow: View {
    let recording: Recording
    let isUploading: Bool

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                Text(recording.displayTitle)
                    .font(.headline)
                    .lineLimit(1)
                HStack(spacing: 8) {
                    Text(recording.date, style: .date)
                    Text(recording.durationText)
                        .foregroundStyle(.secondary)
                }
                .font(.caption)
                .foregroundStyle(.secondary)
            }
            Spacer()
            if isUploading {
                ProgressView()
            } else if recording.isSent {
                Image(systemName: "checkmark.circle.fill")
                    .foregroundColor(.green)
                    .font(.caption)
            }
        }
        .padding(.vertical, 2)
    }
}
