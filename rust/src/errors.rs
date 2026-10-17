//! Bound diagnostics even for hostile trees.
#[derive(Default)]
pub struct Errors(Vec<String>);
impl Errors {
    pub fn new() -> Self {
        Self::default()
    }
    pub fn push(&mut self, message: String) {
        if self.0.len() < 100 {
            self.0.push(message);
        } else if self.0.len() == 100 {
            self.0.push("further errors omitted".into());
        }
    }
    pub fn append(&mut self, other: &mut Self) {
        for message in other.0.drain(..) {
            self.push(message);
        }
    }
}
impl std::ops::Deref for Errors {
    type Target = [String];
    fn deref(&self) -> &[String] {
        &self.0
    }
}
