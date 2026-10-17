use clap::{ArgAction, Parser, ValueEnum};
use std::path::PathBuf;

#[derive(Debug, Clone, Copy, Default, ValueEnum)]
pub enum Sort {
    #[default]
    Name,
    Time,
    Size,
    Extension,
    Version,
    None,
}

#[derive(Debug, Parser)]
#[command(name="kitty-lsi", bin_name="lsi", version=env!("CARGO_PKG_VERSION"),
          about="An ls with real image thumbnails inside Kitty.",
          disable_help_flag=true, args_override_self=true)]
pub struct Options {
    #[arg(long, action=ArgAction::Help)]
    pub help: Option<bool>,
    #[arg(short = 'l', help = "Long listing with metadata")]
    pub long: bool,
    #[arg(short = '1', help = "One thumbnail per row")]
    pub one: bool,
    #[arg(short = 'h', long, help = "Human-readable base-1024 sizes with -l")]
    pub human_readable: bool,
    #[arg(long, help = "Readable sizes in powers of 1000")]
    pub si: bool,
    #[arg(short = 'n', long, help = "Long format with numeric owner/group")]
    pub numeric_uid_gid: bool,
    #[arg(short = 'g', help = "Long format without owner")]
    pub no_owner: bool,
    #[arg(short = 'o', help = "Long format without group")]
    pub no_group: bool,
    #[arg(long, help = "Long format with full timestamp and timezone")]
    pub full_time: bool,
    #[arg(short = 'i', long, help = "Include inode numbers")]
    pub inode: bool,
    #[arg(
        short = 'F',
        long,
        overrides_with = "slash",
        help = "Append file-type indicators"
    )]
    pub classify: bool,
    #[arg(
        short = 'p',
        overrides_with = "classify",
        help = "Append / to directories"
    )]
    pub slash: bool,
    #[arg(short = 'r', long, help = "Reverse sort order")]
    pub reverse: bool,
    #[arg(short='t', overrides_with_all=["size_sort","extension_sort","version_sort","unsorted","sort"], help="Newest modification first")]
    pub time_sort: bool,
    #[arg(short='S', overrides_with_all=["time_sort","extension_sort","version_sort","unsorted","sort"], help="Largest size first")]
    pub size_sort: bool,
    #[arg(short='X', overrides_with_all=["time_sort","size_sort","version_sort","unsorted","sort"], help="Sort by extension")]
    pub extension_sort: bool,
    #[arg(short='v', overrides_with_all=["time_sort","size_sort","extension_sort","unsorted","sort"], help="Natural numeric order")]
    pub version_sort: bool,
    #[arg(short='U', overrides_with_all=["time_sort","size_sort","extension_sort","version_sort","sort"], help="Directory enumeration order")]
    pub unsorted: bool,
    #[arg(long, value_enum, overrides_with_all=["time_sort","size_sort","extension_sort","version_sort","unsorted"])]
    pub sort: Option<Sort>,
    #[arg(
        long,
        help = "Keep directories first even with an explicit --sort=name"
    )]
    pub group_directories_first: bool,
    #[arg(
        short = 'a',
        long,
        overrides_with = "almost_all",
        help = "Include hidden entries and . / .."
    )]
    pub all: bool,
    #[arg(
        short = 'A',
        long,
        overrides_with = "all",
        help = "Hidden entries without . / .."
    )]
    pub almost_all: bool,
    #[arg(short = 'd', long, help = "List directories themselves")]
    pub directory: bool,
    #[arg(
        short = 'R',
        long,
        help = "List subdirectories without following links"
    )]
    pub recursive: bool,
    #[arg(long, default_value_t=14, value_parser=clap::value_parser!(u16).range(4..=60), help="Thumbnail columns")]
    pub width: u16,
    #[arg(long, default_value_t=5, value_parser=clap::value_parser!(u16).range(2..=16), help="Thumbnail rows")]
    pub height: u16,
    #[arg(long, help = "Plain text, without graphics")]
    pub no_images: bool,
    pub paths: Vec<PathBuf>,
}
impl Options {
    pub fn read() -> Self {
        let mut result = Self::try_parse().unwrap_or_else(|e| {
            let code = e.exit_code();
            if e.use_stderr() {
                eprintln!("{}", crate::text::safe(&e.to_string()));
            } else {
                // Only static help/version output is allowed to contain newlines.
                print!("{e}");
            }
            std::process::exit(code);
        });
        let alias = std::env::args_os()
            .next()
            .and_then(|s| PathBuf::from(s).file_name().map(|s| s == "lli"))
            .unwrap_or(false);
        result.long |= alias
            || result.numeric_uid_gid
            || result.no_owner
            || result.no_group
            || result.full_time;
        if result.paths.is_empty() {
            result.paths.push(PathBuf::from("."));
        }
        result
    }
    pub fn order(&self) -> Sort {
        self.sort.unwrap_or(if self.time_sort {
            Sort::Time
        } else if self.size_sort {
            Sort::Size
        } else if self.extension_sort {
            Sort::Extension
        } else if self.version_sort {
            Sort::Version
        } else if self.unsorted {
            Sort::None
        } else {
            Sort::Name
        })
    }

    pub fn directories_first(&self) -> bool {
        self.group_directories_first
            || (!matches!(self.sort, Some(Sort::Name)) && !matches!(self.order(), Sort::None))
    }
}
