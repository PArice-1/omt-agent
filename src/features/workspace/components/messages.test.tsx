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
  it("keeps optional history reasoning independent and safely renders structured live tool content", () => {
    const { container } = render(<Messages messages={[{ role: "assistant", message_id: "old-m", reasoning: "历史独立思考", text: "历史正文", tool_calls: [] }]} run={{ phase: "failed", message: "本轮输入", items: [
      { kind: "assistant", id: "m", text: "当前正文", reasoning: "<script>untrusted reasoning</script>", completed: true },
      { kind: "tool", id: "t1", name: "read", input: null, deltas: [{ progress: 1 }], result: { html: "<img src=x onerror=alert(1)>" }, status: "error" },
      { kind: "tool", id: "t2", name: "read", deltas: [], result: false, status: "success" },
    ] }} />);
    expect(screen.getByText("历史独立思考").closest("details")).not.toHaveAttribute("open");
    expect(screen.getByText("历史正文")).toBeInTheDocument();
    expect(screen.getByText("<script>untrusted reasoning</script>")).toBeInTheDocument();
    expect(screen.getAllByText("read")).toHaveLength(2);
    expect(container.querySelectorAll("[data-tool-call-id]")).toHaveLength(2);
    expect(container.querySelector("script, img")).toBeNull();
    expect(screen.getByText("false")).toBeInTheDocument();
    expect(screen.getByText("null")).toBeInTheDocument();
  });
  it("does not render unsafe HTML, javascript links or remote images", () => {
    const { container } = render(<Messages messages={[{ role: "assistant", text: '<script>alert(1)</script>\n\n[bad](javascript:alert(1))\n\n![tracker](https://evil.test/pixel.png)\n\n**安全文本**', tool_calls: [] }]} />);
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector('a[href^="javascript:"]')).toBeNull();
    expect(screen.getByText("安全文本")).toBeInTheDocument();
  });
});
