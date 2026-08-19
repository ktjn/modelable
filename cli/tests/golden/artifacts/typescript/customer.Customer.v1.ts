/**
 * @modelable domain: customer
 * @modelable name: Customer
 * @modelable owner: customer-team
 * @modelable kind: entity
 * @modelable version: 1
 * @modelable changeKind: additive
 */
import type { CatalogProductV1 } from "./catalog.Product.v1";

export interface CustomerCustomerV1 {
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
export type Customer = CustomerCustomerV1;
