//! A tiny std-only HTTP/1.1 load generator.
//!
//! Usage:
//!     rustc -O benchmarks/loadgen.rs -o /tmp/loadgen
//!     /tmp/loadgen 127.0.0.1 8000 /json 20000 32
//!
//! Threads use persistent connections and parse enough of the response to
//! know where the body ends, so the measured throughput is not distorted by a
//! GIL-bound Python load client.

use std::env;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::TcpStream;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Barrier};
use std::thread;
use std::time::Instant;

fn read_response(reader: &mut BufReader<TcpStream>) -> Result<usize, ()> {
    let mut content_length = 0usize;
    let mut line = String::with_capacity(128);
    loop {
        line.clear();
        let read = reader.read_line(&mut line).map_err(|_| ())?;
        if read == 0 {
            return Err(());
        }
        if line == "\r\n" {
            break;
        }
        if let Some(value) = line
            .strip_prefix("content-length:")
            .or_else(|| line.strip_prefix("Content-Length:"))
        {
            content_length = value.trim().parse().map_err(|_| ())?;
        }
    }

    let mut remaining = content_length;
    let mut buffer = [0u8; 16 * 1024];
    while remaining > 0 {
        let chunk = remaining.min(buffer.len());
        let read = reader.read(&mut buffer[..chunk]).map_err(|_| ())?;
        if read == 0 {
            return Err(());
        }
        remaining -= read;
    }
    Ok(content_length)
}

fn worker(port: u16, path: &str, count: usize, barrier: &Barrier, errors: &AtomicUsize) {
    let request = format!(
        "GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: keep-alive\r\n\r\n"
    );

    let stream = match TcpStream::connect(("127.0.0.1", port)) {
        Ok(stream) => stream,
        Err(_) => {
            errors.fetch_add(count, Ordering::Relaxed);
            barrier.wait();
            return;
        }
    };
    let _ = stream.set_nodelay(true);
    let mut writer = stream;
    let mut reader = BufReader::with_capacity(64 * 1024, writer.try_clone().unwrap());

    barrier.wait();

    for _ in 0..count {
        if writer.write_all(request.as_bytes()).is_err() {
            errors.fetch_add(1, Ordering::Relaxed);
            return;
        }
        if read_response(&mut reader).is_err() {
            errors.fetch_add(1, Ordering::Relaxed);
            return;
        }
    }
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() != 6 {
        eprintln!("usage: loadgen <host> <port> <path> <requests> <concurrency>");
        std::process::exit(2);
    }
    let _host = &args[1];
    let port: u16 = args[2].parse().unwrap();
    let path = &args[3];
    let requests: usize = args[4].parse().unwrap();
    let concurrency: usize = args[5].parse().unwrap();
    let per_thread = (requests / concurrency).max(1);
    let total = per_thread * concurrency;

    let barrier = Arc::new(Barrier::new(concurrency + 1));
    let errors = Arc::new(AtomicUsize::new(0));

    let mut handles = Vec::with_capacity(concurrency);
    for _ in 0..concurrency {
        let barrier = barrier.clone();
        let errors = errors.clone();
        let path = path.clone();
        handles.push(thread::spawn(move || {
            worker(port, &path, per_thread, &barrier, &errors);
        }));
    }

    let started = Instant::now();
    barrier.wait();
    for handle in handles {
        handle.join().unwrap();
    }
    let elapsed = started.elapsed().as_secs_f64();

    println!(
        "{:.0} req/s  {:.3}s  {} requests  {} errors",
        total as f64 / elapsed,
        elapsed,
        total,
        errors.load(Ordering::Relaxed)
    );
}
