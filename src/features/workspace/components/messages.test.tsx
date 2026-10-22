import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Messages } from "./messages";
import { history } from "../../../../tests/fixtures";

describe("message rendering", () => {
  it("retains textless tool calls and links results by call ID", () => {
    render(<Messages messages={history} />);
    expect(screen.getByText("工具调用")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "查看对应调用", hidden: true });
    expect(link.getAttribute("href")).toContain("call-1-0");
    expect(screen.getByText("查看工具结果")).toBeInTheDocument();
  });
  it("keeps unknown tools without inventing pairings", () => {
    render(<Messages messages={[{ role: "tool", text: "<script>alert(1)</script>", tool_calls: [] }]} />);
    expect(screen.getByText("<script>alert(1)</script>")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "查看对应调用", hidden: true })).not.toBeInTheDocument();
    expect(document.querySelector("script")).toBeNull();
  });
  it("does not render unsafe HTML, javascript links or remote images", () => {
    const { container } = render(<Messages messages={[{ role: "assistant", text: '<script>alert(1)</script>\n\n[bad](javascript:alert(1))\n\n![tracker](https://evil.test/pixel.png)\n\n**安全文本**', tool_calls: [] }]} />);
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector('a[href^="javascript:"]')).toBeNull();
    expect(screen.getByText("安全文本")).toBeInTheDocument();
  });
});
