import type { ThemePreference } from '../theme';

export interface WorkbenchHeaderProps {
  status: string;
  diagnosticLabel: string;
  statusIsError: boolean;
  persistencePhase: 'saved' | 'saving' | 'memory-only' | 'recovery-required';
  languageStatus: string;
  themePreference: ThemePreference;
  resolvedTheme: 'light' | 'dark';
  onThemePreferenceChange: (preference: ThemePreference) => void;
}

const nextPreference: Record<ThemePreference, ThemePreference> = {
  system: 'light',
  light: 'dark',
  dark: 'system',
};

function themeLabel(
  preference: ThemePreference,
  resolvedTheme: 'light' | 'dark',
): string {
  if (preference === 'system') {
    return `System (${resolvedTheme})`;
  }
  return preference.charAt(0).toUpperCase() + preference.slice(1);
}

export function WorkbenchHeader({
  status,
  diagnosticLabel,
  statusIsError,
  persistencePhase,
  languageStatus,
  themePreference,
  resolvedTheme,
  onThemePreferenceChange,
}: WorkbenchHeaderProps) {
  const handleThemeClick = (): void => {
    onThemePreferenceChange(nextPreference[themePreference]);
  };

  return (
    <header className="workbench-header">
      <div className="workbench-header__brand">
        <h1 className="workbench-header__logo">Modelable</h1>
        <span className="workbench-header__tagline">Playground</span>
      </div>
      <div className="workbench-header__badges">
        <span
          className={`badge${statusIsError ? ' badge--error' : ' badge--ok'}`}
          role={statusIsError ? 'alert' : 'status'}
          aria-live={statusIsError ? 'assertive' : 'polite'}
        >
          {status}
          <span className="badge__separator">·</span>
          {diagnosticLabel}
        </span>
        <span className="badge" aria-live="polite">
          {persistencePhase === 'saved'
            ? 'Saved locally'
            : persistencePhase === 'saving'
              ? 'Saving…'
              : 'Memory-only'}
        </span>
        <span className="badge badge--muted" aria-live="polite">
          {languageStatus}
        </span>
        <button
          type="button"
          className="workbench-header__theme-toggle"
          aria-label={`Theme: ${themeLabel(themePreference, resolvedTheme)}`}
          title={`Theme: ${themeLabel(themePreference, resolvedTheme)}`}
          onClick={handleThemeClick}
        >
          {resolvedTheme === 'dark' ? 'Dark' : 'Light'}
        </button>
      </div>
    </header>
  );
}
