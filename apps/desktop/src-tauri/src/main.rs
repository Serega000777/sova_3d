// Windows release builds must not open a console window alongside the app.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    physical_ai_desktop_lib::run()
}
