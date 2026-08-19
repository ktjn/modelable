/**
 * @modelable domain: customer
 * @modelable name: CustomerRequest
 * @modelable owner: customer-team
 * @modelable kind: projection
 * @modelable version: 1
 * @modelable source: customer.Customer@1
 */
import type { CatalogProductV1 } from "./catalog.Product.v1";

export interface CustomerCustomerRequestV1 {
  customerId: string;
  displayName: string;
  email: string;
  status: 'active' | 'suspended' | 'deleted';
  tags: string[];
  metadata: Record<string, number>;
  address?: { line1: string; line2?: string };
  favoriteProduct?: CatalogProductV1;
}
export type CustomerRequest = CustomerCustomerRequestV1;
