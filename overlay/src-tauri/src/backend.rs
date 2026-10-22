//! Starts the Python backend and ties its lifetime to ours (PLAN.md §1).
//!
//! - The child is assigned to a Job Object with KILL_ON_JOB_CLOSE: when this
//!   process exits for any reason, Windows kills the backend and everything it
//!   started (later: `claude`).
//! - The session token goes to the child through its environment, never argv.
//! - The child announces its port on stdout: `SWIFT_BACKEND_READY port=<n>`.
//!
//! Dev override: `SWIFT_BACKEND_PORT` + `SWIFT_SESSION_TOKEN` connect to a
//! backend you started yourself instead of spawning one.

use std::io::{BufRead, BufReader};
use std::os::windows::io::AsRawHandle;
use std::os::windows::process::CommandExt;
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::{Arc, Mutex};

use serde::Serialize;
use tauri::{AppHandle, Emitter};
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::System::JobObjects::{
    AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
    SetInformationJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
};

const CREATE_NO_WINDOW: u32 = 0x0800_0000;

#[derive(Clone, Serialize, Default)]
pub struct BackendInfo {
    pub port: u16,
    pub token: String,
}

#[derive(Default)]
pub struct Backend {
    pub info: Option<BackendInfo>,
    /// When the backend's ready line arrived.
    pub ready_at: Option<std::time::Instant>,
    pub error: Option<String>,
    child: Option<Child>,
    _stdin: Option<ChildStdin>,
    job: Option<isize>,
}

pub type SharedBackend = Arc<Mutex<Backend>>;

fn new_token() -> String {
    let mut buf = [0u8; 32];
    getrandom::getrandom(&mut buf).expect("OS random number generator unavailable");
    buf.iter().map(|b| format!("{b:02x}")).collect()
}

fn repo_root() -> PathBuf {
    if let Ok(root) = std::env::var("SWIFT_ROOT") {
        return PathBuf::from(root);
    }
    // overlay/src-tauri -> repository root
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..").join("..")
}

fn kill_on_close_job() -> Option<isize> {
    unsafe {
        let job = CreateJobObjectW(std::ptr::null(), std::ptr::null());
        if job.is_null() {
            return None;
        }
        let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        let ok = SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            &info as *const _ as *const core::ffi::c_void,
            std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
        );
        (ok != 0).then_some(job as isize)
    }
}

pub fn start(app: &AppHandle, shared: SharedBackend) {
    if let (Ok(port), Ok(token)) = (
        std::env::var("SWIFT_BACKEND_PORT"),
        std::env::var("SWIFT_SESSION_TOKEN"),
    ) {
        let port = port.parse().unwrap_or(0);
        shared.lock().unwrap().info = Some(BackendInfo { port, token });
        return;
    }

    let root = repo_root();
    let python = std::env::var("SWIFT_PYTHON")
        .map(PathBuf::from)
        .unwrap_or_else(|_| root.join(".venv").join("Scripts").join("python.exe"));
    let token = new_token();

    let spawned = Command::new(&python)
        .args(["-m", "swift.backend", "--config"])
        .arg(root.join("config.yaml"))
        .current_dir(&root)
        .env("SWIFT_SESSION_TOKEN", &token)
        .env("PYTHONUNBUFFERED", "1")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .creation_flags(CREATE_NO_WINDOW)
        .spawn();

    let mut child = match spawned {
        Ok(child) => child,
        Err(e) => {
            let msg = format!("could not start the backend ({}): {e}", python.display());
            shared.lock().unwrap().error = Some(msg.clone());
            let _ = app.emit("backend-error", msg);
            return;
        }
    };

    let job = kill_on_close_job();
    if let Some(job) = job {
        unsafe {
            AssignProcessToJobObject(job as HANDLE, child.as_raw_handle() as HANDLE);
        }
    }

    let stdout = child.stdout.take().expect("stdout is piped");
    {
        let mut b = shared.lock().unwrap();
        b._stdin = child.stdin.take();
        b.child = Some(child);
        b.job = job;
    }

    let app = app.clone();
    std::thread::spawn(move || {
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            if let Some(rest) = line.strip_prefix("SWIFT_BACKEND_READY port=") {
                let port = rest.trim().parse().unwrap_or(0);
                let info = BackendInfo { port, token: token.clone() };
                let mut b = shared.lock().unwrap();
                b.info = Some(info);
                b.ready_at = Some(std::time::Instant::now());
                drop(b);
                let _ = app.emit("backend-ready", ());
            } else if let Some(rest) = line.strip_prefix("SWIFT_BACKEND_ERROR ") {
                shared.lock().unwrap().error = Some(rest.to_string());
                let _ = app.emit("backend-error", rest.to_string());
            } else {
                println!("[backend] {line}");
            }
        }
        // stdout closed: the backend has exited.
        let mut b = shared.lock().unwrap();
        b.info = None;
        if b.error.is_none() {
            b.error = Some("the backend stopped unexpectedly".into());
        }
        let _ = app.emit("backend-error", b.error.clone());
    });
}

pub fn stop(shared: &SharedBackend) {
    let mut b = shared.lock().unwrap();
    b._stdin = None; // closing stdin asks the backend to exit cleanly
    if let Some(mut child) = b.child.take() {
        for _ in 0..20 {
            if matches!(child.try_wait(), Ok(Some(_))) {
                return;
            }
            std::thread::sleep(std::time::Duration::from_millis(50));
        }
        let _ = child.kill();
    }
    // The job handle is closed by process exit, which kills anything left.
}
