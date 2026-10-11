import type {
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react";
import { useId } from "react";

const CONTROL =
  "mt-1.5 block w-full rounded-xl border-0 bg-white px-3.5 py-2.5 text-sm text-ink-900 shadow-card ring-1 ring-inset ring-ink-200 transition-shadow placeholder:text-ink-400 focus:ring-2 focus:ring-inset focus:ring-brand-500";

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label: string;
  children: ReactNode;
  hint?: string;
}

export function Select({
  label,
  hint,
  children,
  className = "",
  ...props
}: SelectProps) {
  const id = useId();
  return (
    <div className={className}>
      <label htmlFor={id} className="block text-xs font-medium text-ink-600">
        {label}
      </label>
      <select id={id} {...props} className={CONTROL}>
        {children}
      </select>
      {hint && (
        <p className="mt-1.5 text-xs leading-relaxed text-ink-400">{hint}</p>
      )}
    </div>
  );
}

interface TextAreaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label: string;
  hint?: string;
}

export function TextArea({
  label,
  hint,
  className = "",
  rows = 3,
  ...props
}: TextAreaProps) {
  const id = useId();
  return (
    <div className={className}>
      <label htmlFor={id} className="block text-xs font-medium text-ink-600">
        {label}
      </label>
      <textarea id={id} rows={rows} {...props} className={CONTROL} />
      {hint && (
        <p className="mt-1.5 text-xs leading-relaxed text-ink-400">{hint}</p>
      )}
    </div>
  );
}

/** Edits a string[] as one-per-line text: far less fiddly than a row editor. */
export function ListField({
  label,
  value,
  onChange,
  hint,
  rows = 3,
}: {
  label: string;
  value: string[];
  onChange: (next: string[]) => void;
  hint?: string;
  rows?: number;
}) {
  return (
    <TextArea
      label={label}
      hint={hint ?? "One per line."}
      rows={rows}
      value={value.join("\n")}
      onChange={(event) =>
        onChange(
          event.target.value
            .split("\n")
            .map((line) => line.trim())
            .filter(Boolean),
        )
      }
    />
  );
}
