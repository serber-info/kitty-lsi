//! Opt-in paging on an interactive terminal, without changing terminal modes.
use crate::{budget::Budget, options::Options};
use std::io::{self, IsTerminal, Read, Write};

pub struct Pager {
    pub size: Option<usize>,
}
impl Pager {
    pub fn new(opt: &Options) -> Self {
        Self {
            size: opt
                .page_size()
                .filter(|_| io::stdin().is_terminal() && io::stdout().is_terminal()),
        }
    }
    pub fn before(&self, index: usize, out: &mut impl Write, budget: &Budget) -> io::Result<()> {
        if index == 0 || self.size.is_none_or(|size| !index.is_multiple_of(size)) {
            return Ok(());
        }
        write!(out, "Press ENTER to continue...")?;
        out.flush()?;
        budget.excluding(|| {
            let mut input = io::stdin().lock();
            let mut byte = [0];
            loop {
                match input.read(&mut byte) {
                    // Like a closed output pipe, EOF ends the listing cleanly.
                    Ok(0) => {
                        return Err(io::Error::new(
                            io::ErrorKind::BrokenPipe,
                            "paging input closed",
                        ));
                    }
                    Ok(_) if byte[0] == b'\n' => return Ok(()),
                    Ok(_) => (),
                    Err(e) if e.kind() == io::ErrorKind::Interrupted => (),
                    Err(e) => return Err(e),
                }
            }
        })?;
        writeln!(out)
    }
}
