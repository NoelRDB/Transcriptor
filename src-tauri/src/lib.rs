use std::path::PathBuf;
use tauri::Manager;

const MEDIA_EXTENSIONS: &[&str] = &[
    "mp3", "wav", "m4a", "aac", "flac", "ogg", "opus", "mp4", "mov", "mkv", "avi", "webm", "m4v",
];

#[tauri::command]
fn allow_media_file(app: tauri::AppHandle, path: String) -> Result<String, String> {
    let canonical = PathBuf::from(&path)
        .canonicalize()
        .map_err(|_| "El archivo multimedia no existe o ya no es accesible.".to_string())?;
    if !canonical.is_file() {
        return Err("La ruta seleccionada no corresponde a un archivo.".to_string());
    }
    let extension = canonical
        .extension()
        .and_then(|value| value.to_str())
        .map(str::to_ascii_lowercase)
        .ok_or_else(|| "El archivo no tiene una extensión compatible.".to_string())?;
    if !MEDIA_EXTENSIONS.contains(&extension.as_str()) {
        return Err("El formato multimedia no está admitido.".to_string());
    }
    app.asset_protocol_scope()
        .allow_file(&canonical)
        .map_err(|error| format!("No se pudo autorizar la reproducción local: {error}"))?;
    Ok(path)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![allow_media_file])
        .run(tauri::generate_context!())
        .expect("error while running Transcriptor");
}
