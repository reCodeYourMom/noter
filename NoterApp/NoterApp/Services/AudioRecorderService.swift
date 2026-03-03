import AVFoundation
import Combine

@MainActor
final class AudioRecorderService: ObservableObject {
    static let shared = AudioRecorderService()

    @Published var isRecording = false
    @Published var currentDuration: TimeInterval = 0
    @Published var audioLevel: Float = 0

    private var recorder: AVAudioRecorder?
    private var timer: Timer?
    private var startTime: Date?
    private var currentRecordingID: UUID?

    private init() {}

    func startRecording(title: String = "") {
        guard !isRecording else { return }

        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(
                .playAndRecord,
                options: [.mixWithOthers, .defaultToSpeaker, .allowBluetooth]
            )
            try session.setActive(true)
        } catch {
            print("AVAudioSession error: \(error)")
            return
        }

        let id = UUID()
        let filename = "\(id.uuidString).m4a"
        let fileURL = Recording.recordingsDirectory.appendingPathComponent(filename)

        let settings: [String: Any] = [
            AVFormatIDKey: Int(kAudioFormatMPEG4AAC),
            AVSampleRateKey: 48000,
            AVNumberOfChannelsKey: 1,
            AVEncoderAudioQualityKey: AVAudioQuality.high.rawValue,
        ]

        do {
            recorder = try AVAudioRecorder(url: fileURL, settings: settings)
            recorder?.isMeteringEnabled = true
            recorder?.record()
        } catch {
            print("AVAudioRecorder error: \(error)")
            return
        }

        currentRecordingID = id
        startTime = Date()
        isRecording = true
        currentDuration = 0
        audioLevel = 0

        let recording = Recording(
            id: id,
            title: title,
            date: Date(),
            duration: 0,
            filename: filename,
            isSent: false
        )
        RecordingStore.shared.add(recording)

        timer = Timer.scheduledTimer(withTimeInterval: 0.25, repeats: true) { [weak self] _ in
            Task { @MainActor in
                guard let self, let start = self.startTime else { return }
                self.currentDuration = Date().timeIntervalSince(start)
                self.recorder?.updateMeters()
                self.audioLevel = self.recorder?.averagePower(forChannel: 0) ?? -160
            }
        }
    }

    func stopRecording() {
        guard isRecording, let recorder else { return }

        recorder.stop()
        timer?.invalidate()
        timer = nil

        let duration = currentDuration

        if let id = currentRecordingID {
            RecordingStore.shared.updateDuration(id, duration: duration)
        }

        self.recorder = nil
        self.currentRecordingID = nil
        self.startTime = nil
        self.isRecording = false
        self.currentDuration = 0
        self.audioLevel = 0

        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    var currentID: UUID? { currentRecordingID }
}
