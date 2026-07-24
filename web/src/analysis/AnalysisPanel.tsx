import { useState } from 'react';

import type {
  BrowserCompatibilityReport,
  BrowserCompatibilityResult,
  BrowserFieldChange,
  BrowserGovernanceFinding,
  BrowserGovernanceResult,
  BrowserLineageResult,
  BrowserProjectionImpact,
  BrowserProjectionLineage,
} from '../protocol';
import type { AnalysisData } from './AnalysisPanelContainer';

export type AnalysisTab = 'lineage' | 'compatibility' | 'governance';

export interface AnalysisPanelProps {
  data: AnalysisData;
}

function LineageView({ result }: { result: BrowserLineageResult | null }) {
  if (result === null) {
    return <p className="analysis-panel__empty">Loading lineage data…</p>;
  }
  if (result.projections.length === 0) {
    return <p className="analysis-panel__empty">No projections defined</p>;
  }
  return (
    <div className="analysis-panel__content">
      {result.projections.map((projection) => (
        <ProjectionLineageCard
          key={`${projection.domain}.${projection.projection}@${projection.version}`}
          projection={projection}
        />
      ))}
    </div>
  );
}

function ProjectionLineageCard({ projection }: { projection: BrowserProjectionLineage }) {
  const label = `${projection.domain}.${projection.projection}@${projection.version}`;
  return (
    <section className="analysis-card" aria-label={label}>
      <h3 className="analysis-card__title">{label}</h3>
      {projection.fields.length === 0 ? (
        <p className="analysis-card__note">No fields</p>
      ) : (
        <table className="analysis-table">
          <thead>
            <tr>
              <th>Field</th>
              <th>Kind</th>
              <th>Lineage</th>
              <th>Expression</th>
            </tr>
          </thead>
          <tbody>
            {projection.fields.map((field) => (
              <tr key={field.field_name}>
                <td className="analysis-table__mono">{field.field_name}</td>
                <td>
                  <span className={`analysis-badge analysis-badge--${field.kind}`}>
                    {field.kind}
                  </span>
                </td>
                <td className="analysis-table__mono">{field.lineage.join(' → ')}</td>
                <td className="analysis-table__mono">{field.expression ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function CompatibilityView({ result }: { result: BrowserCompatibilityResult | null }) {
  if (result === null) {
    return <p className="analysis-panel__empty">Loading compatibility data…</p>;
  }
  if (result.reports.length === 0 && result.impacts.length === 0) {
    return <p className="analysis-panel__empty">No compatibility reports</p>;
  }
  return (
    <div className="analysis-panel__content">
      {result.reports.map((report) => (
        <CompatibilityReportCard
          key={`${report.domain_name}.${report.model_name}.v${report.from_version}-v${report.to_version}`}
          report={report}
        />
      ))}
      {result.impacts.length > 0 && (
        <section className="analysis-card" aria-label="Projection impacts">
          <h3 className="analysis-card__title">Projection impacts</h3>
          <table className="analysis-table">
            <thead>
              <tr>
                <th>Projection</th>
                <th>Version</th>
                <th>Status</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody>
              {result.impacts.map((impact) => (
                <ImpactRow key={`${impact.domain_name}.${impact.projection_name}@${impact.version}`} impact={impact} />
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}

function CompatibilityReportCard({ report }: { report: BrowserCompatibilityReport }) {
  const label = `${report.domain_name}.${report.model_name} v${report.from_version} → v${report.to_version}`;
  return (
    <section className="analysis-card" aria-label={label}>
      <h3 className="analysis-card__title">
        {label}
        <span className={`analysis-badge analysis-badge--${report.status}`}>
          {report.status}
        </span>
      </h3>
      {report.findings.length > 0 && (
        <ul className="analysis-card__findings">
          {report.findings.map((finding, index) => (
            <li key={index}>{finding}</li>
          ))}
        </ul>
      )}
      {report.changes.length > 0 && (
        <table className="analysis-table">
          <thead>
            <tr>
              <th>Change</th>
              <th>Field</th>
              <th>Details</th>
            </tr>
          </thead>
          <tbody>
            {report.changes.map((change, index) => (
              <FieldChangeRow key={index} change={change} />
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function FieldChangeRow({ change }: { change: BrowserFieldChange }) {
  const details: string[] = [];
  if (change.previous_name !== null) details.push(`renamed from ${change.previous_name}`);
  if (change.replacement !== null) details.push(`replaced by ${change.replacement}`);
  if (change.from_type !== null && change.to_type !== null) {
    details.push(`${change.from_type} → ${change.to_type}`);
  }
  if (change.from_optional !== null && change.to_optional !== null && change.from_optional !== change.to_optional) {
    details.push(change.to_optional ? 'became optional' : 'became required');
  }
  return (
    <tr>
      <td>
        <span className={`analysis-badge analysis-badge--${change.kind}`}>{change.kind}</span>
      </td>
      <td className="analysis-table__mono">{change.field_name}</td>
      <td>{details.length > 0 ? details.join('; ') : '—'}</td>
    </tr>
  );
}

function ImpactRow({ impact }: { impact: BrowserProjectionImpact }) {
  return (
    <tr>
      <td className="analysis-table__mono">{impact.domain_name}.{impact.projection_name}</td>
      <td>{impact.version}</td>
      <td>
        <span className={`analysis-badge analysis-badge--${impact.status}`}>{impact.status}</span>
      </td>
      <td>{impact.reason ?? '—'}</td>
    </tr>
  );
}

function GovernanceView({ result }: { result: BrowserGovernanceResult | null }) {
  if (result === null) {
    return <p className="analysis-panel__empty">Loading governance data…</p>;
  }
  if (result.findings.length === 0) {
    return <p className="analysis-panel__empty">No governance findings</p>;
  }
  return (
    <div className="analysis-panel__content">
      <table className="analysis-table">
        <thead>
          <tr>
            <th>Code</th>
            <th>Subject</th>
            <th>Message</th>
          </tr>
        </thead>
        <tbody>
          {result.findings.map((finding, index) => (
            <GovernanceFindingRow key={index} finding={finding} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function GovernanceFindingRow({ finding }: { finding: BrowserGovernanceFinding }) {
  return (
    <tr>
      <td>
        <span className="analysis-badge">{finding.code}</span>
      </td>
      <td className="analysis-table__mono">{finding.subject}</td>
      <td>{finding.message}</td>
    </tr>
  );
}

export function AnalysisPanel({ data }: AnalysisPanelProps) {
  const [tab, setTab] = useState<AnalysisTab>('lineage');

  return (
    <div className="analysis-panel" role="region" aria-label="Model analysis">
      <div className="analysis-panel__toolbar" role="toolbar" aria-label="Analysis view">
        <button
          className={`analysis-panel__tab${tab === 'lineage' ? ' analysis-panel__tab--active' : ''}`}
          onClick={() => setTab('lineage')}
          aria-pressed={tab === 'lineage'}
        >
          Lineage
        </button>
        <button
          className={`analysis-panel__tab${tab === 'compatibility' ? ' analysis-panel__tab--active' : ''}`}
          onClick={() => setTab('compatibility')}
          aria-pressed={tab === 'compatibility'}
        >
          Compatibility
        </button>
        <button
          className={`analysis-panel__tab${tab === 'governance' ? ' analysis-panel__tab--active' : ''}`}
          onClick={() => setTab('governance')}
          aria-pressed={tab === 'governance'}
        >
          Governance
        </button>
      </div>
      <div className="analysis-panel__body">
        {tab === 'lineage' && <LineageView result={data.lineage} />}
        {tab === 'compatibility' && <CompatibilityView result={data.compatibility} />}
        {tab === 'governance' && <GovernanceView result={data.governance} />}
      </div>
    </div>
  );
}
