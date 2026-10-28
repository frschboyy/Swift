//! Starts the Python backend and ties its lifetime to ours (PLAN.md §1).
//!
//! - The child is assigned to a Job Object with KILL_ON_JOB_CLOSE: when this
//!   process exits for any reason, Windows kills the backend and everything it
//!   started (later: `claude`).
//! - The session token goes to the child through its environment, never argv.
//! - The child announces its port on stdout: `SWIFT_BACKEND_READY port=<n>`.
//!
//! - "Restart Swift" (the tray, or the card for a stopped engine; audit 2026-10,
//!   B-04) ends the old backend and its whole job first (its Claude Code CLIs,
//!   and with the process the microphone), then starts a new one. Each start has
//!   a generation, so the old backend's output closing can't clear the new one.
//!
//! Dev override: `SWIFT_BACKEND_PORT` + `SWIFT_SESSION_TOKEN` connect to a
//! backend you started yourself instead of spawning one.

use std::io::{BufRead, BufReader};
use std::os::windows::io::AsRawHandle;
use std::os::windows::process::CommandExt;
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use serde::Serialize;
use tauri::{AppHandle, Emitter};
use windows_sys::Win32::Foundation::{CloseHandle, HANDLE};
use windows_sys::Win32::System::JobObjects::{
    AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
    SetInformationJobObject, TerminateJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
};

const CREATE_NO_WINDOW: u32 = 0x0800_0000;
/// How long a backend asked to exit (stdin closed) gets before its job is ended.
const QUIT_GRACE: Duration = Duration::from_secs(1);
const RESTART_GRACE: Duration = Duration::from_secs(3);

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
    /// Which start this is: news from an older backend's output (after a restart) is ignored.
    generation: u64,
}

pub type SharedBackend = Arc<Mutex<Backend>>;

fn new_token() -> String {
    let mut buf = [0u8; 32];
    getrandom::getrandom(&mut buf).expect("OS random number generator unavailable");
    buf.iter().map(|b| format!("{b:02x}")).collect()
}

/// config.yaml, which the tray menu's Settings opens (ADR-017).
pub fn config_path() -> PathBuf {
    repo_root().join("config.yaml")
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

fn started_by_hand() -> Option<BackendInfo> {
    let (Ok(port), Ok(token)) = (std::env::var("SWIFT_BACKEND_PORT"), std::env::var("SWIFT_SESSION_TOKEN")) else {
        return None;
    };
    Some(BackendInfo { port: port.parse().unwrap_or(0), token })
}

/// A new start: nothing known about it yet, and news from older ones is ignored from now on.
fn begin(shared: &SharedBackend) -> u64 {
    let mut b = shared.lock().unwrap();
    b.generation += 1;
    b.info = None;
    b.ready_at = None;
    b.error = None;
    b.generation
}

/// Start `generation` said it is ready; false if it isn't the current start.
fn ready(shared: &SharedBackend, generation: u64, info: BackendInfo) -> bool {
    let mut b = shared.lock().unwrap();
    if b.generation != generation {
        return false;
    }
    b.info = Some(info);
    b.ready_at = Some(Instant::now());
    true
}

/// Start `generation` reported a problem; false if it isn't the current start.
fn failed(shared: &SharedBackend, generation: u64, problem: String) -> bool {
    let mut b = shared.lock().unwrap();
    if b.generation != generation {
        return false;
    }
    b.error = Some(problem);
    true
}

/// Start `generation`'s output closed: it has exited. The problem to report, if it is the current one.
fn exited(shared: &SharedBackend, generation: u64) -> Option<String> {
    let mut b = shared.lock().unwrap();
    if b.generation != generation {
        return None;
    }
    b.info = None;
    Some(b.error.get_or_insert_with(|| "the backend stopped unexpectedly".into()).clone())
}

pub fn start(app: &AppHandle, shared: SharedBackend) {
    launch(app, shared, false);
}

fn launch(app: &AppHandle, shared: SharedBackend, restarted: bool) {
    if let Some(info) = started_by_hand() {
        shared.lock().unwrap().info = Some(info);
        return;
    }
    let generation = begin(&shared);

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
        .env("SWIFT_RESTARTED", if restarted { "1" } else { "0" }) // logged, for the owner checks
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .creation_flags(CREATE_NO_WINDOW)
        .spawn();

    let mut child = match spawned {
        Ok(child) => child,
        Err(e) => {
            let msg = format!("could not start the backend ({}): {e}", python.display());
            if failed(&shared, generation, msg.clone()) {
                let _ = app.emit("backend-error", msg);
            }
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
                if ready(&shared, generation, BackendInfo { port, token: token.clone() }) {
                    let _ = app.emit("backend-ready", ());
                }
            } else if let Some(rest) = line.strip_prefix("SWIFT_BACKEND_ERROR ") {
                if failed(&shared, generation, rest.to_string()) {
                    let _ = app.emit("backend-error", rest.to_string());
                }
            } else {
                println!("[backend] {line}");
            }
        }
        // stdout closed: the backend has exited.
        if let Some(problem) = exited(&shared, generation) {
            let _ = app.emit("backend-error", problem);
        }
    });
}

/// Quit: ask the backend to exit, then end whatever is left of it.
pub fn stop(shared: &SharedBackend) {
    end(shared, QUIT_GRACE);
}

/// Restart Swift: end this backend and everything it started, then start a new one.
pub fn restart(app: &AppHandle, shared: SharedBackend) -> Result<(), String> {
    if started_by_hand().is_some() {
        return Err("Swift's engine was started by hand (SWIFT_BACKEND_PORT): restart it there.".into());
    }
    begin(&shared); // from here the old backend's output closing is old news
    end(&shared, RESTART_GRACE);
    eprintln!("[overlay] restarting the backend");
    launch(app, shared, true);
    Ok(())
}

/// Close the backend's stdin (it exits cleanly: the microphone, its runs), give it `grace`,
/// then end its job: anything still running in it, the backend or a Claude Code CLI, is
/// killed. Returns once the backend process is gone, so a new one never runs beside it.
fn end(shared: &SharedBackend, grace: Duration) {
    let (stdin, child, job) = {
        let mut b = shared.lock().unwrap();
        (b._stdin.take(), b.child.take(), b.job.take())
    };
    drop(stdin); // closing stdin asks the backend to exit cleanly
    let mut child = child;
    if let Some(c) = child.as_mut() {
        let until = Instant::now() + grace;
        while Instant::now() < until && !matches!(c.try_wait(), Ok(Some(_))) {
            std::thread::sleep(Duration::from_millis(50));
        }
    }
    if let Some(job) = job {
        unsafe {
            TerminateJobObject(job as HANDLE, 1);
            CloseHandle(job as HANDLE);
        }
    }
    if let Some(mut c) = child {
        let _ = c.kill(); // not in a job (assigning failed): the backend itself at least
        let _ = c.wait();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use windows_sys::Win32::System::Threading::{OpenProcess, WaitForSingleObject, PROCESS_SYNCHRONIZE};

    fn shared() -> SharedBackend {
        Arc::new(Mutex::new(Backend::default()))
    }

    fn info(port: u16) -> BackendInfo {
        BackendInfo { port, token: "t".into() }
    }

    #[test]
    fn a_restart_starts_clean_and_the_old_readers_news_is_ignored() {
        let s = shared();
        let old = begin(&s);
        assert!(ready(&s, old, info(4000)));
        let new = begin(&s); // Restart Swift
        assert!(s.lock().unwrap().info.is_none() && s.lock().unwrap().error.is_none());
        assert!(ready(&s, new, info(5000)));
        // The old backend's stdout closes after the new one is up: it mustn't take the new one down.
        assert_eq!(exited(&s, old), None);
        assert!(!ready(&s, old, info(4000)) && !failed(&s, old, "late".into()));
        assert_eq!(s.lock().unwrap().info.as_ref().map(|i| i.port), Some(5000));
        // The new one dying is news.
        assert!(exited(&s, new).is_some() && s.lock().unwrap().info.is_none());
    }

    #[test]
    fn ending_the_backend_ends_everything_in_its_job() {
        let s = shared();
        let job = kill_on_close_job().expect("a job object");
        // Ignores a closed stdin, like a hung backend (or a Claude Code CLI it left behind).
        let child = Command::new("ping")
            .args(["-n", "120", "127.0.0.1"])
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .creation_flags(CREATE_NO_WINDOW)
            .spawn()
            .expect("ping starts");
        let pid = child.id();
        unsafe {
            AssignProcessToJobObject(job as HANDLE, child.as_raw_handle() as HANDLE);
        }
        {
            let mut b = s.lock().unwrap();
            b.child = Some(child);
            b.job = Some(job);
        }
        let t0 = std::time::Instant::now();
        end(&s, std::time::Duration::from_millis(200));
        assert!(t0.elapsed() < std::time::Duration::from_secs(5));
        let b = s.lock().unwrap();
        assert!(b.child.is_none() && b.job.is_none());
        let gone = unsafe {
            let h = OpenProcess(PROCESS_SYNCHRONIZE, 0, pid);
            h.is_null() || {
                let done = WaitForSingleObject(h, 0) == 0; // WAIT_OBJECT_0: it has exited
                windows_sys::Win32::Foundation::CloseHandle(h);
                done
            }
        };
        assert!(gone, "the process is still running");
    }
}
