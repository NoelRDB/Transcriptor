import { describe, expect, it } from "vitest";
import { activeSegmentIndex, followSegmentIndex, formatClock, formatSrtTime, formatVttTime } from "./time";

describe("time formatting", () => {
  it("formats player and subtitle times", () => {
    expect(formatClock(3_723_456)).toBe("01:02:03");
    expect(formatSrtTime(3_723_456)).toBe("01:02:03,456");
    expect(formatVttTime(3_723_456)).toBe("01:02:03.456");
  });

  it("never returns negative subtitle times", () => {
    expect(formatSrtTime(-20)).toBe("00:00:00,000");
  });
});

describe("activeSegmentIndex", () => {
  const segments = [{ startMs: 0, endMs: 1000 }, { startMs: 1300, endMs: 2200 }, { startMs: 3000, endMs: 4000 }];
  it("finds the active segment with a binary search", () => {
    expect(activeSegmentIndex(segments, 0)).toBe(0);
    expect(activeSegmentIndex(segments, 1900)).toBe(1);
    expect(activeSegmentIndex(segments, 3999)).toBe(2);
  });
  it("returns -1 in gaps and at an exclusive end", () => {
    expect(activeSegmentIndex(segments, 1100)).toBe(-1);
    expect(activeSegmentIndex(segments, 4000)).toBe(-1);
  });
});

describe("followSegmentIndex", () => {
  const segments = [{ startMs: 500, endMs: 1000 }, { startMs: 1300, endMs: 2200 }, { startMs: 3000, endMs: 4000 }];

  it("follows the active segment and advances across silence gaps", () => {
    expect(followSegmentIndex(segments, 700)).toBe(0);
    expect(followSegmentIndex(segments, 1100)).toBe(1);
    expect(followSegmentIndex(segments, 2500)).toBe(2);
  });

  it("stays on the first or last segment outside the transcript range", () => {
    expect(followSegmentIndex(segments, 0)).toBe(0);
    expect(followSegmentIndex(segments, 9000)).toBe(2);
    expect(followSegmentIndex([], 0)).toBe(-1);
  });
});
