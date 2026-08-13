import { useEffect, useRef } from 'react';

export interface ShortcutEntry {
  keys: string;
  description: string;
}

export interface ShortcutsHelpProps {
  open: boolean;
  shortcuts: ShortcutEntry[];
  onClose(): void;
}

export function ShortcutsHelp({ open, shortcuts, onClose }: ShortcutsHelpProps) {
  const previouslyFocusedRef = useRef<HTMLElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (open) {
      previouslyFocusedRef.current =
        document.activeElement instanceof HTMLElement
          ? document.activeElement
          : null;
      closeButtonRef.current?.focus();
    } else {
      previouslyFocusedRef.current?.focus();
    }
  }, [open]);

  useEffect(() => {
    if (!open) {
      return undefined;
    }
    const handleKeyDown = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose]);

  if (!open) {
    return null;
  }

  return (
    <div
      className="shortcuts-help-overlay"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <div
        className="shortcuts-help"
        role="dialog"
        aria-modal="true"
        aria-label="Keyboard shortcuts"
      >
        <div className="shortcuts-help__header">
          <h2>Keyboard shortcuts</h2>
          <button
            ref={closeButtonRef}
            type="button"
            className="shortcuts-help__close"
            aria-label="Close keyboard shortcuts"
            onClick={onClose}
          >
            ✕
          </button>
        </div>
        <dl className="shortcuts-help__list">
          {shortcuts.map((shortcut) => (
            <div className="shortcuts-help__row" key={shortcut.keys}>
              <dt className="shortcuts-help__keys">{shortcut.keys}</dt>
              <dd className="shortcuts-help__description">
                {shortcut.description}
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}
