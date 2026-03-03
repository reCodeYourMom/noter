import SwiftUI

struct ActiveRecordingView: View {
    @ObservedObject var recorder = AudioRecorderService.shared

    var body: some View {
        VStack(spacing: 32) {
            Spacer()

            // Timer
            Text(formatDuration(recorder.currentDuration))
                .font(.system(size: 64, weight: .light, design: .monospaced))
                .foregroundColor(.red)

            // Audio level indicator
            AudioLevelView(level: recorder.audioLevel)
                .frame(height: 40)
                .padding(.horizontal, 40)

            Text("Enregistrement en cours...")
                .font(.subheadline)
                .foregroundStyle(.secondary)

            Spacer()

            // Stop button
            Button {
                recorder.stopRecording()
            } label: {
                ZStack {
                    Circle()
                        .fill(.red)
                        .frame(width: 72, height: 72)
                    RoundedRectangle(cornerRadius: 6)
                        .fill(.white)
                        .frame(width: 24, height: 24)
                }
            }
            .padding(.bottom, 48)
        }
    }

    private func formatDuration(_ t: TimeInterval) -> String {
        let m = Int(t) / 60
        let s = Int(t) % 60
        return String(format: "%02d:%02d", m, s)
    }
}

struct AudioLevelView: View {
    let level: Float // -160 to 0

    private var normalizedLevel: CGFloat {
        let clamped = max(-60, min(0, level))
        return CGFloat((clamped + 60) / 60)
    }

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                RoundedRectangle(cornerRadius: 4)
                    .fill(Color(.systemGray5))
                RoundedRectangle(cornerRadius: 4)
                    .fill(normalizedLevel > 0.8 ? .red : .green)
                    .frame(width: geo.size.width * normalizedLevel)
                    .animation(.easeOut(duration: 0.1), value: normalizedLevel)
            }
        }
    }
}
