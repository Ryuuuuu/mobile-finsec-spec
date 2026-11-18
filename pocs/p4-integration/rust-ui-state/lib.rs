//! GPUI-independent response gating, not a window or a transport client.
mod response_guard;
#[derive(Clone, Copy, PartialEq, Debug)]
pub enum Tab { Record, Check, Results }

pub struct Selection {
    pub project: String,
    pub generation: u64,
    pub run: Option<String>,
    pub tab: Tab,
}

impl Selection {
    pub fn select(&mut self, tab: Tab, run: Option<String>) -> Result<(), &'static str> {
        let next = self.generation.checked_add(1).ok_or("GENERATION_OVERFLOW")?;
        if next > 9_007_199_254_740_991 { return Err("GENERATION_OVERFLOW"); }
        self.generation = next;
        self.tab = tab;
        self.run = run;
        Ok(())
    }

    pub fn accepts(&self, contract: &str, project: &str, generation: u64, run: Option<&str>) -> bool {
        response_guard::accepts(&self.project, self.generation, self.run.as_deref(),
                                contract, project, generation, run)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn stale_response_and_tab_are_independent() {
        let mut s = Selection { project: "mock".into(), generation: 0, run: None, tab: Tab::Record };
        s.select(Tab::Results, Some("run-2".into())).unwrap();
        assert!(s.accepts("mock-ui.v1", "mock", 1, Some("run-2")));
        assert!(!s.accepts("mock-ui.v1", "mock", 0, Some("run-2")));
        assert!(!s.accepts("mock-ui.v1", "other", 1, Some("run-2")));
        assert!(!s.accepts("mock-ui.v1", "mock", 1, Some("run-1")));
        assert!(!s.accepts("mock-ui.v1", "mock", 1, None));
        assert_eq!(s.tab, Tab::Results);
        s.generation = 9_007_199_254_740_991;
        assert!(s.select(Tab::Check, None).is_err());
        assert_eq!(s.tab, Tab::Results);
    }
}
