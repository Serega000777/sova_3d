//! Desktop shell (T-086, F-057) for Windows and macOS.
//!
//! The workspace itself is the web client; the shell is the native window around it,
//! plus the one thing a browser cannot do — remember which workspace this machine
//! talks to. `open_workspace` navigates the window at the URL the launcher confirms,
//! and the remembered URL is stored next to the app's own data, not in the page.

use std::fs;
use std::path::PathBuf;

use tauri::{Manager, Url};

const SETTINGS_FILE: &str = "workspace.json";
const DEFAULT_WORKSPACE: &str = "http://localhost:3100";

#[derive(serde::Serialize, serde::Deserialize, Default)]
struct Settings {
    workspace_url: Option<String>,
}

fn settings_path(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let dir = app
        .path()
        .app_config_dir()
        .map_err(|e| format!("no config directory: {e}"))?;
    fs::create_dir_all(&dir).map_err(|e| format!("cannot create {}: {e}", dir.display()))?;
    Ok(dir.join(SETTINGS_FILE))
}

/// The workspace this machine opens by default: what was saved, else localhost.
#[tauri::command]
fn workspace_url(app: tauri::AppHandle) -> String {
    settings_path(&app)
        .ok()
        .and_then(|path| fs::read_to_string(path).ok())
        .and_then(|raw| serde_json::from_str::<Settings>(&raw).ok())
        .and_then(|settings| settings.workspace_url)
        .unwrap_or_else(|| DEFAULT_WORKSPACE.to_string())
}

/// Remember the workspace and point the window at it. The URL is parsed here, so a
/// typo stays an error message in the launcher instead of a blank window.
#[tauri::command]
fn open_workspace(app: tauri::AppHandle, url: String) -> Result<(), String> {
    let parsed = Url::parse(url.trim()).map_err(|e| format!("not a valid URL: {e}"))?;
    match parsed.scheme() {
        "http" | "https" => {}
        scheme => return Err(format!("unsupported scheme {scheme:?}; use http or https")),
    }

    let settings = Settings {
        workspace_url: Some(parsed.to_string()),
    };
    if let Ok(path) = settings_path(&app) {
        let _ = fs::write(
            path,
            serde_json::to_string_pretty(&settings).unwrap_or_default(),
        );
    }

    let window = app
        .get_webview_window("main")
        .ok_or_else(|| "main window is gone".to_string())?;
    window
        .navigate(parsed)
        .map_err(|e| format!("could not open the workspace: {e}"))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![workspace_url, open_workspace])
        .setup(|_app| {
            // The window itself is declared in tauri.conf.json; it starts on the bundled
            // launcher, and `tauri dev` points it at the web client's dev server instead.
            #[cfg(debug_assertions)]
            if let Some(window) = _app.get_webview_window("main") {
                window.open_devtools();
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running the desktop shell");
}
