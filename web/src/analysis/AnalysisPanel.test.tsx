// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, test } from 'vitest';

import type {
  BrowserCompatibilityResult,
  BrowserGovernanceResult,
  BrowserLineageResult,
} from '../protocol';
import { AnalysisPanel, type AnalysisPanelProps } from './AnalysisPanel';
import type { AnalysisData } from './AnalysisPanelContainer';

afterEach(cleanup);

const emptyData: AnalysisData = {
  lineage: null,
  compatibility: null,
  governance: null,
};

const lineageResult: BrowserLineageResult = {
  workspace_revision: 1,
  projections: [
    {
      domain: 'billing',
      projection: 'BillingCustomer',
      version: 1,
      fields: [
        {
          field_name: 'id',
          kind: 'direct',
          lineage: ['customer.Customer.customerId'],
          expression: null,
        },
        {
          field_name: 'total',
          kind: 'computed',
          lineage: ['sales.Order.total'],
          expression: 'sum(total)',
        },
      ],
    },
  ],
};

const compatibilityResult: BrowserCompatibilityResult = {
  workspace_revision: 1,
  reports: [
    {
      domain_name: 'customer',
      model_name: 'Customer',
      from_version: 1,
      to_version: 2,
      status: 'additive',
      findings: [],
      changes: [
        {
          kind: 'added',
          field_name: 'email',
          previous_name: null,
          replacement: null,
          from_optional: null,
          to_optional: null,
          from_type: null,
          to_type: null,
        },
      ],
    },
  ],
  impacts: [
    {
      domain_name: 'billing',
      projection_name: 'BillingCustomer',
      version: 1,
      status: 'compatible',
      reason: null,
    },
  ],
};

const governanceResult: BrowserGovernanceResult = {
  workspace_revision: 1,
  findings: [
    {
      code: 'GOV001',
      subject: 'customer.Customer@2',
      message: 'Entity version missing owner annotation',
    },
  ],
};

function renderPanel(data: Partial<AnalysisData> = {}) {
  return render(
    <AnalysisPanel data={{ ...emptyData, ...data }} />,
  );
}

describe('AnalysisPanel', () => {
  test('renders lineage tab by default with loading state', () => {
    renderPanel();
    expect(screen.getByText('Loading lineage data…')).toBeTruthy();
  });

  test('renders lineage data with projection fields', () => {
    renderPanel({ lineage: lineageResult });
    expect(screen.getByText('billing.BillingCustomer@1')).toBeTruthy();
    expect(screen.getByText('id')).toBeTruthy();
    expect(screen.getByText('direct')).toBeTruthy();
    expect(screen.getByText('computed')).toBeTruthy();
    expect(screen.getByText('sum(total)')).toBeTruthy();
  });

  test('renders empty lineage state', () => {
    renderPanel({
      lineage: { workspace_revision: 1, projections: [] },
    });
    expect(screen.getByText('No projections defined')).toBeTruthy();
  });

  test('switches to compatibility tab', () => {
    renderPanel({ compatibility: compatibilityResult });
    fireEvent.click(screen.getByText('Compatibility'));
    expect(
      screen.getByText('customer.Customer v1 → v2'),
    ).toBeTruthy();
    expect(screen.getByText('additive')).toBeTruthy();
    expect(screen.getByText('added')).toBeTruthy();
    expect(screen.getByText('email')).toBeTruthy();
  });

  test('renders projection impacts in compatibility view', () => {
    renderPanel({ compatibility: compatibilityResult });
    fireEvent.click(screen.getByText('Compatibility'));
    expect(screen.getByText('Projection impacts')).toBeTruthy();
    expect(screen.getByText('billing.BillingCustomer')).toBeTruthy();
    expect(screen.getByText('compatible')).toBeTruthy();
  });

  test('switches to governance tab', () => {
    renderPanel({ governance: governanceResult });
    fireEvent.click(screen.getByText('Governance'));
    expect(screen.getByText('GOV001')).toBeTruthy();
    expect(screen.getByText('customer.Customer@2')).toBeTruthy();
    expect(
      screen.getByText('Entity version missing owner annotation'),
    ).toBeTruthy();
  });

  test('renders empty governance state', () => {
    renderPanel({
      governance: { workspace_revision: 1, findings: [] },
    });
    fireEvent.click(screen.getByText('Governance'));
    expect(screen.getByText('No governance findings')).toBeTruthy();
  });

  test('tabs have correct aria-pressed state', () => {
    renderPanel();
    const lineageTab = screen.getByText('Lineage');
    const compatibilityTab = screen.getByText('Compatibility');
    const governanceTab = screen.getByText('Governance');

    expect(lineageTab.getAttribute('aria-pressed')).toBe('true');
    expect(compatibilityTab.getAttribute('aria-pressed')).toBe('false');
    expect(governanceTab.getAttribute('aria-pressed')).toBe('false');

    fireEvent.click(governanceTab);
    expect(lineageTab.getAttribute('aria-pressed')).toBe('false');
    expect(governanceTab.getAttribute('aria-pressed')).toBe('true');
  });

  test('has accessible role and label', () => {
    renderPanel();
    expect(
      screen.getByRole('region', { name: 'Model analysis' }),
    ).toBeTruthy();
    expect(
      screen.getByRole('toolbar', { name: 'Analysis view' }),
    ).toBeTruthy();
  });
});
