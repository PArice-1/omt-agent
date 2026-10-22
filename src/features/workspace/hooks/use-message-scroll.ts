"use client";
import { useLayoutEffect, useRef } from "react";
import type { MessageResponse } from "@/lib/omt-api/contracts";
import type { RunState } from "../model/types";

/** Follow explicit sends/results, but leave unrelated renders alone when reading older messages. */
export function useMessageScroll(messages: MessageResponse[], run?: RunState) {
  const root = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const following = useRef(true);
  const previous = useRef<{ messages: MessageResponse[]; phase?: RunState["phase"]; runId?: string; answer?: string } | null>(null);
  const phase = run?.phase;
  const runId = run?.runId;
  const answer = run?.answer;

  useLayoutEffect(() => {
    const prior = previous.current;
    const sending = phase === "sending" && prior?.phase !== "sending";
    const completed = phase === "completed" && (prior?.phase !== phase || prior.runId !== runId || prior.answer !== answer || prior.messages !== messages);
    if (!prior || sending || completed || following.current) {
      following.current = true;
      if (root.current) root.current.scrollTop = root.current.scrollHeight;
    }
    previous.current = { messages, phase, runId, answer };
  }, [messages, phase, runId, answer]);

  useLayoutEffect(() => {
    if (typeof ResizeObserver === "undefined") return;
    // Markdown wrapping, tool expansion and notice removal can change layout after render.
    const observer = new ResizeObserver(() => {
      if (following.current && root.current) root.current.scrollTop = root.current.scrollHeight;
    });
    if (root.current) observer.observe(root.current);
    if (content.current) observer.observe(content.current);
    return () => observer.disconnect();
  }, []);

  return { root, content, onScroll: () => {
    const node = root.current;
    if (node) following.current = node.scrollHeight - node.scrollTop - node.clientHeight < 140;
  } };
}
