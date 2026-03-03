import AppIntents

struct StartRecordingIntent: AppIntent {
    static var title: LocalizedStringResource = "Start Noter Recording"
    static var description = IntentDescription("Démarre un enregistrement audio dans Noter")
    static var openAppWhenRun: Bool = true

    func perform() async throws -> some IntentResult {
        await AudioRecorderService.shared.startRecording()
        return .result()
    }
}
