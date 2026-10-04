import SwiftUI
import WebKit

/// Full-screen web view running the bundled game (copied into the app's Game/ folder at build time
/// by copy_game.sh). Files are served through a custom URL scheme rather than file:// so the game's
/// ES modules and fetch()-based model loading behave exactly as they do on the website.
struct GameView: UIViewRepresentable {
    static let scheme = "cloudhopper"
    static let startURL = URL(string: "\(scheme)://game/index.html?app=ios")!

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        let root = Bundle.main.resourceURL!.appendingPathComponent("Game", isDirectory: true)
        config.setURLSchemeHandler(BundleSchemeHandler(root: root), forURLScheme: Self.scheme)
        config.allowsInlineMediaPlayback = true
        config.mediaTypesRequiringUserActionForPlayback = []
        #if DEBUG
        ConsoleBridge.install(in: config.userContentController)
        #endif

        let web = WKWebView(frame: .zero, configuration: config)
        web.isOpaque = false
        web.backgroundColor = UIColor(red: 0.53, green: 0.80, blue: 1.0, alpha: 1)
        web.scrollView.isScrollEnabled = false
        web.scrollView.bounces = false
        web.scrollView.contentInsetAdjustmentBehavior = .never
        #if DEBUG
        web.isInspectable = true   // Safari ▸ Develop ▸ Simulator to debug the game
        #endif
        web.load(URLRequest(url: Self.startURL))
        return web
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {}
}

/// Serves files from a folder inside the app bundle for `cloudhopper://game/<path>` requests.
final class BundleSchemeHandler: NSObject, WKURLSchemeHandler {
    private let root: URL

    init(root: URL) {
        self.root = root.standardizedFileURL
    }

    func webView(_ webView: WKWebView, start task: WKURLSchemeTask) {
        guard let url = task.request.url else {
            task.didFailWithError(URLError(.badURL))
            return
        }
        let relative = url.path.isEmpty || url.path == "/" ? "index.html" : String(url.path.dropFirst())
        let file = root.appendingPathComponent(relative).standardizedFileURL
        // Stay inside the Game folder, whatever the path says.
        guard file.path.hasPrefix(root.path + "/"), let data = try? Data(contentsOf: file) else {
            respond(task, url: url, status: 404, data: Data(), type: "text/plain")
            return
        }
        respond(task, url: url, status: 200, data: data, type: Self.mimeType(for: file.pathExtension))
    }

    func webView(_ webView: WKWebView, stop task: WKURLSchemeTask) {}

    private func respond(_ task: WKURLSchemeTask, url: URL, status: Int, data: Data, type: String) {
        // WebKit gives custom-scheme pages an opaque origin, so module scripts and fetch() need CORS.
        let headers = ["Content-Type": type, "Content-Length": String(data.count), "Cache-Control": "no-cache",
                       "Access-Control-Allow-Origin": "*"]
        let response = HTTPURLResponse(url: url, statusCode: status, httpVersion: "HTTP/1.1", headerFields: headers)!
        task.didReceive(response)
        task.didReceive(data)
        task.didFinish()
    }

    private static func mimeType(for ext: String) -> String {
        switch ext.lowercased() {
        case "html": return "text/html; charset=utf-8"
        case "js", "mjs": return "text/javascript; charset=utf-8"
        case "json": return "application/json"
        case "glb": return "model/gltf-binary"
        case "webp": return "image/webp"
        case "png": return "image/png"
        case "jpg", "jpeg": return "image/jpeg"
        case "wasm": return "application/wasm"
        default: return "application/octet-stream"
        }
    }
}
