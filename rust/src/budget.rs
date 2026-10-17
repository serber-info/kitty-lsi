//! Shared processing deadline; time spent waiting for ENTER is not processing.
use std::{
    cell::Cell,
    io,
    time::{Duration, Instant},
};

pub struct Budget {
    started: Instant,
    paused: Cell<Duration>,
}
impl Budget {
    pub fn new() -> Self {
        Self {
            started: Instant::now(),
            paused: Cell::new(Duration::ZERO),
        }
    }
    pub fn check(&self) -> io::Result<()> {
        if self.started.elapsed().saturating_sub(self.paused.get()) >= Duration::from_secs(120) {
            Err(io::Error::other("listing exceeded 120 second deadline"))
        } else {
            Ok(())
        }
    }
    pub fn excluding<T>(&self, operation: impl FnOnce() -> io::Result<T>) -> io::Result<T> {
        let started = Instant::now();
        let result = operation();
        self.paused.set(self.paused.get() + started.elapsed());
        result
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_user_wait_time_is_excluded_from_the_deadline() {
        let budget = Budget {
            started: Instant::now() - Duration::from_secs(121),
            paused: Cell::new(Duration::ZERO),
        };
        assert!(budget.check().is_err());
        budget.paused.set(Duration::from_secs(120));
        assert!(budget.check().is_ok());
        budget.paused.set(Duration::from_secs(1));
        assert!(budget.check().is_err());
    }
}
