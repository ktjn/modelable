export interface AiPromptDialogProps {
  open: boolean;
  value: string;
  onChange(value: string): void;
  onSubmit(): void;
  onCancel(): void;
}

export function AiPromptDialog({
  open,
  value,
  onChange,
  onSubmit,
  onCancel,
}: AiPromptDialogProps) {
  if (!open) {
    return null;
  }

  return (
    <div className="ai-prompt" role="dialog" aria-label="Generate entity">
      <label className="ai-prompt__label">
        Describe the entity to generate
        <input
          className="ai-prompt__input"
          type="text"
          value={value}
          autoFocus
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              onSubmit();
            } else if (e.key === 'Escape') {
              onCancel();
            }
          }}
        />
      </label>
      <button type="button" onClick={onSubmit}>
        Generate
      </button>
      <button type="button" onClick={onCancel}>
        Cancel
      </button>
    </div>
  );
}
