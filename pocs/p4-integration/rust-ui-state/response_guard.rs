//! Allocation-free shared response identity guard, usable by std and no_std.
pub fn accepts(expected_project: &str, expected_generation: u64, expected_run: Option<&str>,
               contract: &str, project: &str, generation: u64, run: Option<&str>) -> bool {
    contract == "mock-ui.v1" && project == expected_project && generation == expected_generation
        && match (expected_run, run) {
            (Some(expected), Some(actual)) => expected == actual,
            (Some(_), None) => false,
            _ => true,
        }
}
