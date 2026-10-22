"use client";
import { useEffect, useId, useRef } from "react";
import { X } from "lucide-react";

interface DialogProps {
  title: string;
  description?: string;
  onClose(): void;
  busy?: boolean;
  children: React.ReactNode;
}
export function Dialog({ title, description, onClose, busy, children }: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const id = useId();
  useEffect(() => {
    const dialog = ref.current;
    if (dialog && !dialog.open) {
      dialog.showModal();
      // React autoFocus may run before a native dialog enters the top layer.
      dialog.querySelector<HTMLInputElement>("input:not(:disabled)")?.focus();
    }
    return () => { dialog?.close(); };
  }, []);
  return <dialog ref={ref} className="dialog" aria-labelledby={id} aria-describedby={description ? id + "-description" : undefined}
    onCancel={(event) => { event.preventDefault(); if (!busy) onClose(); }}>
    <div className="dialog-heading">
      <h2 id={id}>{title}</h2>
      <button type="button" className="icon-button" aria-label="关闭弹窗" disabled={busy} onClick={onClose}><X size={19} /></button>
    </div>
    {description && <p id={id + "-description"} className="dialog-description">{description}</p>}
    {children}
  </dialog>;
}
