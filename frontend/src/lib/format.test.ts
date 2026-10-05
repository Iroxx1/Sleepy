import { describe, expect, it } from "vitest";
import { addDays, clock, dateDe, duration, fmtMetric, hm, num } from "./format";

describe("format", () => {
  it("formats numbers German style", () => {
    expect(num(1234.5, 1)).toBe("1.234,5");
    expect(num(null)).toBe("–");
    expect(num(Number.NaN)).toBe("–");
  });
  it("formats hours", () => {
    expect(hm(7.7)).toBe("7h 42m");
    expect(hm(undefined)).toBe("–");
  });
  it("uses device wall clock (UTC) for timestamps", () => {
    // 2026-09-01 23:05:07 wall clock encoded as UTC milliseconds
    const ms = Date.UTC(2026, 8, 1, 23, 5, 7);
    expect(clock(ms)).toBe("23:05");
    expect(clock(ms, true)).toBe("23:05:07");
  });
  it("handles dates", () => {
    expect(dateDe("2026-10-05")).toBe("05.10.2026");
    expect(addDays("2026-12-31", 1)).toBe("2027-01-01");
    expect(duration(75)).toBe("1:15 min");
    expect(fmtMetric(2.5, "/h", 1)).toBe("2,5 /h");
    expect(fmtMetric(1.5, "h", 1)).toBe("1h 30m");
  });
});

import { explain } from "./glossary";
describe("glossary", () => {
  it("explains abbreviations", () => {
    expect(explain("AHI")).toContain("Apnoe-Hypopnoe-Index");
    expect(explain("CAI")).toContain("Zentral");
    expect(explain("Völlig unbekannt")).toBeUndefined();
  });
});
