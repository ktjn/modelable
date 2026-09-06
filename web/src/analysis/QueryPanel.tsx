import { useState } from 'react';

import type { BrowserCompilerClientLike } from '../client';
import type { BrowserQueryKind, BrowserQueryRequest, BrowserQueryResult } from '../protocol';

const QUERY_KINDS: BrowserQueryKind[] = [
  'declaration',
  'referencesTo',
  'lineage',
  'consumersOf',
  'dependencies',
  'dependents',
  'changes',
  'consequences',
  'facets',
  'lifecycle',
];

const COMPARISON_KINDS = new Set<BrowserQueryKind>(['changes', 'consequences']);

export interface QueryPanelProps {
  clientRef: React.RefObject<BrowserCompilerClientLike | null>;
  runtimeReady: boolean;
  workspaceRevisionRef: React.RefObject<number>;
}

export function QueryPanel({ clientRef, runtimeReady, workspaceRevisionRef }: QueryPanelProps) {
  const [kind, setKind] = useState<BrowserQueryKind>('declaration');
  const [id, setId] = useState('');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [result, setResult] = useState<BrowserQueryResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const isComparison = COMPARISON_KINDS.has(kind);
  const canSubmit = runtimeReady && !pending && (isComparison ? from !== '' && to !== '' : id !== '');

  const runQuery = () => {
    const client = clientRef.current;
    if (client === null) return;
    const request: BrowserQueryRequest = isComparison
      ? {
          $schema: 'modelable.query/v1',
          kind: 'query',
          query: kind as 'changes' | 'consequences',
          from,
          to,
        }
      : {
          $schema: 'modelable.query/v1',
          kind: 'query',
          query: kind as Exclude<BrowserQueryKind, 'changes' | 'consequences'>,
          id,
        };
    const revision = workspaceRevisionRef.current;
    const pendingQuery = client.query?.(revision, request);
    if (pendingQuery === undefined) {
      setError('Query support is not available in this runtime.');
      return;
    }
    setPending(true);
    setError(null);
    pendingQuery.then(
      (value) => {
        setPending(false);
        setResult(value);
      },
      (err: unknown) => {
        setPending(false);
        setError(err instanceof Error ? err.message : String(err));
      },
    );
  };

  return (
    <div className="analysis-panel__body query-panel" data-testid="query-panel">
      <div className="query-panel__form">
        <label className="query-panel__field">
          Query
          <select
            value={kind}
            onChange={(event) => {
              setKind(event.target.value as BrowserQueryKind);
              setResult(null);
              setError(null);
              setId('');
              setFrom('');
              setTo('');
            }}
          >
            {QUERY_KINDS.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        {isComparison ? (
          <>
            <label className="query-panel__field">
              From
              <input
                value={from}
                onChange={(event) => setFrom(event.target.value)}
                placeholder="domain.Model@1"
              />
            </label>
            <label className="query-panel__field">
              To
              <input
                value={to}
                onChange={(event) => setTo(event.target.value)}
                placeholder="domain.Model@2"
              />
            </label>
          </>
        ) : (
          <label className="query-panel__field">
            Id
            <input value={id} onChange={(event) => setId(event.target.value)} placeholder="domain.Model@1" />
          </label>
        )}
        <button type="button" onClick={runQuery} disabled={!canSubmit}>
          {pending ? 'Running…' : 'Run query'}
        </button>
      </div>
      {error !== null && (
        <p className="analysis-panel__empty" role="alert">
          {error}
        </p>
      )}
      {result !== null && (
        <pre className="query-panel__result" data-testid="query-panel-result">
          {JSON.stringify(result.data, null, 2)}
        </pre>
      )}
    </div>
  );
}
