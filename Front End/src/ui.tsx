import { useEffect, useRef, useState } from "react";
import { AlertCircle, LoaderCircle, X } from "lucide-react";
import type { ReactNode } from "react";
import { errorGuidance } from "./errors";

export function ErrorNotice({ message }: { message: string }) {
  if (!message) return null;
  const guidance = errorGuidance(message);
  return (
    <div className="notice error" role="alert">
      <AlertCircle size={16} />
      <div>
        <strong>{guidance.title}</strong>
        <p>{guidance.body}</p>
        {guidance.detail && (
          <details>
            <summary>Details for support</summary>
            <small>{guidance.detail}</small>
          </details>
        )}
      </div>
    </div>
  );
}
export function Busy({ label }: { label: string }) {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const start = Date.now();
    const timer = setInterval(
      () => setSeconds(Math.floor((Date.now() - start) / 1000)),
      1000,
    );
    return () => clearInterval(timer);
  }, []);
  return (
    <div className="busy" role="status">
      <LoaderCircle className="spin" size={17} />
      <div>
        <strong>{label}</strong>
        <small>{seconds}s elapsed</small>
      </div>
    </div>
  );
}
export function Modal({
  title,
  children,
  onClose,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    const previous = document.activeElement as HTMLElement | null;
    dialog?.showModal();
    return () => {
      dialog?.close();
      previous?.focus();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      className="modal"
      aria-label={title}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
    >
      <div className="modal-heading">
        <h2>{title}</h2>
        <button
          className="icon-button"
          aria-label="Close dialog"
          onClick={onClose}
        >
          <X size={18} />
        </button>
      </div>
      {children}
    </dialog>
  );
}
export function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="form-field">
      <span>{label}</span>
      {children}
    </label>
  );
}
export function loadLocal<T>(
  key: string,
  fallback: T,
  valid: (value: unknown) => value is T,
): T {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(key) ?? "null");
    return valid(value) ? value : fallback;
  } catch {
    return fallback;
  }
}
