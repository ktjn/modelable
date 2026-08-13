import { useEffect, useMemo, useRef, useState } from 'react';

export interface CommandPaletteCommand {
  id: string;
  group: string;
  label: string;
  hint?: string;
  onRun(): void;
}

export interface CommandPaletteProps {
  open: boolean;
  commands: CommandPaletteCommand[];
  onClose(): void;
}

export function CommandPalette({ open, commands, onClose }: CommandPaletteProps) {
  const [query, setQuery] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const previouslyFocusedRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (open) {
      previouslyFocusedRef.current =
        document.activeElement instanceof HTMLElement
          ? document.activeElement
          : null;
      setQuery('');
      setActiveIndex(0);
      inputRef.current?.focus();
    } else {
      previouslyFocusedRef.current?.focus();
    }
  }, [open]);

  const filtered = useMemo(() => {
    const trimmed = query.trim().toLowerCase();
    if (trimmed === '') {
      return commands;
    }
    return commands.filter((command) =>
      `${command.group} ${command.label}`.toLowerCase().includes(trimmed),
    );
  }, [commands, query]);

  useEffect(() => {
    setActiveIndex(0);
  }, [query]);

  if (!open) {
    return null;
  }

  const runCommand = (command: CommandPaletteCommand): void => {
    onClose();
    command.onRun();
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>): void => {
    if (event.key === 'Escape') {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActiveIndex((index) =>
        filtered.length === 0 ? 0 : (index + 1) % filtered.length,
      );
      return;
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActiveIndex((index) =>
        filtered.length === 0 ? 0 : (index - 1 + filtered.length) % filtered.length,
      );
      return;
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      const command = filtered[activeIndex];
      if (command !== undefined) {
        runCommand(command);
      }
    }
  };

  const activeCommand = filtered[activeIndex];

  return (
    <div
      className="command-palette-overlay"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <div
        className="command-palette"
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
      >
        <input
          ref={inputRef}
          type="text"
          className="command-palette__input"
          placeholder="Type a command…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={handleKeyDown}
          role="combobox"
          aria-expanded="true"
          aria-controls="command-palette-list"
          aria-autocomplete="list"
          aria-activedescendant={
            activeCommand === undefined
              ? undefined
              : `command-palette-option-${activeCommand.id}`
          }
        />
        <ul
          id="command-palette-list"
          role="listbox"
          aria-label="Commands"
          className="command-palette__list"
        >
          {filtered.length === 0 ? (
            <li className="command-palette__empty">No matching commands</li>
          ) : (
            filtered.map((command, index) => (
              <li
                key={command.id}
                id={`command-palette-option-${command.id}`}
                role="option"
                aria-selected={index === activeIndex}
                className={`command-palette__item${
                  index === activeIndex ? ' command-palette__item--active' : ''
                }`}
                onMouseEnter={() => setActiveIndex(index)}
                onClick={() => runCommand(command)}
              >
                <span className="command-palette__item-group">
                  {command.group}
                </span>
                <span className="command-palette__item-label">
                  {command.label}
                </span>
                {command.hint === undefined ? null : (
                  <span className="command-palette__item-hint">
                    {command.hint}
                  </span>
                )}
              </li>
            ))
          )}
        </ul>
      </div>
    </div>
  );
}
