import { describe, expect, it } from "vitest";
import { formatTimestamp, sessionTitle, validateMessage } from "./format";

describe("display and input rules", () => {
  it("uses title fallback only for display", () => {
    expect(sessionTitle(null)).toBe("新对话");
    expect(sessionTitle("  ")).toBe("新对话");
    expect(sessionTitle("  标题  ")).toBe("  标题  ");
  });
  it("parses the documented timestamp explicitly as UTC", () => {
    const expected = new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date("2026-06-01T08:00:00Z"));
    expect(formatTimestamp("2026-06-01 08:00:00")).toBe(expected);
    expect(formatTimestamp("unexpected")).toBe("unexpected");
  });
  it("counts Unicode code points and preserves valid whitespace", () => {
    expect(validateMessage("😀".repeat(32000))).toBeNull();
    expect(validateMessage("😀".repeat(32001))).toContain("32000");
    expect(validateMessage("  hello\n")).toBeNull();
    expect(validateMessage(" \n")).not.toBeNull();
    expect(validateMessage("\u0000")).not.toBeNull();
  });
});
