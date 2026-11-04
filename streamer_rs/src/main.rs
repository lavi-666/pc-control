use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use image::codecs::jpeg::JpegEncoder;
use image::ExtendedColorType;
use scrap::{Capturer, Display};
use serde::Serialize;
use std::collections::VecDeque;
use std::ffi::OsStr;
use std::io::Write;
use std::net::SocketAddr;
use std::os::windows::ffi::OsStrExt;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};
use tiny_http::{Header, Response, Server, StatusCode};

#[link(name = "user32")]
extern "system" {
    fn OpenDesktopW(
        lpszDesktop: *const u16,
        dwFlags: u32,
        fInherit: i32,
        dwDesiredAccess: u32,
    ) -> *mut std::ffi::c_void;
    fn SetThreadDesktop(hDesktop: *mut std::ffi::c_void) -> i32;
    fn CloseDesktop(hDesktop: *mut std::ffi::c_void) -> i32;
}

thread_local! {
    static DESKTOP_ATTACHED: std::cell::Cell<bool> = const { std::cell::Cell::new(false) };
}

fn attach_desktop() {
    DESKTOP_ATTACHED.with(|attached| {
        if attached.get() {
            return;
        }
        unsafe {
            let name: Vec<u16> = OsStr::new("Default")
                .encode_wide()
                .chain(std::iter::once(0))
                .collect();
            let desk = OpenDesktopW(name.as_ptr(), 0, 0, 0x01FF);
            if !desk.is_null() {
                if SetThreadDesktop(desk) != 0 {
                    attached.set(true);
                } else {
                    let _ = CloseDesktop(desk);
                }
            }
        }
    });
}

#[derive(Serialize)]
struct HealthResponse {
    status: &'static str,
    service: &'static str,
    version: &'static str,
    monitors: usize,
    sample_rate: u32,
}

#[derive(Clone)]
struct AudioBroadcaster {
    buffer: Arc<Mutex<VecDeque<i16>>>,
    sample_rate: u32,
    channels: u16,
}

impl AudioBroadcaster {
    fn new(sample_rate: u32, channels: u16) -> Self {
        Self {
            buffer: Arc::new(Mutex::new(VecDeque::with_capacity(sample_rate as usize * 2))),
            sample_rate,
            channels,
        }
    }

    fn push_samples(&self, samples: &[f32]) {
        let mut buf = match self.buffer.lock() {
            Ok(b) => b,
            Err(_) => return,
        };
        // Keep max 0.5s of audio to guarantee minimal latency
        let max_samples = (self.sample_rate as usize * self.channels as usize) / 2;
        for &s in samples {
            let clamped = s.max(-1.0).min(1.0);
            let pcm = (clamped * 32767.0) as i16;
            buf.push_back(pcm);
        }
        while buf.len() > max_samples {
            buf.pop_front();
        }
    }

    fn get_chunk(&self, count: usize) -> Vec<i16> {
        let mut buf = match self.buffer.lock() {
            Ok(b) => b,
            Err(_) => return Vec::new(),
        };
        let take = count.min(buf.len());
        let mut out = Vec::with_capacity(take);
        for _ in 0..take {
            if let Some(s) = buf.pop_front() {
                out.push(s);
            }
        }
        out
    }
}

fn start_loopback_recorder(broadcaster: AudioBroadcaster, running: Arc<AtomicBool>) {
    thread::spawn(move || {
        let host = cpal::default_host();
        let device = match host.default_output_device() {
            Some(d) => d,
            None => {
                eprintln!("[RustStreamer] No default output device for loopback");
                return;
            }
        };

        let config = match device.default_output_config() {
            Ok(c) => c,
            Err(e) => {
                eprintln!("[RustStreamer] Failed to get output config: {:?}", e);
                return;
            }
        };

        let stream_config: cpal::StreamConfig = config.into();
        let bc = broadcaster.clone();

        let stream = match device.build_input_stream(
            &stream_config,
            move |data: &[f32], _| {
                bc.push_samples(data);
            },
            move |err| {
                eprintln!("[RustStreamer] Loopback audio error: {:?}", err);
            },
            None,
        ) {
            Ok(s) => s,
            Err(e) => {
                eprintln!("[RustStreamer] Build loopback stream error: {:?}", e);
                return;
            }
        };

        if let Err(e) = stream.play() {
            eprintln!("[RustStreamer] Start loopback audio stream error: {:?}", e);
            return;
        }

        println!("[RustStreamer] WASAPI Loopback audio capture active (48 kHz Stereo)");
        while running.load(Ordering::Relaxed) {
            thread::sleep(Duration::from_millis(100));
        }
    });
}

fn start_mic_recorder(broadcaster: AudioBroadcaster, running: Arc<AtomicBool>) {
    thread::spawn(move || {
        let host = cpal::default_host();
        let device = match host.default_input_device() {
            Some(d) => d,
            None => {
                eprintln!("[RustStreamer] No default microphone found");
                return;
            }
        };

        let config = match device.default_input_config() {
            Ok(c) => c,
            Err(e) => {
                eprintln!("[RustStreamer] Failed to get mic config: {:?}", e);
                return;
            }
        };

        let stream_config: cpal::StreamConfig = config.clone().into();
        let in_channels = stream_config.channels;
        let sample_format = config.sample_format();
        let bc = broadcaster.clone();

        let stream_res = match sample_format {
            cpal::SampleFormat::F32 => {
                let bc = bc.clone();
                device.build_input_stream(
                    &stream_config,
                    move |data: &[f32], _| {
                        if in_channels == 1 {
                            let mut stereo = Vec::with_capacity(data.len() * 2);
                            for &s in data {
                                stereo.push(s);
                                stereo.push(s);
                            }
                            bc.push_samples(&stereo);
                        } else {
                            bc.push_samples(data);
                        }
                    },
                    move |err| {
                        eprintln!("[RustStreamer] Mic audio error: {:?}", err);
                    },
                    None,
                )
            }
            cpal::SampleFormat::I16 => {
                let bc = bc.clone();
                device.build_input_stream(
                    &stream_config,
                    move |data: &[i16], _| {
                        let cap = if in_channels == 1 { data.len() * 2 } else { data.len() };
                        let mut stereo = Vec::with_capacity(cap);
                        for &s in data {
                            let f = (s as f32) / 32768.0;
                            if in_channels == 1 {
                                stereo.push(f);
                                stereo.push(f);
                            } else {
                                stereo.push(f);
                            }
                        }
                        bc.push_samples(&stereo);
                    },
                    move |err| {
                        eprintln!("[RustStreamer] Mic audio error: {:?}", err);
                    },
                    None,
                )
            }
            sample_fmt => {
                eprintln!("[RustStreamer] Unsupported mic sample format: {:?}", sample_fmt);
                return;
            }
        };

        let stream = match stream_res {
            Ok(s) => s,
            Err(e) => {
                eprintln!("[RustStreamer] Build mic stream error: {:?}", e);
                return;
            }
        };

        if let Err(e) = stream.play() {
            eprintln!("[RustStreamer] Start mic stream error: {:?}", e);
            return;
        }

        println!("[RustStreamer] WASAPI Microphone capture active");
        while running.load(Ordering::Relaxed) {
            thread::sleep(Duration::from_millis(100));
        }
    });
}

fn init_capturer(monitor_idx: usize) -> Result<(Capturer, u32, u32), String> {
    attach_desktop();
    let displays = Display::all().map_err(|e| format!("Failed to enumerate displays: {:?}", e))?;
    if displays.is_empty() {
        return Err("No displays found".into());
    }

    let disp_idx = if monitor_idx > 0 && monitor_idx <= displays.len() {
        monitor_idx - 1
    } else {
        0
    };

    let display = displays
        .into_iter()
        .nth(disp_idx)
        .ok_or_else(|| "Display index out of bounds".to_string())?;

    let orig_w = display.width() as u32;
    let orig_h = display.height() as u32;

    let capturer = Capturer::new(display).map_err(|e| format!("Capturer init error: {:?}", e))?;
    Ok((capturer, orig_w, orig_h))
}

fn capture_from_capturer(
    capturer: &mut Capturer,
    orig_w: u32,
    orig_h: u32,
    target_height: u32,
    quality: u8,
) -> Result<Vec<u8>, String> {
    let mut frame_data = Vec::new();
    let start = Instant::now();
    while start.elapsed() < Duration::from_millis(150) {
        match capturer.frame() {
            Ok(f) => {
                frame_data = f.to_vec();
                break;
            }
            Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                thread::sleep(Duration::from_millis(2));
            }
            Err(e) => return Err(format!("Frame capture error: {:?}", e)),
        }
    }

    if frame_data.is_empty() {
        return Err("Timeout waiting for screen frame".into());
    }

    let row_stride = if orig_h > 0 {
        (frame_data.len() / (orig_h as usize)).max((orig_w as usize) * 4)
    } else {
        (orig_w as usize) * 4
    };

    let (out_w, out_h, rgb) = if target_height == 0 || target_height == orig_h {
        // Native / Джерело: 1:1 pixel representation without downscaling
        let mut rgb = vec![0u8; (orig_w * orig_h * 3) as usize];
        for y in 0..(orig_h as usize) {
            let row_start = y * row_stride;
            let dst_row = y * (orig_w as usize) * 3;
            for x in 0..(orig_w as usize) {
                let src_idx = row_start + x * 4;
                let dst_idx = dst_row + x * 3;
                if src_idx + 2 < frame_data.len() && dst_idx + 2 < rgb.len() {
                    rgb[dst_idx] = frame_data[src_idx + 2]; // R
                    rgb[dst_idx + 1] = frame_data[src_idx + 1]; // G
                    rgb[dst_idx + 2] = frame_data[src_idx]; // B
                }
            }
        }
        (orig_w, orig_h, rgb)
    } else {
        // Scaled resolution (e.g. 720p or 1080p)
        let out_h = target_height;
        let out_w = ((orig_w as f32 * (out_h as f32 / orig_h as f32)).round() as u32 / 2) * 2;
        let mut rgb = vec![0u8; (out_w * out_h * 3) as usize];

        let x_ratio = orig_w as f32 / out_w as f32;
        let y_ratio = orig_h as f32 / out_h as f32;

        for y in 0..out_h {
            let orig_y = ((y as f32 * y_ratio) as usize).min((orig_h as usize).saturating_sub(1));
            let row_start = orig_y * row_stride;
            for x in 0..out_w {
                let orig_x = ((x as f32 * x_ratio) as usize).min((orig_w as usize).saturating_sub(1));
                let src_idx = row_start + orig_x * 4;
                let dst_idx = (y as usize * out_w as usize + x as usize) * 3;
                if src_idx + 2 < frame_data.len() && dst_idx + 2 < rgb.len() {
                    rgb[dst_idx] = frame_data[src_idx + 2]; // R
                    rgb[dst_idx + 1] = frame_data[src_idx + 1]; // G
                    rgb[dst_idx + 2] = frame_data[src_idx]; // B
                }
            }
        }
        (out_w, out_h, rgb)
    };

    let mut out_jpg = Vec::new();
    let q = quality.max(10).min(95);
    let mut encoder = JpegEncoder::new_with_quality(&mut out_jpg, q);
    encoder
        .encode(&rgb, out_w, out_h, ExtendedColorType::Rgb8)
        .map_err(|e| format!("JPEG encode error: {:?}", e))?;

    Ok(out_jpg)
}

fn capture_frame_jpeg(
    monitor_idx: usize,
    target_height: u32,
    quality: u8,
) -> Result<Vec<u8>, String> {
    let (mut capturer, orig_w, orig_h) = init_capturer(monitor_idx)?;
    capture_from_capturer(&mut capturer, orig_w, orig_h, target_height, quality)
}

fn create_wav_header(sample_rate: u32, channels: u16) -> Vec<u8> {
    let mut h = Vec::with_capacity(44);
    h.extend_from_slice(b"RIFF");
    h.extend_from_slice(&0x7fffffffu32.to_le_bytes()); // Indeterminate streaming length
    h.extend_from_slice(b"WAVE");
    h.extend_from_slice(b"fmt ");
    h.extend_from_slice(&16u32.to_le_bytes()); // Subchunk1Size
    h.extend_from_slice(&1u16.to_le_bytes()); // PCM format
    h.extend_from_slice(&channels.to_le_bytes());
    h.extend_from_slice(&sample_rate.to_le_bytes());
    let byte_rate = sample_rate * channels as u32 * 2;
    h.extend_from_slice(&byte_rate.to_le_bytes());
    let block_align = channels * 2;
    h.extend_from_slice(&block_align.to_le_bytes());
    h.extend_from_slice(&16u16.to_le_bytes()); // BitsPerSample
    h.extend_from_slice(b"data");
    h.extend_from_slice(&0x7fffffffu32.to_le_bytes()); // Streaming data length
    h
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let mut port = 5051;
    for i in 1..args.len() {
        if args[i] == "--port" && i + 1 < args.len() {
            if let Ok(p) = args[i + 1].parse() {
                port = p;
            }
        }
    }

    let addr: SocketAddr = format!("127.0.0.1:{}", port).parse().unwrap();
    let server = match Server::http(addr) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("[RustStreamer] Failed to bind to {}: {:?}", addr, e);
            std::process::exit(1);
        }
    };

    println!("[RustStreamer] Service started on http://{}", addr);

    let running = Arc::new(AtomicBool::new(true));
    let loopback_bc = AudioBroadcaster::new(48000, 2);
    let mic_bc = AudioBroadcaster::new(48000, 2);

    start_loopback_recorder(loopback_bc.clone(), running.clone());
    start_mic_recorder(mic_bc.clone(), running.clone());

    let server = Arc::new(server);

    for request in server.incoming_requests() {
        let url = request.url().to_string();
        let loopback_bc = loopback_bc.clone();
        let mic_bc = mic_bc.clone();

        thread::spawn(move || {
            let path = url.split('?').next().unwrap_or("/");

            match path {
                "/health" => {
                    let displays = Display::all().unwrap_or_default();
                    let health = HealthResponse {
                        status: "online",
                        service: "pc_control_rust_streamer",
                        version: "1.0.0",
                        monitors: displays.len(),
                        sample_rate: 48000,
                    };
                    let json = serde_json::to_string(&health).unwrap_or_default();
                    let response = Response::from_string(json).with_header(
                        Header::from_bytes(&b"Content-Type"[..], &b"application/json"[..]).unwrap(),
                    );
                    let _ = request.respond(response);
                }
                "/audio/stream" | "/audio/loopback" => {
                    let header_bytes = create_wav_header(48000, 2);
                    let mut writer = match request.into_writer() {
                        writer => writer,
                    };

                    let http_res = "HTTP/1.1 200 OK\r\nContent-Type: audio/wav\r\nCache-Control: no-cache, no-store\r\nConnection: close\r\n\r\n";
                    if writer.write_all(http_res.as_bytes()).is_err() {
                        return;
                    }
                    if writer.write_all(&header_bytes).is_err() {
                        return;
                    }

                    // Stream 48 kHz stereo PCM chunks (~20ms per chunk = 960 stereo samples = 1920 samples)
                    let chunk_samples = 1920;
                    loop {
                        let samples = loopback_bc.get_chunk(chunk_samples);
                        if samples.is_empty() {
                            thread::sleep(Duration::from_millis(5));
                            continue;
                        }
                        let mut bytes = Vec::with_capacity(samples.len() * 2);
                        for s in samples {
                            bytes.extend_from_slice(&s.to_le_bytes());
                        }
                        if writer.write_all(&bytes).is_err() {
                            break;
                        }
                        thread::sleep(Duration::from_millis(15));
                    }
                }
                "/audio/mic" => {
                    let header_bytes = create_wav_header(48000, 2);
                    let mut writer = match request.into_writer() {
                        writer => writer,
                    };

                    let http_res = "HTTP/1.1 200 OK\r\nContent-Type: audio/wav\r\nCache-Control: no-cache, no-store\r\nConnection: close\r\n\r\n";
                    if writer.write_all(http_res.as_bytes()).is_err() {
                        return;
                    }
                    if writer.write_all(&header_bytes).is_err() {
                        return;
                    }

                    let chunk_samples = 1920;
                    loop {
                        let samples = mic_bc.get_chunk(chunk_samples);
                        if samples.is_empty() {
                            thread::sleep(Duration::from_millis(5));
                            continue;
                        }
                        let mut bytes = Vec::with_capacity(samples.len() * 2);
                        for s in samples {
                            bytes.extend_from_slice(&s.to_le_bytes());
                        }
                        if writer.write_all(&bytes).is_err() {
                            break;
                        }
                        thread::sleep(Duration::from_millis(15));
                    }
                }
                "/screen/frame" => {
                    let mut mon = 1;
                    let mut h = 1080;
                    let mut q = 75;

                    if let Some(query) = url.split('?').nth(1) {
                        for pair in query.split('&') {
                            let mut parts = pair.split('=');
                            if let (Some(k), Some(v)) = (parts.next(), parts.next()) {
                                match k {
                                    "monitor" => mon = v.parse().unwrap_or(1),
                                    "height" => h = v.parse().unwrap_or(1080),
                                    "quality" => q = v.parse().unwrap_or(75),
                                    _ => {}
                                }
                            }
                        }
                    }

                    match capture_frame_jpeg(mon, h, q) {
                        Ok(jpeg) => {
                            let response = Response::from_data(jpeg).with_header(
                                Header::from_bytes(&b"Content-Type"[..], &b"image/jpeg"[..])
                                    .unwrap(),
                            );
                            let _ = request.respond(response);
                        }
                        Err(e) => {
                            let response = Response::from_string(format!("Error: {}", e))
                                .with_status_code(StatusCode(500));
                            let _ = request.respond(response);
                        }
                    }
                }
                "/screen/mjpeg" => {
                    let mut mon = 1;
                    let mut h = 1080;
                    let mut fps = 60;
                    let mut q = 70;

                    if let Some(query) = url.split('?').nth(1) {
                        for pair in query.split('&') {
                            let mut parts = pair.split('=');
                            if let (Some(k), Some(v)) = (parts.next(), parts.next()) {
                                match k {
                                    "monitor" => mon = v.parse().unwrap_or(1),
                                    "height" => h = v.parse().unwrap_or(1080),
                                    "fps" => fps = v.parse().unwrap_or(60),
                                    "quality" => q = v.parse().unwrap_or(70),
                                    _ => {}
                                }
                            }
                        }
                    }

                    fps = fps.max(10).min(60);
                    let frame_interval = Duration::from_micros(1_000_000 / fps as u64);

                    let mut writer = match request.into_writer() {
                        writer => writer,
                    };

                    let init_header = "HTTP/1.1 200 OK\r\nContent-Type: multipart/x-mixed-replace; boundary=frame\r\nCache-Control: no-cache, no-store\r\nConnection: close\r\n\r\n";
                    if writer.write_all(init_header.as_bytes()).is_err() {
                        return;
                    }

                    let mut cap_state = init_capturer(mon).ok();

                    loop {
                        let t0 = Instant::now();
                        if cap_state.is_none() {
                            cap_state = init_capturer(mon).ok();
                        }
                        let jpeg_res = if let Some((ref mut cap, orig_w, orig_h)) = cap_state {
                            match capture_from_capturer(cap, orig_w, orig_h, h, q) {
                                Ok(jpg) => Ok(jpg),
                                Err(e) => {
                                    if !e.contains("Timeout") {
                                        cap_state = None;
                                    }
                                    Err(e)
                                }
                            }
                        } else {
                            Err("Capturer not initialized".into())
                        };
                        if let Ok(jpeg) = jpeg_res {
                            let boundary_header = format!(
                                "--frame\r\nContent-Type: image/jpeg\r\nContent-Length: {}\r\n\r\n",
                                jpeg.len()
                            );
                            if writer.write_all(boundary_header.as_bytes()).is_err() {
                                break;
                            }
                            if writer.write_all(&jpeg).is_err() {
                                break;
                            }
                            if writer.write_all(b"\r\n").is_err() {
                                break;
                            }
                        }

                        let elapsed = t0.elapsed();
                        if elapsed < frame_interval {
                            thread::sleep(frame_interval - elapsed);
                        }
                    }
                }
                _ => {
                    let response =
                        Response::from_string("Not Found").with_status_code(StatusCode(404));
                    let _ = request.respond(response);
                }
            }
        });
    }
}
