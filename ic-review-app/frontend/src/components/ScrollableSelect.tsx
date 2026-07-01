import { useEffect, useRef, useState } from "react";

type Props = {
  value: string;
  options: readonly string[];
  onChange: (value: string) => void;
  disabled?: boolean;
  ariaLabel?: string;
};

export default function ScrollableSelect({ value, options, onChange, disabled, ariaLabel }: Props) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const selectedRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    function closeOnOutsideClick(event: MouseEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    }
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", closeOnOutsideClick);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("mousedown", closeOnOutsideClick);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, []);

  useEffect(() => {
    if (open) requestAnimationFrame(() => selectedRef.current?.scrollIntoView({ block: "nearest" }));
  }, [open]);

  return (
    <div className={`scroll-select${open ? " open" : ""}${disabled ? " disabled" : ""}`} ref={rootRef}>
      <button
        type="button"
        className="scroll-select-trigger"
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen((current) => !current)}
      >
        <span>{value}</span>
        <span className="scroll-select-chevron" aria-hidden="true" />
      </button>
      {open && (
        <div className="scroll-select-menu" role="listbox" aria-label={ariaLabel}>
          {options.map((option) => (
            <button
              type="button"
              role="option"
              aria-selected={option === value}
              className={`scroll-select-option${option === value ? " selected" : ""}`}
              key={option}
              ref={option === value ? selectedRef : undefined}
              onClick={() => {
                onChange(option);
                setOpen(false);
              }}
            >
              {option}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
