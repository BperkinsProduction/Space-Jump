import SwiftUI

@main
struct CloudHopperApp: App {
    var body: some Scene {
        WindowGroup {
            GameView()
                .ignoresSafeArea()
                .statusBarHidden()
                .persistentSystemOverlays(.hidden)
                .background(Color(red: 0.53, green: 0.80, blue: 1.0))
        }
    }
}
