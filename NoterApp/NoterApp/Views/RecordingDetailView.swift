import SwiftUI
import AVFoundation

struct RecordingDetailView: View {
    let recording: Recording
    @ObservedObject var store = RecordingStore.shared
    @State private var isUploading = false
    @State private var showError = false
    @State private var errorMessage = ""
    @State private var isPlaying = false
    @State private var player: AVAudioPlayer?

    var body: some View {
        List {
            Section("Détails") {
                LabeledContent("Date") {
                    Text(recording.date, style: .date)
                }
                LabeledContent("Heure") {
                    Text(recording.date, style: .time)
                }
                LabeledContent("Durée") {
                    Text(recording.durationText)
                }
                LabeledContent("Statut") {
                    if recording.isSent {
                        Label("Envoyé", systemImage: "checkmark.circle.fill")
                            .foregroundColor(.green)
                    } else {
                        Label("Local", systemImage: "iphone")
                            .foregroundStyle(.secondary)
                    }
                }
            }

            Section {
                // Play/pause
                Button {
                    togglePlayback()
                } label: {
                    Label(isPlaying ? "Pause" : "Écouter", systemImage: isPlaying ? "pause.fill" : "play.fill")
                }

                // Upload
                if !recording.isSent {
                    Button {
                        Task { await upload() }
                    } label: {
                        if isUploading {
                            HStack {
                                ProgressView()
                                    .padding(.trailing, 8)
                                Text("Envoi en cours...")
                            }
                        } else {
                            Label("Envoyer au Mac", systemImage: "arrow.up.circle")
                        }
                    }
                    .disabled(isUploading)
                }
            }

            Section {
                Button(role: .destructive) {
                    store.delete(recording.id)
                } label: {
                    Label("Supprimer", systemImage: "trash")
                }
            }
        }
        .navigationTitle(recording.displayTitle)
        .alert("Erreur", isPresented: $showError) {
            Button("OK") {}
        } message: {
            Text(errorMessage)
        }
    }

    private func togglePlayback() {
        if isPlaying {
            player?.stop()
            isPlaying = false
        } else {
            do {
                player = try AVAudioPlayer(contentsOf: recording.fileURL)
                player?.play()
                isPlaying = true
            } catch {
                errorMessage = "Impossible de lire le fichier audio"
                showError = true
            }
        }
    }

    private func upload() async {
        isUploading = true
        do {
            _ = try await NoterAPIService.shared.uploadRecording(recording)
            store.markSent(recording.id)
        } catch {
            errorMessage = error.localizedDescription
            showError = true
        }
        isUploading = false
    }
}
