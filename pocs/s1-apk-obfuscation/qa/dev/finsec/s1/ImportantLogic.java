package dev.finsec.s1;

public final class ImportantLogic {
    private final int maximumDemoUnits;
    public ImportantLogic(int maximumDemoUnits) { this.maximumDemoUnits = maximumDemoUnits; }
    public String classifyDemoUnits(int requestedUnits) {
        if (requestedUnits <= 0) return "QA_INVALID";
        if (requestedUnits > maximumDemoUnits) return "QA_LIMIT";
        return "QA_ACCEPTED";
    }
}
