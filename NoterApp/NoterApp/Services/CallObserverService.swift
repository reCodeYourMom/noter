import CallKit
import Combine

final class CallObserverService: NSObject, ObservableObject, CXCallObserverDelegate {
    static let shared = CallObserverService()

    @Published var isOnCall = false
    @Published var autoRecord = true

    private let observer = CXCallObserver()
    private var wasRecordingBeforeCall = false

    private override init() {
        self.autoRecord = UserDefaults.standard.object(forKey: "autoRecord") as? Bool ?? true
        super.init()
        observer.setDelegate(self, queue: .main)
        print("[Noter] CXCallObserver delegate configuré")
    }

    func callObserver(_ callObserver: CXCallObserver, callChanged call: CXCall) {
        print("[Noter] Call event — connected:\(call.hasConnected) ended:\(call.hasEnded) outgoing:\(call.isOutgoing)")

        if call.hasConnected && !call.hasEnded && !isOnCall {
            isOnCall = true
            print("[Noter] Appel connecté — autoRecord=\(autoRecord)")
            if autoRecord {
                Task { @MainActor in
                    let recorder = AudioRecorderService.shared
                    if !recorder.isRecording {
                        self.wasRecordingBeforeCall = false
                        recorder.startRecording(title: "Appel")
                        print("[Noter] Enregistrement démarré automatiquement")
                    } else {
                        self.wasRecordingBeforeCall = true
                        print("[Noter] Déjà en enregistrement, on ne redémarre pas")
                    }
                }
            }
        }

        if call.hasEnded && isOnCall {
            isOnCall = false
            print("[Noter] Appel terminé")
            if autoRecord && !wasRecordingBeforeCall {
                Task { @MainActor in
                    AudioRecorderService.shared.stopRecording()
                    print("[Noter] Enregistrement arrêté automatiquement")
                }
            }
        }
    }
}
