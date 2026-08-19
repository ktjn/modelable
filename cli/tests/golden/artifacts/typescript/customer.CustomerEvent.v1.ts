/**
 * @modelable domain: customer
 * @modelable name: CustomerEvent
 * @modelable owner: customer-team
 * @modelable kind: projection
 * @modelable version: 1
 * @modelable source: customer.Customer@1
 */
import type { CatalogProductV1 } from "./catalog.Product.v1";

export interface CustomerCustomerEventV1 {
  customerId: string;
  displayName: string;
  email: string;
  internalRiskNotes?: string;
  status: 'active' | 'suspended' | 'deleted';
  tags: string[];
  metadata: Record<string, number>;
  address?: { line1: string; line2?: string };
  favoriteProduct?: CatalogProductV1;
  createdAt: string;
  updatedAt?: string;
}
export type CustomerEvent = CustomerCustomerEventV1;
