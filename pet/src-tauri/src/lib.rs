use serde::{Deserialize, Serialize};
use std::sync::Mutex;
use tauri::{
    include_image,
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Manager, PhysicalPosition, PhysicalSize, State, WebviewWindow, WindowEvent,
};

#[derive(Clone, Copy, Debug, Serialize, Deserialize)]
pub struct HitRect {
    pub x: f64,
    pub y: f64,
    pub w: f64,
    pub h: f64,
}

#[derive(Default)]
struct PetState {
    hit: Mutex<Option<HitRect>>,
    /// User hid via menu (independent of Face mutex applied in the webview).
    user_hidden: Mutex<bool>,
}

fn hub_url() -> String {
    std::env::var("RAU_HUB_URL").unwrap_or_else(|_| "http://127.0.0.1:8765".into())
}

fn main_window(app: &AppHandle) -> Option<WebviewWindow> {
    app.get_webview_window("main")
}

fn apply_macos_window_chrome(window: &WebviewWindow) {
    #[cfg(target_os = "macos")]
    {
        use objc2::msg_send;
        use objc2::runtime::AnyObject;
        use objc2_app_kit::{
            NSColor, NSWindow, NSWindowCollectionBehavior, NSWindowStyleMask,
        };
        use objc2_foundation::{MainThreadMarker, NSNumber, NSString};

        let _ = MainThreadMarker::new().expect("macos window chrome on main thread");
        let ns = window.ns_window().expect("ns_window");
        // Safety: Tauri hands us a valid NSWindow pointer for the lifetime of the window.
        let ns_window = ns as *mut NSWindow;
        unsafe {
            let win = &*ns_window;
            win.setOpaque(false);
            win.setHasShadow(false);
            win.setBackgroundColor(Some(&NSColor::clearColor()));
            let mut mask = win.styleMask();
            mask.insert(NSWindowStyleMask::Borderless);
            win.setStyleMask(mask);
            let behavior = NSWindowCollectionBehavior::CanJoinAllSpaces
                | NSWindowCollectionBehavior::FullScreenAuxiliary
                | NSWindowCollectionBehavior::Stationary
                | NSWindowCollectionBehavior::Transient;
            win.setCollectionBehavior(behavior);
            // Keep above normal windows; still below screen savers.
            let _: () = msg_send![win, setLevel: 3_isize]; // NSFloatingWindowLevel ≈ 3
        }

        // WKWebView paints an opaque page fill unless drawsBackground is off.
        let _ = window.with_webview(|webview| {
            unsafe {
                let ptr = webview.inner();
                let obj = &*(ptr as *const AnyObject);
                let key = NSString::from_str("drawsBackground");
                let no = NSNumber::new_bool(false);
                let _: () = msg_send![obj, setValue: &*no, forKey: &*key];
            }
        });
    }
    let _ = window.set_always_on_top(true);
    let _ = window.set_ignore_cursor_events(true);
}

fn corner_position(
    window: &WebviewWindow,
    corner: &str,
) -> Option<PhysicalPosition<i32>> {
    let monitor = window.current_monitor().ok().flatten()?;
    let size = window.outer_size().ok()?;
    let area = monitor.work_area();
    let margin = 16i32;
    let x = match corner {
        "tl" | "bl" => area.position.x + margin,
        _ => area.position.x + area.size.width as i32 - size.width as i32 - margin,
    };
    let y = match corner {
        "tl" | "tr" => area.position.y + margin,
        _ => area.position.y + area.size.height as i32 - size.height as i32 - margin,
    };
    Some(PhysicalPosition::new(x, y))
}

#[tauri::command]
fn pet_set_hit_rect(state: State<PetState>, rect: HitRect) {
    *state.hit.lock().unwrap() = Some(rect);
}

#[tauri::command]
fn pet_hide(app: AppHandle, state: State<PetState>) {
    *state.user_hidden.lock().unwrap() = true;
    if let Some(w) = main_window(&app) {
        let _ = w.hide();
    }
    // Notify hub so Face mutex math stays consistent when user hides.
    let _ = std::thread::spawn(|| {
        let url = format!("{}/api/pet/visibility", hub_url());
        let _ = ureq_post_json(&url, r#"{"user_hidden":true}"#);
    });
}

#[tauri::command]
fn pet_show(app: AppHandle, state: State<PetState>) {
    *state.user_hidden.lock().unwrap() = false;
    if let Some(w) = main_window(&app) {
        let _ = w.show();
    }
    let _ = std::thread::spawn(|| {
        let url = format!("{}/api/pet/visibility", hub_url());
        let _ = ureq_post_json(&url, r#"{"user_hidden":false}"#);
    });
}

#[tauri::command]
fn pet_set_visible(app: AppHandle, state: State<PetState>, visible: bool) {
    let user_hidden = *state.user_hidden.lock().unwrap();
    if let Some(w) = main_window(&app) {
        if visible && !user_hidden {
            let _ = w.show();
        } else {
            let _ = w.hide();
        }
    }
}

#[tauri::command]
fn pet_quit(app: AppHandle) {
    app.exit(0);
}

#[tauri::command]
fn pet_move_corner(app: AppHandle, corner: String) {
    if let Some(w) = main_window(&app) {
        if let Some(pos) = corner_position(&w, corner.as_str()) {
            let _ = w.set_position(tauri::Position::Physical(pos));
        }
    }
}

#[tauri::command]
fn pet_start_drag(app: AppHandle) -> Result<(), String> {
    let w = main_window(&app).ok_or_else(|| "no main window".to_string())?;
    w.start_dragging().map_err(|e| e.to_string())
}

/// Minimal JSON POST without pulling reqwest into the binary.
fn ureq_post_json(url: &str, body: &str) -> Result<(), String> {
    use std::io::Write;
    use std::net::TcpStream;
    use std::time::Duration;

    let url = url
        .strip_prefix("http://")
        .ok_or_else(|| "only http hub supported".to_string())?;
    let (hostport, path) = url
        .split_once('/')
        .map(|(h, p)| (h, format!("/{p}")))
        .unwrap_or((url, "/".into()));
    let mut stream = TcpStream::connect(hostport).map_err(|e| e.to_string())?;
    stream
        .set_write_timeout(Some(Duration::from_secs(2)))
        .ok();
    let req = format!(
        "POST {path} HTTP/1.1\r\nHost: {hostport}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
        body.len()
    );
    stream.write_all(req.as_bytes()).map_err(|e| e.to_string())?;
    Ok(())
}

fn update_click_through(app: &AppHandle, state: &PetState) {
    let Some(window) = main_window(app) else { return };
    let Ok(cursor) = window.cursor_position() else {
        let _ = window.set_ignore_cursor_events(true);
        return;
    };
    let Ok(outer) = window.outer_position() else {
        let _ = window.set_ignore_cursor_events(true);
        return;
    };
    let scale = window.scale_factor().unwrap_or(1.0);
    let local_x = (cursor.x - outer.x as f64) / scale;
    let local_y = (cursor.y - outer.y as f64) / scale;
    let hit = state.hit.lock().unwrap().clone();
    let over = match hit {
        Some(r) => {
            local_x >= r.x && local_x <= r.x + r.w && local_y >= r.y && local_y <= r.y + r.h
        }
        None => false,
    };
    let _ = window.set_ignore_cursor_events(!over);
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(PetState::default())
        .invoke_handler(tauri::generate_handler![
            pet_set_hit_rect,
            pet_hide,
            pet_show,
            pet_set_visible,
            pet_quit,
            pet_move_corner,
            pet_start_drag,
        ])
        .setup(|app| {
            #[cfg(target_os = "macos")]
            {
                // Menu-bar companion — stay out of the Dock.
                let _ = app.set_activation_policy(tauri::ActivationPolicy::Accessory);
            }
            let handle = app.handle().clone();
            if let Some(window) = main_window(&handle) {
                let _ = window.set_size(PhysicalSize::new(280u32, 320u32));
                if let Some(pos) = corner_position(&window, "br") {
                    let _ = window.set_position(tauri::Position::Physical(pos));
                }
                apply_macos_window_chrome(&window);
                let win = window.clone();
                window.on_window_event(move |event| {
                    if let WindowEvent::Focused(true) = event {
                        apply_macos_window_chrome(&win);
                    }
                });
            }

            let show = MenuItem::with_id(app, "show", "Show pet", true, None::<&str>)?;
            let hide = MenuItem::with_id(app, "hide", "Hide pet", true, None::<&str>)?;
            let br = MenuItem::with_id(app, "br", "Move bottom-right", true, None::<&str>)?;
            let bl = MenuItem::with_id(app, "bl", "Move bottom-left", true, None::<&str>)?;
            let tr = MenuItem::with_id(app, "tr", "Move top-right", true, None::<&str>)?;
            let tl = MenuItem::with_id(app, "tl", "Move top-left", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Quit pet", true, None::<&str>)?;
            let menu = Menu::with_items(
                app,
                &[&show, &hide, &br, &bl, &tr, &tl, &quit],
            )?;

            let _tray = TrayIconBuilder::new()
                .icon(include_image!("icons/icon.png"))
                .menu(&menu)
                .tooltip("Rau Pet")
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show" => {
                        let state = app.state::<PetState>();
                        pet_show(app.clone(), state);
                    }
                    "hide" => {
                        let state = app.state::<PetState>();
                        pet_hide(app.clone(), state);
                    }
                    "br" | "bl" | "tr" | "tl" => {
                        pet_move_corner(app.clone(), event.id().as_ref().to_string());
                    }
                    "quit" => pet_quit(app.clone()),
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        let app = tray.app_handle();
                        let state = app.state::<PetState>();
                        let hidden = *state.user_hidden.lock().unwrap();
                        if hidden {
                            pet_show(app.clone(), state);
                        } else if let Some(w) = main_window(app) {
                            let _ = w.set_focus();
                        }
                    }
                })
                .build(app)?;

            // Poll cursor vs hit-rect for click-through.
            let poll_handle = handle.clone();
            std::thread::spawn(move || loop {
                std::thread::sleep(std::time::Duration::from_millis(32));
                let state = poll_handle.state::<PetState>();
                update_click_through(&poll_handle, &state);
            });

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running rau-pet");
}
