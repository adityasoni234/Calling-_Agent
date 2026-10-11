import type { InputHTMLAttributes } from "react";
import { useId } from "react";

interface FieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  error?: string;
  hint?: string;
}

export const CONTROL_CLASS =
  "mt-1.5 block w-full rounded-xl border-0 bg-white px-3.5 py-2.5 text-sm text-ink-900 shadow-card ring-1 ring-inset transition-shadow placeholder:text-ink-400 focus:ring-2 focus:ring-inset";

export function Field({
  label,
  error,
  hint,
  className = "",
  ...props
}: FieldProps) {
  const id = useId();
  const describedBy = error ? `${id}-error` : hint ? `${id}-hint` : undefined;

  return (
    <div className={className}>
      {label && (
        <label htmlFor={id} className="block text-xs font-medium text-ink-600">
          {label}
        </label>
      )}
      <input
        {...props}
        id={id}
        aria-invalid={Boolean(error)}
        aria-describedby={describedBy}
        className={`${CONTROL_CLASS} ${
          error
            ? "ring-red-300 focus:ring-red-500"
            : "ring-ink-200 focus:ring-brand-500"
        }`}
      />
      {error ? (
        <p id={`${id}-error`} className="mt-1.5 text-xs text-red-600">
          {error}
        </p>
      ) : hint ? (
        <p
          id={`${id}-hint`}
          className="mt-1.5 text-xs leading-relaxed text-ink-400"
        >
          {hint}
        </p>
      ) : null}
    </div>
  );
}
