mod budget;
mod cache;
mod errors;
mod graphics;
mod listing;
mod options;
mod pager;
mod preview;
mod render;
mod scan;
mod secure_fs;
mod terminal;
mod text;
mod worker;
use std::io;
fn run() -> io::Result<i32> {
    let options = options::Options::read();
    worker::limit(libc::RLIMIT_CORE, 0)?;
    worker::limit(libc::RLIMIT_NOFILE, 1024)?;
    worker::limit(libc::RLIMIT_AS, 1024 * 1024 * 1024)?;
    worker::limit(libc::RLIMIT_CPU, 60)?;
    let output = io::stdout();
    let budget = budget::Budget::new();
    let mut renderer = render::Renderer::new(&options, output.lock(), &budget);
    let mut errors = errors::Errors::new();
    scan::walk(
        &options,
        |heading, entries| renderer.section(heading, entries),
        &mut errors,
        &budget,
    )?;
    errors.append(&mut renderer.errors);
    for error in errors.iter() {
        eprintln!("lsi: {}", text::safe(error));
    }
    Ok(i32::from(!errors.is_empty()))
}
fn main() {
    if worker::entry() {
        return;
    }
    let code = match run() {
        Ok(code) => code,
        Err(e) if e.kind() == io::ErrorKind::BrokenPipe => 0,
        Err(e) => {
            eprintln!("lsi: {}", text::safe(&e.to_string()));
            1
        }
    };
    std::process::exit(code);
}
